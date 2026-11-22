from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.adapters.repo import LocalRepoAdapter
from app.config import AppConfig, MetricsConfig, load_config
from app.container import AppContainer
from app.domain.enums import MetricId, StageTier
from app.domain.models import Metric
from app.evidence.store import LocalEvidenceStore
from app.main import create_app
from app.metrics import capture_health
from app.metrics.collectors.eval_channel import EvalConclusionReader, read_expected_digest
from app.metrics.collectors.main_flow import MainFlowEvidenceCollector
from app.metrics.collectors.runtime_sampler import SelfRunSampleReader
from app.metrics.definitions import DefinitionRegistry
from app.metrics.reason_codes import UncomputableReason
from app.metrics.report import MetricReportService

from app.metrics.service import RecalcGuard, RecalcService
from app.metrics.snapshot import SNAPSHOT_SCHEMA_VERSION, SnapshotBuilder
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
from tests.support.perf_fixture import (
    EVENTS_PER_RUN,
    PERF02_ISSUES,
    PERF02_RUNS,
    build_perf02_store,
    build_small_store,
)

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


class CaptureBudgetInvariantTest(unittest.TestCase):
    """P2-5.1 / F-01…F-06、F-10：阈值、默认预算与数据规模常量守护。"""

    def test_write_block_budget_constant(self) -> None:
        self.assertEqual(capture_health.WRITE_BLOCK_BUDGET_MS, 200, "WRITE_BLOCK_BUDGET_MS 期望 200")
        self.assertEqual(
            capture_health.CAPTURE_WARNINGS,
            ("WRITE_BLOCK_EXCEEDED", "CAPTURE_SLOW"),
            "CAPTURE_WARNINGS 取值域漂移",
        )

    def test_capture_budget_default_and_no_extra_key(self) -> None:
        self.assertEqual(MetricsConfig().capture_budget_ms, 200, "capture_budget_ms 期望默认 200")
        self.assertNotIn("write_block_budget_ms", MetricsConfig.model_fields, "配置层不得新增写阻塞阈值键")

    def test_capture_budget_lower_bound_enforced(self) -> None:
        with self.assertRaises(ValidationError):
            AppConfig(metrics=MetricsConfig(capture_budget_ms=0))

    def test_snapshot_schema_version_frozen(self) -> None:
        self.assertEqual(SNAPSHOT_SCHEMA_VERSION, 1, "SNAPSHOT_SCHEMA_VERSION 期望 1")

    def test_perf_threshold_constants(self) -> None:
        from tests import test_metrics_perf

        self.assertEqual(test_metrics_perf.PERF01_LIMIT_S, 5.0, "PERF01_LIMIT_S 期望 5.0")
        self.assertEqual(test_metrics_perf.PERF02_LIMIT_S, 60.0, "PERF02_LIMIT_S 期望 60.0")
        self.assertEqual(test_metrics_perf.PERF04_LIMIT_S, 3.0, "PERF04_LIMIT_S 期望 3.0")
        self.assertEqual(test_metrics_perf.PERF02_EVENTS, 12000, "PERF02_EVENTS 期望 12000")
        self.assertEqual(test_metrics_perf.PERF_WRITE_BLOCK_MS, 200, "PERF_WRITE_BLOCK_MS 期望 200")

    def test_fixture_scale_constants(self) -> None:
        self.assertEqual(PERF02_ISSUES, 1100, "PERF02_ISSUES 期望 1100")
        self.assertEqual(PERF02_RUNS, 1000, "PERF02_RUNS 期望 1000")
        self.assertEqual(EVENTS_PER_RUN, 12, "EVENTS_PER_RUN 期望 12")


