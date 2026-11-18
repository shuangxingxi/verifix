from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.enums import MetricId, StageTier
from app.metrics.collectors.main_flow import CollectedEvidence
from app.metrics.definitions import DefinitionRegistry
from app.metrics.judgment import ComputabilityPipeline, JudgmentError, MetricComputation
from app.metrics.reason_codes import JudgmentStage, UncomputableReason
from app.metrics.rules.base import RuleExclusion, RuleResult

NOW_CLOSED = datetime(2027, 1, 2, tzinfo=timezone.utc)
NOW_OPEN = datetime(2026, 12, 5, tzinfo=timezone.utc)
REGISTRY = DefinitionRegistry()


def definition(metric_id: MetricId = MetricId.M4):
    return REGISTRY.effective(metric_id, NOW_CLOSED)


def evidence(now_window: bool = True) -> CollectedEvidence:
    return CollectedEvidence(
        window="2026-12",
        tier=StageTier.PRELIMINARY,
        window_start=datetime(2026, 12, 1, tzinfo=timezone.utc),
        window_end=datetime(2027, 1, 1, tzinfo=timezone.utc),
    )


def result(
    metric_id: MetricId = MetricId.M4,
    *,
    numerator: float = 8.0,
    covered: int = 10,
    excluded: int = 0,
    evidence_present: bool = True,
    details: dict | None = None,
    exclusion_reason: str = "EVIDENCE_MISSING",
) -> RuleResult:
    exclusions = [
        RuleExclusion(f"ISS-X{index}", exclusion_reason, "detail", metric_id) for index in range(excluded)
    ]
    return RuleResult(
        metric_id=metric_id,
        numerator=numerator,
        covered_count=covered,
        excluded_count=excluded,
        exclusions=exclusions,
        source_ref="test-source",
        evidence_present=evidence_present,
        details=details or {},
    )


class PipelineBasicTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pipeline = ComputabilityPipeline()

    def test_computable_requires_closed_window(self) -> None:
        computation = self.pipeline.evaluate(MetricId.M4, definition(), result(), evidence(), NOW_CLOSED)
        self.assertTrue(computation.computable)
        self.assertAlmostEqual(computation.value, 0.8)
        self.assertIsNone(computation.reason_code)
        self.assertEqual(computation.denominator, 10)

    def test_definition_missing_short_circuits(self) -> None:
        computation = self.pipeline.evaluate(MetricId.M4, None, result(), evidence(), NOW_CLOSED)
        self.assertFalse(computation.computable)
        self.assertIs(computation.reason_code, UncomputableReason.DEFINITION_UNREGISTERED)
        self.assertIs(computation.stage, JudgmentStage.DEFINITION)

    def test_source_missing(self) -> None:
        computation = self.pipeline.evaluate(
            MetricId.M6,
            definition(MetricId.M6),
            result(MetricId.M6, evidence_present=False, details={"missing": "GateAttempt/GateResult 缺失"}),
            evidence(),
            NOW_CLOSED,
        )
        self.assertIs(computation.reason_code, UncomputableReason.SOURCE_MISSING)
        self.assertIn("GateAttempt", computation.missing)

    def test_denominator_empty(self) -> None:
        computation = self.pipeline.evaluate(MetricId.M4, definition(), result(covered=0, excluded=0), evidence(), NOW_CLOSED)
        self.assertIs(computation.reason_code, UncomputableReason.DENOMINATOR_EMPTY)

    def test_denominator_empty_beats_window_not_closed(self) -> None:
        computation = self.pipeline.evaluate(MetricId.M4, definition(), result(covered=0, excluded=0), evidence(), NOW_OPEN)
        self.assertIs(computation.reason_code, UncomputableReason.DENOMINATOR_EMPTY)
        self.assertFalse(computation.trial)

    def test_window_not_closed_sets_trial(self) -> None:
        computation = self.pipeline.evaluate(MetricId.M4, definition(), result(), evidence(), NOW_OPEN)
        self.assertIs(computation.reason_code, UncomputableReason.WINDOW_NOT_CLOSED)
        self.assertTrue(computation.trial)
        self.assertIsNone(computation.value)

    def test_m5_first_attempt_missing(self) -> None:
        computation = self.pipeline.evaluate(
            MetricId.M5,
            definition(MetricId.M5),
            result(MetricId.M5, covered=0, excluded=3, details={"first_attempt_missing_all": True}),
            evidence(),
            NOW_CLOSED,
        )
        self.assertIs(computation.reason_code, UncomputableReason.FIRST_ATTEMPT_EVIDENCE_MISSING)


class ExclusionThresholdTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pipeline = ComputabilityPipeline(exclusion_ratio_limit=0.10)

    def test_n13_10_1_percent_is_coverage_insufficient(self) -> None:
        computation = self.pipeline.evaluate(
            MetricId.M4, definition(), result(covered=89, excluded=10), evidence(), NOW_CLOSED
        )
        self.assertFalse(computation.computable)
        self.assertIs(computation.reason_code, UncomputableReason.COVERAGE_INSUFFICIENT)
        self.assertIsNone(computation.value)

    def test_p08_9_9_percent_is_computable(self) -> None:
        computation = self.pipeline.evaluate(
            MetricId.M4, definition(), result(covered=91, excluded=10), evidence(), NOW_CLOSED
        )
        self.assertTrue(computation.computable)
        self.assertIsNotNone(computation.value)
        self.assertEqual(computation.excluded_count, 10)

    def test_all_inconsistent_with_zero_covered_is_inconsistent(self) -> None:
        computation = self.pipeline.evaluate(
            MetricId.M8,
            definition(MetricId.M8),
            result(MetricId.M8, covered=0, excluded=3, exclusion_reason="EVIDENCE_INCONSISTENT"),
            evidence(),
            NOW_CLOSED,
        )
        self.assertIs(computation.reason_code, UncomputableReason.EVIDENCE_INCONSISTENT)

    def test_pre_exclusions_are_merged(self) -> None:
        collected = evidence()
        collected.pre_exclusions.append(
            {"issue_id": "ISS-U", "reason_code": "EVIDENCE_INCONSISTENT", "detail": "通道不可判"}
        )
        computation = self.pipeline.evaluate(MetricId.M4, definition(), result(covered=1, excluded=0), collected, NOW_CLOSED)
        self.assertEqual(computation.excluded_count, 1)
        self.assertEqual(computation.denominator, 2)
        self.assertEqual(computation.exclusions[0].issue_id, "ISS-U")


class EmptyValueGuardTest(unittest.TestCase):
    def test_uncomputable_with_value_rejected(self) -> None:
        with self.assertRaises(JudgmentError):
            MetricComputation(metric_id=MetricId.M4, computable=False, value=0.0, reason_code=UncomputableReason.SOURCE_MISSING)

    def test_computable_with_reason_rejected(self) -> None:
        with self.assertRaises(JudgmentError):
            MetricComputation(metric_id=MetricId.M4, computable=True, value=0.5, reason_code=UncomputableReason.SOURCE_MISSING)

    def test_trial_with_computable_rejected(self) -> None:
        with self.assertRaises(JudgmentError):
            MetricComputation(metric_id=MetricId.M4, computable=True, value=0.5, trial=True)

    def test_trial_requires_window_reason(self) -> None:
        with self.assertRaises(JudgmentError):
            MetricComputation(metric_id=MetricId.M4, computable=False, trial=True, reason_code=UncomputableReason.SOURCE_MISSING)

    def test_unknown_reason_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MetricComputation(metric_id=MetricId.M4, computable=False, reason_code="LOG_MISSING")

    def test_count_consistency_enforced(self) -> None:
        with self.assertRaises(JudgmentError):
            MetricComputation(
                metric_id=MetricId.M4,
                computable=False,
                reason_code=UncomputableReason.DENOMINATOR_EMPTY,
                covered_count=1,
                excluded_count=0,
                denominator=3,
            )


class JudgmentPurityTest(unittest.TestCase):
    def test_judgment_does_not_touch_store(self) -> None:
        from app.repo.memory import MemoryStore

        store = MemoryStore()
        before = store.content_digest()
        ComputabilityPipeline().evaluate(MetricId.M4, definition(), result(), evidence(), NOW_CLOSED)
        self.assertEqual(store.content_digest(), before)

    def test_no_issue_views_needed(self) -> None:
        collected = evidence()
        collected.issues = []
        computation = ComputabilityPipeline().evaluate(MetricId.M4, definition(), result(), collected, NOW_CLOSED)
        self.assertTrue(computation.computable)


if __name__ == "__main__":
    unittest.main()