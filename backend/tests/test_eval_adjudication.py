from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.envelope import ApiError, ErrorCode
from app.domain.enums import EvalCategory, FixParadigm, MetricId, ProofResult, StageTier
from app.domain.models import MetricReport
from app.eval.adjudication import AdjudicationService
from app.eval.models import EvalObservation, ExpectedAnswer
from app.metrics.eval_special_report import EvalSpecialReportBuilder
from app.metrics.report import ReportOutcome

BINDING = "a" * 64
NOW = datetime(2027, 1, 6, 12, 0, tzinfo=timezone.utc)


def answer(case_id: str, category: EvalCategory, reachable: bool, reject: bool = False) -> ExpectedAnswer:
    return ExpectedAnswer(
        case_id=case_id,
        set_version="1.0.0",
        category=category,
        reachable=reachable,
        fixable=category is not EvalCategory.NEGATIVE,
        expected_fix_kind=FixParadigm.PARAMETERIZED_QUERY,
        should_reject=reject,
        content_digest=f"digest-{case_id}",
    )


def observation(case_id: str, detected: bool, verdict: str | None, patch: str = "PATCHED") -> EvalObservation:
    return EvalObservation(
        case_id=case_id,
        detected=detected,
        verdict=verdict,
        repro_status="PROVEN",
        patch_status=patch,
        binding_digest=BINDING,
    )


class AdjudicationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.service = AdjudicationService(Path(self.tmp.name))
        self.answers = [
            answer("EVAL-0001", EvalCategory.POSITIVE, True),
            answer("EVAL-0021", EvalCategory.NEGATIVE, False),
            answer("EVAL-0031", EvalCategory.BOUNDARY, True),
            answer("EVAL-0050", EvalCategory.ADVERSARIAL, True, reject=True),
        ]
        self.observations = [
            observation("EVAL-0001", True, "REACHABLE"),
            observation("EVAL-0021", False, "UNREACHABLE", "NOT_APPLICABLE"),
            observation("EVAL-0031", True, "REACHABLE"),
            observation("EVAL-0050", True, "REACHABLE", "REJECTED_SHALLOW"),
        ]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_aggregates_match_samples(self) -> None:
        result = self.service.adjudicate("EVALRUN-0001", BINDING, self.answers, self.observations)
        self.assertEqual(result.verdict.m1.numerator, 2)
        self.assertEqual(result.verdict.m1.denominator, 2)
        self.assertEqual(result.verdict.m3.numerator, 3)
        self.assertEqual(result.verdict.m3.denominator, 3)
        self.assertIsNone(result.verdict.m2)
        self.assertTrue(all(item.passed for item in result.verdict.case_verdicts))

    def test_idempotent_single_file(self) -> None:
        first = self.service.adjudicate("EVALRUN-0001", BINDING, self.answers, self.observations)
        second = self.service.adjudicate("EVALRUN-0001", BINDING, self.answers, self.observations)
        self.assertFalse(first.idempotent)
        self.assertTrue(second.idempotent)
        self.assertEqual(len(list(Path(self.tmp.name).glob("*.verdict.json"))), 1)

    def test_binding_mismatch_rejected(self) -> None:
        with self.assertRaises(ApiError) as raised:
            self.service.adjudicate("EVALRUN-0002", "b" * 64, self.answers, self.observations)
        self.assertIs(raised.exception.code, ErrorCode.EVAL_DIGEST_MISMATCH)

    def test_no_answer_echo_in_verdict(self) -> None:
        result = self.service.adjudicate("EVALRUN-0001", BINDING, self.answers, self.observations)
        text = result.path.read_text(encoding="utf-8")
        for token in ("should_reject", "expected_fix_kind", "PARAMETERIZED_QUERY"):
            self.assertNotIn(token, text)


class SpecialReportGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        record = MetricReport(
            report_id="RPT-2026-12-PRELIMINARY-0001",
            version=1,
            window="2026-12",
            tier=StageTier.PRELIMINARY,
            definition_version="v2",
            conclusion="UNDETERMINED",
            generated_at=NOW,
        )
        self.rows = [
            {"metric_id": metric_id.value, "value": 1.0, "computable": True, "reason_code": None}
            for metric_id in MetricId
        ]
        self.main = ReportOutcome(record=record, markdown="", rows=self.rows)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_unadjudicated_run_is_rejected(self) -> None:
        builder = EvalSpecialReportBuilder(Path(self.tmp.name))
        with self.assertRaises(ApiError) as raised:
            builder.build(self.main, verdict=None)
        self.assertIs(raised.exception.code, ErrorCode.EVAL_NOT_ADJUDICATED)

    def test_reference_rows_have_no_values(self) -> None:
        answers = [answer("EVAL-0001", EvalCategory.POSITIVE, True)]
        observations = [observation("EVAL-0001", True, "REACHABLE")]
        verdict = AdjudicationService(Path(self.tmp.name)).adjudicate(
            "EVALRUN-0009", BINDING, answers, observations
        ).verdict
        outcome = EvalSpecialReportBuilder(Path(self.tmp.name)).build(self.main, verdict=verdict)
        ref_only = [row for row in outcome.rows if row["metric_id"] in {"M4", "M5", "M6", "M7", "M8", "M9"}]
        self.assertTrue(all("value" not in row for row in ref_only))
        self.assertEqual(len(outcome.rows), 9)
        self.assertEqual(outcome.conclusion, "UNDETERMINED")
        self.assertNotIn("缺 Pipeline 日志", outcome.markdown)


if __name__ == "__main__":
    unittest.main()