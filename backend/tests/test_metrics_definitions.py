from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import ValidationError

from app.domain.enums import MetricChannel, MetricId, StageTier
from app.domain.models import (
    ExclusionEntry,
    Metric,
    MetricDefinitionRecord,
    MetricReport,
    MetricSnapshotRef,
    RecalcRun,
)
from app.metrics.definitions import (
    V1,
    V2,
    DefinitionRegistry,
    MetricDirection,
    MetricUnit,
    V2_EFFECTIVE_AT,
    default_definitions,
)
from app.metrics.reason_codes import (
    REASON_LABELS,
    UncomputableReason,
    coerce_reason,
    is_reason_code,
    reason_label,
    stage_of,
)
from app.repo.memory import MemoryStore, SNAPSHOT_COLLECTIONS


class ReasonCodeTest(unittest.TestCase):
    def test_exactly_eight_reason_codes(self) -> None:
        self.assertEqual(
            {item.value for item in UncomputableReason},
            {
                "SOURCE_MISSING",
                "DENOMINATOR_EMPTY",
                "EVIDENCE_MISSING",
                "EVIDENCE_INCONSISTENT",
                "COVERAGE_INSUFFICIENT",
                "DEFINITION_UNREGISTERED",
                "WINDOW_NOT_CLOSED",
                "FIRST_ATTEMPT_EVIDENCE_MISSING",
            },
        )

    def test_label_mapping_covers_all_codes(self) -> None:
        self.assertEqual(set(REASON_LABELS), set(UncomputableReason))
        for item in UncomputableReason:
            self.assertTrue(reason_label(item))
            self.assertIsNotNone(stage_of(item))

    def test_illegal_reason_rejected(self) -> None:
        with self.assertRaises(ValueError):
            coerce_reason("LOG_MISSING")
        self.assertFalse(is_reason_code("LOG_MISSING"))
        self.assertTrue(is_reason_code("SOURCE_MISSING"))
        self.assertTrue(is_reason_code(UncomputableReason.SOURCE_MISSING))


class DefinitionRegistryTest(unittest.TestCase):
    def test_all_nine_effective_v2_at_december(self) -> None:
        registry = DefinitionRegistry()
        effective = registry.all_effective(V2_EFFECTIVE_AT)
        self.assertEqual(set(effective), set(MetricId))
        for metric_id, definition in effective.items():
            self.assertEqual(definition.definition_version, V2, metric_id)

    def test_v1_archived_and_unmodified(self) -> None:
        registry = DefinitionRegistry()
        before = registry.by_version(MetricId.M6, V1)
        self.assertIsNotNone(before)
        self.assertIn("Pipeline 日志", before.source_bindings[0])
        historical = registry.effective(MetricId.M6, datetime(2026, 6, 1, tzinfo=timezone.utc))
        self.assertEqual(historical.definition_version, V1)
        self.assertEqual(historical.source_bindings, before.source_bindings)
        self.assertEqual(registry.by_version(MetricId.M6, V1).source_bindings, before.source_bindings)

    def test_m6_v2_uses_gate_sources(self) -> None:
        registry = DefinitionRegistry()
        m6 = registry.effective(MetricId.M6, V2_EFFECTIVE_AT)
        self.assertEqual(m6.definition_version, V2)
        self.assertIn("GateResult", m6.source_bindings)
        self.assertIn("GateAttempt", m6.source_bindings)
        self.assertNotIn("Pipeline 日志", m6.source_bindings)

    def test_m2_marked_pending_alignment(self) -> None:
        registry = DefinitionRegistry()
        m2 = registry.effective(MetricId.M2, V2_EFFECTIVE_AT)
        self.assertIn("口径待评测通道对齐", m2.note)

    def test_targets_registered(self) -> None:
        registry = DefinitionRegistry()
        expected = {
            MetricId.M1: 0.50,
            MetricId.M4: 0.60,
            MetricId.M5: 0.45,
            MetricId.M9: 24.0,
        }
        for metric_id, target in expected.items():
            self.assertEqual(registry.effective(metric_id, V2_EFFECTIVE_AT).preliminary_target, target)
        self.assertIs(registry.effective(MetricId.M6, V2_EFFECTIVE_AT).direction, MetricDirection.LOWER_IS_BETTER)
        self.assertIs(registry.effective(MetricId.M7, V2_EFFECTIVE_AT).unit, MetricUnit.MINUTES)
        self.assertIs(registry.effective(MetricId.M9, V2_EFFECTIVE_AT).unit, MetricUnit.HOURS)

    def test_missing_definitions_reported(self) -> None:
        partial = DefinitionRegistry([])
        for definition in default_definitions():
            if definition.metric_id in {MetricId.M6, MetricId.M7}:
                continue
            partial.register(definition)
        self.assertEqual(partial.missing(V2_EFFECTIVE_AT), {MetricId.M6, MetricId.M7})
        self.assertNotIn(MetricId.M6, partial.all_effective(V2_EFFECTIVE_AT))

    def test_all_definitions_use_registered_channels(self) -> None:
        for definition in default_definitions():
            self.assertIsInstance(definition.channel, MetricChannel)


