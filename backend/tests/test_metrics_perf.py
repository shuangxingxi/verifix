from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_config
from app.domain.enums import EventType, StageTier
from app.domain.models import Event, Run
from app.evidence.store import LocalEvidenceStore
from app.metrics.collectors.eval_channel import EvalConclusionReader, read_expected_digest
from app.metrics.collectors.main_flow import MainFlowEvidenceCollector
from app.metrics.collectors.runtime_sampler import SelfRunSampleReader
from app.metrics.report import MetricReportService
from app.metrics.snapshot import SnapshotBuilder
from app.metrics.service import RecalcGuard, RecalcService
from app.metrics.types import RecalcTrigger
from app.repo.memory import MemoryStore
from tests.support.mainflow_builder import seed_synthetic

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2027, 1, 6, 12, 0, tzinfo=timezone.utc)
WINDOW = "2026-12"
STAGE_TIER = StageTier.PRELIMINARY
SKIP = os.environ.get("VERIFIX_SKIP_PERF") == "1"


@unittest.skipIf(SKIP, "VERIFIX_SKIP_PERF=1")
class PerfTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        self.config = load_config()
        sample_path = self.root / "samples.jsonl"
        reader = SelfRunSampleReader(sample_path)
        reader.append(
            {
                "sampled_at": (NOW - timedelta(seconds=10)).isoformat(),
                "continuous_seconds": 7200.0,
                "interruptions": 0,
                "heartbeat_ok": True,
            }
        )
        expected = read_expected_digest(ROOT / "eval" / "eval_set.sha256")
        self.collector = MainFlowEvidenceCollector(reader, EvalConclusionReader(ROOT / "eval" / "runs", expected), expected)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _service(self, store: MemoryStore) -> RecalcService:
        return RecalcService(
            store,
            LocalEvidenceStore(self.root / "evidence"),
            self.config,
            guard=RecalcGuard(),
            collector=self.collector,
            clock=lambda: NOW,
        )

    def test_perf01_fifty_issues_under_five_seconds(self) -> None:
        store = MemoryStore()
        seed_synthetic(store, WINDOW, full=50, repro_failed=5)
        started = time.perf_counter()
        result = self._service(store).recalc(WINDOW, STAGE_TIER, RecalcTrigger.MANUAL, "perf", now=NOW)
        elapsed = time.perf_counter() - started
        print(f"\nPERF-01 55 issues recalc: {elapsed:.3f}s")
        self.assertTrue(result.succeeded)
        self.assertLess(elapsed, 5.0)

    def test_perf02_thousand_issues_and_twelve_thousand_events(self) -> None:
        store = MemoryStore()
        seed_synthetic(store, WINDOW, full=1000, repro_failed=100)
        for index in range(1000):
            issue_id = f"ISF-{index + 1:03d}"
            run = Run(
                run_id=f"RUN-{issue_id}",
                issue_id=issue_id,
                started_at=NOW - timedelta(hours=2),
                deadline_at=NOW,
            )
            store.add_run(run)
            for seq in range(12):
                store.append(
                    Event(
                        event_id=f"E-{issue_id}-{seq}",
                        run_id=run.run_id,
                        seq=seq + 1,
                        event_type=EventType.INGEST,
                        actor="perf",
                    )
                )
        builder = SnapshotBuilder(store, LocalEvidenceStore(self.root / "evidence"))
        started = time.perf_counter()
        envelope = builder.capture(WINDOW, STAGE_TIER)
        capture_elapsed = time.perf_counter() - started
        print(f"\nPERF-02 1100 issues / 12000 events capture: {capture_elapsed * 1000:.1f}ms")
        self.assertEqual(envelope.ref.event_count, 12000)
        self.assertLess(capture_elapsed, 0.2)

        started = time.perf_counter()
        result = self._service(store).recalc(WINDOW, STAGE_TIER, RecalcTrigger.MANUAL, "perf", now=NOW)
        elapsed = time.perf_counter() - started
        print(f"PERF-02 full recalc: {elapsed:.3f}s")
        self.assertTrue(result.succeeded)
        self.assertLess(elapsed, 60.0)

    def test_perf04_report_under_three_seconds(self) -> None:
        store = MemoryStore()
        seed_synthetic(store, WINDOW, full=50, repro_failed=5)
        self._service(store).recalc(WINDOW, STAGE_TIER, RecalcTrigger.MANUAL, "perf", now=NOW)
        report_service = MetricReportService(store, report_dir=self.root / "reports", clock=lambda: NOW)
        started = time.perf_counter()
        outcome = report_service.generate(WINDOW, STAGE_TIER, "perf", now=NOW)
        elapsed = time.perf_counter() - started
        print(f"\nPERF-04 report generation: {elapsed:.3f}s")
        self.assertEqual(len(outcome.rows), 9)
        self.assertLess(elapsed, 3.0)

    def test_read01_recalc_is_read_only(self) -> None:
        store = MemoryStore()
        seed_synthetic(store, WINDOW, full=10, repro_failed=2)
        snapshot_digest = store.snapshot_digest()
        content_digest = store.content_digest()
        self._service(store).recalc(WINDOW, STAGE_TIER, RecalcTrigger.MANUAL, "perf", now=NOW)
        self.assertEqual(store.snapshot_digest(), snapshot_digest)
        self.assertEqual(store.content_digest(), content_digest)


