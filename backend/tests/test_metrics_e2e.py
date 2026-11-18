from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_config
from app.domain.enums import MetricId, StageTier
from app.evidence.store import LocalEvidenceStore
from app.metrics.collectors.eval_channel import EvalConclusionReader, read_expected_digest
from app.metrics.collectors.main_flow import MainFlowEvidenceCollector
from app.metrics.collectors.runtime_sampler import SelfRunSampleReader
from app.metrics.reason_codes import UncomputableReason
from app.metrics.report import MetricReportService
from app.metrics.service import RecalcGuard, RecalcService
from app.metrics.types import RecalcConflict, RecalcTrigger
from app.repo.memory import MemoryStore
from tests.support.mainflow_builder import WINDOW_OBSERVED, build_preliminary_window, run_full_chain, seed_synthetic

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2027, 1, 6, 12, 0, tzinfo=timezone.utc)
STAGE_TIER = StageTier.PRELIMINARY
WINDOW = "2026-12"
LEGACY_REPORT = ROOT / "docs" / "devlog" / "m5-eval-report.md"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


class BuildEvidenceTest(unittest.TestCase):
    def test_run_full_chain_produces_all_evidence(self) -> None:
        store = MemoryStore()
        outcome = run_full_chain(store, "ISS-CHAIN")
        issue_id = "ISS-CHAIN"
        self.assertIsNotNone(store.effective(issue_id))
        self.assertIsNotNone(store.proof_for(issue_id))
        self.assertEqual(len(store.reproduction_attempts_for(issue_id)), 1)
        self.assertIsNotNone(store.patch_for(issue_id))
        self.assertEqual(len(store.patch_attempts_for(issue_id)), 1)
        patch_id = store.patch_for(issue_id).patch_id
        self.assertEqual(len(store.gate_attempts_for(patch_id)), 1)
        disposition = store.disposition_for(issue_id)
        self.assertIsNotNone(disposition.ready_at)
        self.assertEqual(len(store.disposition_history_for(issue_id)), 1)
        run = store.run_for_issue(issue_id)
        self.assertTrue(store.verify_chain(run.run_id))
        self.assertIsNotNone(outcome["gate"].disposition)