class ComplianceGuardInvariantTest(unittest.TestCase):
    """P2-5.2 / RQ-5：无 sleep、无新增 skip、无规模下调。"""

    _TESTS_DIR = Path(__file__).resolve().parent
    _SLEEP_NEEDLE = "time." + "sleep("
    _SKIP_NEEDLE = "skip" + "If"

    def _source(self, name: str) -> str:
        return (self._TESTS_DIR / name).read_text(encoding="utf-8")

    def test_default_environment_does_not_skip_perf(self) -> None:
        from tests import test_metrics_perf

        self.assertFalse(test_metrics_perf.SKIP, "默认环境不得启用 VERIFIX_SKIP_PERF")
        method = test_metrics_perf.PerfTest("test_perf02_thousand_issues_and_twelve_thousand_events")
        self.assertFalse(getattr(method, "__unittest_skip__", False), "PERF-02 用例不得被 skip 标记")

    def test_no_sleep_in_new_test_files(self) -> None:
        for name in ("test_metrics_capture_budget.py", "test_metrics_invariants.py"):
            self.assertNotIn(self._SLEEP_NEEDLE, self._source(name), f"{name} 禁止新增 sleep")

    def test_skip_count_not_increased(self) -> None:
        self.assertLessEqual(
            self._source("test_metrics_perf.py").count(self._SKIP_NEEDLE), 2, "既有 skip 基线为 2 处，不得扩大"
        )
        for name in ("test_metrics_capture_budget.py", "test_metrics_invariants.py"):
            self.assertEqual(self._source(name).count(self._SKIP_NEEDLE), 0, f"{name} 禁止新增 skip")

    def test_fixture_scale_not_reduced(self) -> None:
        store, scale = build_perf02_store()
        self.assertEqual(len(store.issues), 1100)
        self.assertEqual(len(store.runs), 1000)
        self.assertEqual(sum(len(value) for value in store.events.values()), 12000)
        self.assertEqual(scale["issues"], 1100)
        self.assertEqual(scale["events"], 12000)


class _StepClock:
    def __init__(self, step_ns: int) -> None:
        self.step_ns = step_ns
        self.value = 0

    def __call__(self) -> int:
        current = self.value
        self.value += self.step_ns
        return current


_ROW_PERF_FIELDS = frozenset(
    (
        "warnings",
        "write_block_ms",
        "write_block_budget_ms",
        "write_block_exceeded",
        "capture_ms",
        "capture_total_ms",
        "capture_budget_ms",
        "capture_slow",
        "segment_ms",
        "encode_count",
    )
)
_ROW_COMPARE_FIELDS = (
    "metric_id",
    "name",
    "definition_version",
    "unit",
    "value",
    "computable",
    "unverified",
    "unverified_reason",
    "reason_code",
    "numerator",
    "denominator",
    "covered_count",
    "excluded_count",
    "channel_excluded_count",
    "not_applicable_count",
    "trial",
    "snapshot_digest",
    "eval_run_id",
    "preliminary_target",
    "met",
    "publishable",
)
_METRIC_PAYLOAD_KEYS = frozenset(
    (
        "metric_id",
        "stage_tier",
        "window",
        "value",
        "computable",
        "source_ref",
        "definition_version",
        "reason_code",
        "channel",
        "recalc_id",
        "snapshot_id",
        "numerator",
        "denominator",
        "covered_count",
        "excluded_count",
        "channel_excluded_count",
        "not_applicable_count",
        "trial",
        "computed_at",
        "last_success_at",
    )
)