if __name__ == "__main__":
    unittest.main()

@unittest.skipIf(SKIP, "VERIFIX_SKIP_PERF=1")
class EvalPerfBudgetTest(unittest.TestCase):
    def test_perf01_isolation_self_check_within_budget(self) -> None:
        from app.eval.isolation import AccessAuditLog, AnswerIsolationGuard

        class _Probe:
            def probe_denied(self):
                return []

            def cases_readable(self):
                return True

        guard = AnswerIsolationGuard(
            ROOT / "eval" / "cases",
            ROOT / "eval" / "expected",
            audit=AccessAuditLog(Path(tempfile.mkdtemp()) / "audit.jsonl"),
            probe=_Probe(),
        )
        started = time.perf_counter()
        verdict = guard.self_check()
        elapsed_ms = (time.perf_counter() - started) * 1000
        self.assertTrue(verdict.ok)
        self.assertLessEqual(elapsed_ms, 2000)

    def test_perf02_digest_triple_within_budget(self) -> None:
        from app.eval.digest import digest_triple

        started = time.perf_counter()
        digest_triple(ROOT / "eval" / "cases", ROOT / "eval" / "expected", "1.0.0")
        elapsed_ms = (time.perf_counter() - started) * 1000
        self.assertLessEqual(elapsed_ms, 500)

    def test_perf03_cross_report_consistency_within_budget(self) -> None:
        from app.metrics.consistency import CrossReportConsistencyChecker

        rows = [
            {
                "metric_id": f"M{index}",
                "value": 0.5,
                "computable": True,
                "unverified": False,
                "reason_code": None,
                "numerator": 1.0,
                "denominator": 2.0,
                "covered_count": 2,
                "excluded_count": 0,
                "channel_excluded_count": 0,
                "not_applicable_count": 0,
                "source_ref": "ref",
                "recalc_id": "RC-1",
                "snapshot_digest": "a" * 64,
                "eval_run_id": "EVALRUN-1",
                "definition_version": "v2",
                "met": True,
            }
            for index in range(1, 10)
        ]
        started = time.perf_counter()
        report = CrossReportConsistencyChecker().compare(rows, rows)
        elapsed_ms = (time.perf_counter() - started) * 1000
        self.assertTrue(report.consistent)
        self.assertLessEqual(elapsed_ms, 1000)

    def test_perf05_leak_scan_within_budget(self) -> None:
        from app.eval.leak_scan import LeakScanner

        started = time.perf_counter()
        report = LeakScanner().scan_directory(ROOT / "eval" / "cases")
        elapsed_ms = (time.perf_counter() - started) * 1000
        self.assertEqual(report.hits, 0, report.hit_fields)
        self.assertLessEqual(elapsed_ms, 5000)