class RecalcE2ETest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        self.config = load_config()
        self.store = build_preliminary_window(MemoryStore(), full=1, repro_failed=1, eval=1, out_of_window=1)
        self.evidence = LocalEvidenceStore(self.root / "evidence")
        sample = SelfRunSampleReader(self.root / "samples.jsonl")
        sample.append(
            {
                "sampled_at": (NOW - timedelta(seconds=10)).isoformat(),
                "continuous_seconds": 86400.0,
                "interruptions": 0,
                "heartbeat_ok": True,
                "tracker_started_at": (NOW - timedelta(seconds=86410)).isoformat(),
                "origin": "runtime",
                "manual_interventions": 0,
            }
        )
        expected = read_expected_digest(ROOT / "eval" / "eval_set.sha256")
        collector = MainFlowEvidenceCollector(sample, EvalConclusionReader(ROOT / "eval" / "runs", expected), expected)
        self.guard = RecalcGuard()
        self.service = RecalcService(
            self.store,
            self.evidence,
            self.config,
            guard=self.guard,
            collector=collector,
            clock=lambda: NOW,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _recalc(self, trigger: RecalcTrigger = RecalcTrigger.MANUAL, actor: str = "e2e"):
        return self.service.recalc(WINDOW, STAGE_TIER, trigger, actor, now=NOW)

    def test_p01_all_main_flow_metrics_computable(self) -> None:
        result = self._recalc()
        self.assertTrue(result.succeeded)
        computations = result.computations
        for metric_id in (MetricId.M4, MetricId.M5, MetricId.M7, MetricId.M8, MetricId.M9):
            self.assertTrue(computations[metric_id].computable, metric_id)
        self.assertTrue(computations[MetricId.M6].computable)
        self.assertAlmostEqual(computations[MetricId.M4].value, 0.5)
        self.assertAlmostEqual(computations[MetricId.M5].value, 1.0)
        self.assertAlmostEqual(computations[MetricId.M7].value, 30.0)
        self.assertAlmostEqual(computations[MetricId.M9].value, 24.0)

    def test_value_matches_numerator_and_counts(self) -> None:
        result = self._recalc()
        for metric_id, computation in result.computations.items():
            self.assertEqual(
                computation.covered_count + computation.excluded_count,
                computation.denominator,
                metric_id,
            )
            if computation.computable:
                self.assertAlmostEqual(computation.value, computation.numerator / computation.covered_count, places=6)
        records = self.store.metrics_for(WINDOW, STAGE_TIER)
        self.assertEqual(len(records), 9)
        for record in records:
            self.assertIsNotNone(record.recalc_id)
            self.assertIsNotNone(record.snapshot_digest)
            self.assertEqual(record.covered_count + record.excluded_count, int(record.denominator))

    def test_channel_and_window_exclusions(self) -> None:
        result = self._recalc()
        m8 = result.computations[MetricId.M8]
        self.assertEqual(m8.channel_excluded_count, 1)
        self.assertEqual(m8.covered_count, 2)
        self.assertEqual(m8.numerator, 1)

    def test_report_generated_and_legacy_untouched(self) -> None:
        before = sha256_of(LEGACY_REPORT)
        self._recalc()
        report_service = MetricReportService(self.store, report_dir=self.root / "reports", clock=lambda: NOW)
        outcome = report_service.generate(WINDOW, STAGE_TIER, "e2e", now=NOW)
        self.assertEqual(len(outcome.rows), 9)
        self.assertTrue((self.root / "reports" / f"{outcome.record.report_id}.md").is_file())
        self.assertTrue((self.root / "reports" / f"{outcome.record.report_id}.json").is_file())
        self.assertEqual(sha256_of(LEGACY_REPORT), before)
        self.assertNotIn("缺 Pipeline 日志", outcome.markdown)
        for row in outcome.rows:
            if not row["computable"]:
                self.assertIn(row["reason_code"], {item.value for item in UncomputableReason})

    def test_three_triggers_share_service(self) -> None:
        manual = self._recalc(RecalcTrigger.MANUAL, "tester")
        dashboard = self._recalc(RecalcTrigger.DASHBOARD, "dashboard")
        scheduled = self._recalc(RecalcTrigger.SCHEDULED, "scheduler:metrics")
        for result, expected_trigger, expected_actor in (
            (manual, "MANUAL", "tester"),
            (dashboard, "DASHBOARD", "dashboard"),
            (scheduled, "SCHEDULED", "scheduler:metrics"),
        ):
            run = self.store.get_recalc(result.recalc_id)
            self.assertEqual(run.trigger, expected_trigger)
            self.assertEqual(run.actor, expected_actor)

    def test_concurrent_trigger_conflicts(self) -> None:
        with self.guard.acquire(WINDOW, STAGE_TIER, "RC-ACTIVE"):
            with self.assertRaises(RecalcConflict):
                self._recalc()


class SyntheticSeedTest(unittest.TestCase):
    def test_seed_synthetic_counts(self) -> None:
        store = MemoryStore()
        seed_synthetic(store, "2026-12", full=2, repro_failed=2, eval=1, out_of_window=1)
        main_issues = [issue for issue in store.issues.values() if issue.channel.value == "MAIN"]
        self.assertEqual(len(main_issues), 5)
        self.assertEqual(len([issue for issue in store.issues.values() if issue.channel.value == "EVAL"]), 1)
        out = [issue for issue_id, issue in store.issues.items() if issue_id.startswith("ISO-")]
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].occurred_at.month, 9)


if __name__ == "__main__":
    unittest.main()