class ReportIsolationTest(unittest.TestCase):
    """P2-5.3 / RP-04：报告与对外指标口径不含性能告警字段。"""

    def _service(self, store, root: Path, budget: int) -> RecalcService:
        sample = SelfRunSampleReader(root / "samples.jsonl")
        sample.append(
            {
                "sampled_at": (NOW - timedelta(seconds=10)).isoformat(),
                "continuous_seconds": 7200.0,
                "interruptions": 0,
                "heartbeat_ok": True,
            }
        )
        expected = read_expected_digest(ROOT / "eval" / "eval_set.sha256")
        collector = MainFlowEvidenceCollector(sample, EvalConclusionReader(ROOT / "eval" / "runs", expected), expected)
        evidence = LocalEvidenceStore(root / "evidence")
        config = load_config()
        metrics = config.metrics.model_copy(
            update={"snapshot_dir": str(root / "evidence"), "self_run_sample_path": str(root / "samples.jsonl")}
        )
        config = config.model_copy(update={"metrics": metrics})
        builder = SnapshotBuilder(store, evidence, capture_budget_ms=budget, clock_ns=_StepClock(2_000_000))
        return RecalcService(
            store, evidence, config, builder=builder, guard=RecalcGuard(), collector=collector, clock=lambda: NOW
        )

    def _report(self, store, root: Path):
        return MetricReportService(store, report_dir=root / "reports", clock=lambda: NOW).generate(
            WINDOW, STAGE_TIER, "inv", now=NOW
        )

    def test_report_rows_and_markdown_have_no_performance_fields(self) -> None:
        store, _ = build_small_store()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            self._service(store, root, 200).recalc(WINDOW, STAGE_TIER, RecalcTrigger.MANUAL, "inv", now=NOW)
            outcome = self._report(store, root)
            self.assertEqual(len(outcome.rows), 9)
            for row in outcome.rows:
                self.assertFalse(_ROW_PERF_FIELDS & set(row), "报告行混入性能字段")
            for needle in ("write_block_ms", "capture_total_ms", "capture_slow", "CAPTURE_SLOW", "encode_count"):
                self.assertNotIn(needle, outcome.markdown, "报告正文混入性能字段")
            self.assertEqual(
                outcome.record.content_digest,
                hashlib.sha256(outcome.markdown.encode("utf-8")).hexdigest(),
                "报告 content_digest 计算口径漂移",
            )

    def test_report_version_increments(self) -> None:
        store, _ = build_small_store()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            self._service(store, root, 200).recalc(WINDOW, STAGE_TIER, RecalcTrigger.MANUAL, "inv", now=NOW)
            first = self._report(store, root)
            second = self._report(store, root)
        self.assertEqual([first.record.version, second.record.version], [1, 2])
        self.assertNotEqual(first.record.report_id, second.record.report_id)

    def test_warning_budget_does_not_change_report_rows(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root_a = Path(tmp) / "a"
            root_b = Path(tmp) / "b"
            store_a, _ = build_small_store()
            store_b, _ = build_small_store()
            result_a = self._service(store_a, root_a, 200).recalc(
                WINDOW, STAGE_TIER, RecalcTrigger.MANUAL, "inv", now=NOW
            )
            result_b = self._service(store_b, root_b, 1).recalc(
                WINDOW, STAGE_TIER, RecalcTrigger.MANUAL, "inv", now=NOW
            )
            self.assertEqual(result_a.warnings, [])
            self.assertEqual(result_b.warnings, ["CAPTURE_SLOW"])
            rows_a = self._report(store_a, root_a).rows
            rows_b = self._report(store_b, root_b).rows
        for row_a, row_b in zip(rows_a, rows_b):
            self.assertEqual(
                {name: row_a[name] for name in _ROW_COMPARE_FIELDS},
                {name: row_b[name] for name in _ROW_COMPARE_FIELDS},
                f"{row_a['metric_id']} 报告口径被告警污染",
            )

    def test_metrics_api_payload_keys_frozen(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            config = load_config()
            metrics = config.metrics.model_copy(update={"snapshot_dir": str(root / "evidence")})
            config = config.model_copy(update={"metrics": metrics})
            store, _ = build_small_store()
            self._service(store, root, 200).recalc(WINDOW, STAGE_TIER, RecalcTrigger.MANUAL, "inv", now=NOW)
            box = AppContainer(config)
            box.store = store
            client = TestClient(create_app(config, box))
            response = client.get("/api/v1/metrics")
            self.assertEqual(response.status_code, 200)
            for row in response.json()["data"]:
                self.assertEqual(set(row), set(_METRIC_PAYLOAD_KEYS), "指标行响应键集合漂移")

    def test_historical_report_file_unchanged(self) -> None:
        target = ROOT / "docs" / "devlog" / "m5-eval-report.md"
        before = hashlib.sha256(target.read_bytes()).hexdigest()
        store, _ = build_small_store()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            self._service(store, root, 200).recalc(WINDOW, STAGE_TIER, RecalcTrigger.MANUAL, "inv", now=NOW)
            self._report(store, root)
        after = hashlib.sha256(target.read_bytes()).hexdigest()
        self.assertEqual(before, after, "历史报告 m5-eval-report.md 被改写")


if __name__ == "__main__":
    unittest.main()