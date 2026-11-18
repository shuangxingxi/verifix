from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.adapters.repo import LocalRepoAdapter
from app.config import load_config
from app.container import AppContainer
from app.domain.enums import MetricId, StageTier
from app.domain.models import Metric
from app.evidence.store import LocalEvidenceStore
from app.main import create_app
from app.metrics.collectors.eval_channel import EvalConclusionReader, read_expected_digest
from app.metrics.collectors.main_flow import MainFlowEvidenceCollector
from app.metrics.collectors.runtime_sampler import SelfRunSampleReader
from app.metrics.definitions import DefinitionRegistry
from app.metrics.reason_codes import UncomputableReason
from app.metrics.service import RecalcGuard, RecalcService
from app.metrics.types import RecalcTrigger
from app.orchestration.state_machine import (
    AUXILIARY_TRANSITIONS,
    PRIMARY_TRANSITIONS,
    StateMachine,
    StateTransitionError,
    Transition,
    TransitionContext,
)
from app.repo.memory import MemoryStore
from app.tools.errors import ForbiddenBranchError
from tests.support.mainflow_builder import WINDOW_OBSERVED, build_preliminary_window, make_issue

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2027, 1, 6, 12, 0, tzinfo=timezone.utc)
STAGE_TIER = StageTier.PRELIMINARY
WINDOW = "2026-12"


class InvariantFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        self.config = load_config()
        metrics = self.config.metrics.model_copy(
            update={
                "snapshot_dir": str(self.root / "evidence"),
                "self_run_sample_path": str(self.root / "samples.jsonl"),
            }
        )
        self.config = self.config.model_copy(update={"metrics": metrics})
        self.store = build_preliminary_window(MemoryStore(), full=1, repro_failed=1, eval=1)
        sample = SelfRunSampleReader(self.root / "samples.jsonl")
        sample.append(
            {
                "sampled_at": (NOW - timedelta(seconds=10)).isoformat(),
                "continuous_seconds": 86400.0,
                "interruptions": 0,
                "heartbeat_ok": True,
            }
        )
        expected = read_expected_digest(ROOT / "eval" / "eval_set.sha256")
        collector = MainFlowEvidenceCollector(sample, EvalConclusionReader(ROOT / "eval" / "runs", expected), expected)
        self.service = RecalcService(
            self.store,
            LocalEvidenceStore(self.root / "evidence"),
            self.config,
            guard=RecalcGuard(),
            collector=collector,
            clock=lambda: NOW,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()


class TransitionInvariantTest(unittest.TestCase):
    def test_transition_sets_frozen(self) -> None:
        self.assertEqual(len(PRIMARY_TRANSITIONS), 17)
        self.assertEqual(len(AUXILIARY_TRANSITIONS), 3)
        self.assertEqual(set(AUXILIARY_TRANSITIONS), {Transition.T0, Transition.T5, Transition.T8B})
        for transition in (Transition.T7, Transition.T8, Transition.T8B, Transition.T16, Transition.T18):
            self.assertTrue(transition in PRIMARY_TRANSITIONS or transition in AUXILIARY_TRANSITIONS)

    def test_skip_transition_rejected(self) -> None:
        store = MemoryStore()
        issue = make_issue(store, "ISS-JUMP", observed_at=WINDOW_OBSERVED)
        with self.assertRaises(StateTransitionError):
            StateMachine().target_status(issue.status, Transition.T7, TransitionContext(issue=issue))

    def test_main_is_hard_rejected(self) -> None:
        repo = LocalRepoAdapter()
        repo.load_from_directory(ROOT / "verifix-target")
        with self.assertRaises(ForbiddenBranchError):
            repo.create_branch("verifix-target", "main", "abc")
        with self.assertRaises(ForbiddenBranchError):
            repo.merge_to_release_auto("verifix-target", "main")
        self.assertTrue(repo.violations)


class ComputabilityInvariantTest(InvariantFixture):
    def test_uncomputable_has_no_value_and_known_reason(self) -> None:
        self.service.recalc(WINDOW, STAGE_TIER, RecalcTrigger.MANUAL, "invariant", now=NOW)
        allowed = {item.value for item in UncomputableReason}
        for record in self.store.metrics_for(WINDOW, STAGE_TIER):
            if not record.computable:
                self.assertIsNone(record.value)
                self.assertIn(record.reason_code, allowed)
            else:
                self.assertIsNotNone(record.value)
                self.assertIsNone(record.reason_code)
            if record.trial:
                self.assertEqual(record.reason_code, "WINDOW_NOT_CLOSED")
                self.assertFalse(record.computable)

    def test_eval_channel_excluded_from_main_metrics(self) -> None:
        result = self.service.recalc(WINDOW, STAGE_TIER, RecalcTrigger.MANUAL, "invariant", now=NOW)
        for metric_id in (MetricId.M4, MetricId.M5, MetricId.M6, MetricId.M7, MetricId.M8):
            self.assertEqual(result.computations[metric_id].channel_excluded_count, 1, metric_id)

    def test_recalc_does_not_change_previous_window(self) -> None:
        legacy = Metric(
            metric_id=MetricId.M4,
            stage_tier=STAGE_TIER,
            window="2026-11",
            definition_version="v1",
            value=0.42,
            source_ref="legacy",
            recalc_id="RC-LEGACY",
        )
        self.store.add_metric(legacy)
        before = self.store.metrics[(MetricId.M4.value, "PRELIMINARY", "2026-11")].model_dump()
        self.service.recalc(WINDOW, STAGE_TIER, RecalcTrigger.MANUAL, "invariant", now=NOW)
        after = self.store.metrics[(MetricId.M4.value, "PRELIMINARY", "2026-11")].model_dump()
        self.assertEqual(before, after)

    def test_v1_definitions_and_legacy_metrics_readable(self) -> None:
        registry = DefinitionRegistry()
        self.assertEqual(registry.by_version(MetricId.M6, "v1").definition_version, "v1")
        self.assertEqual(registry.by_version(MetricId.M6, "v2").definition_version, "v2")
        legacy = Metric(
            metric_id=MetricId.M4,
            stage_tier=STAGE_TIER,
            window="2026-10",
            definition_version="v1",
            value=0.1,
            source_ref="legacy",
        )
        self.store.add_metric(legacy)


class ApiCompatibilityInvariantTest(InvariantFixture):
    def test_metrics_api_is_field_superset(self) -> None:
        self.service.recalc(WINDOW, STAGE_TIER, RecalcTrigger.MANUAL, "invariant", now=NOW)
        box = AppContainer(self.config)
        box.store = self.store
        client = TestClient(create_app(self.config, box))
        response = client.get("/api/v1/metrics")
        self.assertEqual(response.status_code, 200)
        rows = response.json()["data"]
        self.assertEqual(len(rows), 9)
        legacy_fields = {"metric_id", "stage_tier", "window", "value", "computable", "source_ref", "definition_version"}
        for row in rows:
            self.assertTrue(legacy_fields <= set(row))
            self.assertIn("reason_code", row)
            self.assertIn("recalc_id", row)
        filtered = client.get("/api/v1/metrics", params={"window": "2026-12", "tier": "PRELIMINARY"})
        self.assertEqual(len(filtered.json()["data"]), 9)
        empty = client.get("/api/v1/metrics", params={"window": "2025-01"})
        self.assertEqual(empty.json()["data"], [])

    def test_legacy_metric_construction_unchanged(self) -> None:
        metric = Metric(
            metric_id=MetricId.M4,
            stage_tier=STAGE_TIER,
            window="2026-12",
            definition_version="v1",
            value=0.5,
            source_ref="legacy",
        )
        self.assertTrue(metric.computable)
        self.assertIsNone(metric.reason_code)


if __name__ == "__main__":
    unittest.main()