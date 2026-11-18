from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.selfcheck.models import (
    CheckResult,
    CheckSpec,
    Dimension,
    JudgmentMode,
    SelfcheckResult,
    Status,
    ThreeQuestion,
    derive_overall,
    summarize_dimensions,
)


def _spec(check_id: str = "D1-1", **overrides: object) -> CheckSpec:
    values = {
        "check_id": check_id,
        "title": "示例",
        "dimension": Dimension.REPRODUCIBLE,
        "mode": JudgmentMode.AUTO,
        "question": ThreeQuestion.REPRODUCE,
        "criterion": "可判定标准",
    }
    values.update(overrides)
    return CheckSpec(**values)


def _result(check_id: str, status: Status, dimension: Dimension = Dimension.REPRODUCIBLE) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        dimension=dimension,
        mode=JudgmentMode.AUTO,
        question=ThreeQuestion.REPRODUCE,
        status=status,
    )


class ModelsTest(unittest.TestCase):
    def test_enum_values_are_stable(self) -> None:
        self.assertEqual(len({item.value for item in Status}), 5)
        self.assertEqual(len({item.value for item in Dimension}), 5)
        self.assertEqual(Status.PASS.value, "通过")
        self.assertEqual(Status.BLOCKED.value, "阻塞")
        self.assertEqual(Status.MANUAL_PENDING.value, "人工待填")
        self.assertEqual(Status.UNVERIFIED.value, "未验证")

    def test_check_id_format_rejected(self) -> None:
        for bad in ("X1-1", "D6-1", "D1-A", "D1_1", ""):
            with self.assertRaises(ValueError):
                _spec(check_id=bad)

    def test_empty_criterion_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _spec(criterion="   ")

    def test_invalid_question_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _spec(question="真实")

    def test_depends_on_must_be_tuple(self) -> None:
        with self.assertRaises(ValueError):
            _spec(depends_on=["D1-2"])

    def test_unimplemented_spec_returns_unverified(self) -> None:
        result = _spec().execute(ctx=None)
        self.assertIs(result.status, Status.UNVERIFIED)
        self.assertEqual(result.sub_reason, "NOT_IMPLEMENTED")

    def test_single_status_per_result(self) -> None:
        result = _result("D1-1", Status.PASS)
        self.assertIsInstance(result.status, Status)
        self.assertEqual(result.status.value, "通过")
        self.assertEqual(
            sum(1 for field in CheckResult.__dataclass_fields__.values() if field.name == "status"), 1
        )

    def test_dimension_summary_counts(self) -> None:
        checks = [
            _result("D1-1", Status.PASS),
            _result("D1-2", Status.BLOCKED),
            _result("D2-1", Status.MANUAL_PENDING, Dimension.CAPABILITY),
            _result("D3-1", Status.WARNING, Dimension.EVIDENCE),
        ]
        summaries = summarize_dimensions(checks)
        self.assertEqual([item.dimension for item in summaries], list(Dimension))
        d1 = summaries[0]
        self.assertEqual((d1.passed, d1.blocked), (1, 1))
        self.assertEqual(summaries[1].manual_pending, 1)
        self.assertEqual(summaries[2].warning, 1)

    def test_derive_overall_priority_order(self) -> None:
        self.assertEqual(derive_overall([_result("D1-1", Status.PASS)], readonly_ok=True), ("通过", 0))
        self.assertEqual(
            derive_overall([_result("D1-1", Status.WARNING)], readonly_ok=True), ("通过（附警告）", 2)
        )
        self.assertEqual(
            derive_overall([_result("D1-1", Status.UNVERIFIED)], readonly_ok=True), ("未完成", 2)
        )
        self.assertEqual(
            derive_overall(
                [_result("D1-1", Status.WARNING), _result("D1-2", Status.MANUAL_PENDING)],
                readonly_ok=True,
            ),
            ("未完成", 3),
        )
        self.assertEqual(
            derive_overall(
                [_result("D1-1", Status.PASS), _result("D1-2", Status.BLOCKED)], readonly_ok=True
            ),
            ("不通过", 3),
        )
        self.assertEqual(
            derive_overall([_result("D1-1", Status.PASS)], readonly_ok=False), ("不通过", 3)
        )

    def test_scope_excluded_results_still_count_as_unverified(self) -> None:
        result = SelfcheckResult(checks=[_result("D1-1", Status.UNVERIFIED)])
        self.assertEqual(result.exit_code, 3)


if __name__ == "__main__":
    unittest.main()