class MetricRecordCompatibilityTest(unittest.TestCase):
    def test_legacy_metric_constructs_with_original_fields(self) -> None:
        metric = Metric(
            metric_id=MetricId.M4,
            stage_tier=StageTier.PRELIMINARY,
            window="2026-12",
            definition_version="v1",
            value=0.7,
            source_ref="proof.pre_patch_result",
        )
        self.assertTrue(metric.computable)
        self.assertIs(metric.channel, MetricChannel.MAIN)
        self.assertIsNone(metric.reason_code)
        self.assertIsNone(metric.recalc_id)
        self.assertEqual(metric.covered_count, 0)
        self.assertFalse(metric.trial)

    def test_uncomputable_with_zero_still_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            Metric(
                metric_id=MetricId.M4,
                stage_tier=StageTier.PRELIMINARY,
                window="2026-12",
                definition_version="v2",
                value=0,
                source_ref="x",
                computable=False,
            )

    def test_trial_cannot_be_computable(self) -> None:
        with self.assertRaises(ValidationError):
            Metric(
                metric_id=MetricId.M4,
                stage_tier=StageTier.PRELIMINARY,
                window="2026-12",
                definition_version="v2",
                value=0.5,
                source_ref="x",
                trial=True,
            )


class MetricRepositoryShapeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = MemoryStore()

    def test_new_collections_are_transactional(self) -> None:
        for name in ("metric_definitions", "metric_snapshots", "recalc_runs", "metric_exclusions", "metric_reports"):
            self.assertIn(name, SNAPSHOT_COLLECTIONS)
        with self.assertRaises(RuntimeError):
            with self.store.transaction():
                record = MetricDefinitionRecord(
                    metric_id=MetricId.M4,
                    name="复现成功率",
                    numerator_spec="n",
                    denominator_spec="d",
                    unit="RATIO",
                    channel=MetricChannel.MAIN,
                    definition_version=V2,
                    effective_at=V2_EFFECTIVE_AT,
                )
                self.store.put_definition(record)
                self.store.put_snapshot(
                    MetricSnapshotRef(snapshot_id="SNAP-1", window="2026-12", tier=StageTier.PRELIMINARY, digest="a" * 64)
                )
                self.store.put_recalc(
                    RecalcRun(recalc_id="RC-1", window="2026-12", tier=StageTier.PRELIMINARY, trigger="MANUAL", actor="tester", status="RUNNING")
                )
                self.store.put_exclusions(
                    "RC-1",
                    MetricId.M4,
                    [ExclusionEntry(issue_id="ISS-1", reason_code="EVIDENCE_MISSING", metric_id=MetricId.M4, recalc_id="RC-1")],
                )
                self.store.put_report(
                    MetricReport(report_id="RPT-1", window="2026-12", tier=StageTier.PRELIMINARY, definition_version=V2, conclusion="PASS")
                )
                raise RuntimeError("rollback")
        self.assertEqual(self.store.metric_definitions, {})
        self.assertEqual(self.store.metric_snapshots, {})
        self.assertEqual(self.store.recalc_runs, {})
        self.assertEqual(self.store.metric_exclusions, {})
        self.assertEqual(self.store.metric_reports, {})

    def test_metric_unique_key_is_metric_tier_window(self) -> None:
        first = Metric(
            metric_id=MetricId.M4,
            stage_tier=StageTier.PRELIMINARY,
            window="2026-12",
            definition_version=V1,
            value=0.1,
            source_ref="s",
        )
        second = first.model_copy(update={"value": 0.9, "definition_version": V2})
        self.store.add_metric(first)
        self.store.add_metric(second)
        self.assertEqual(len(self.store.metrics), 1)
        self.assertEqual(self.store.metrics_for("2026-12", StageTier.PRELIMINARY)[0].value, 0.9)

    def test_report_version_increments(self) -> None:
        base = MetricReport(
            report_id="RPT-1",
            window="2026-12",
            tier=StageTier.PRELIMINARY,
            definition_version=V2,
            conclusion="PASS",
            version=1,
        )
        self.store.put_report(base)
        self.assertEqual(self.store.next_report_version("2026-12", StageTier.PRELIMINARY), 2)
        self.store.put_report(base.model_copy(update={"report_id": "RPT-2", "version": 2}))
        self.assertEqual(self.store.next_report_version("2026-12", StageTier.PRELIMINARY), 3)


if __name__ == "__main__":
    unittest.main()