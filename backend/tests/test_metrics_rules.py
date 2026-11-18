from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.enums import MetricChannel, MetricId
from app.metrics.collectors.main_flow import CollectedEvidence, IssueEvidenceView
from app.metrics.definitions import DefinitionRegistry
from app.metrics.rules import M1Rule, M2Rule, M3Rule, M4Rule, M5Rule, M6Rule, M7Rule, M8Rule, M9Rule

BASE = datetime(2026, 12, 5, 12, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 12, 5, 13, 0, tzinfo=timezone.utc)
REGISTRY = DefinitionRegistry()


def definition(metric_id: MetricId):
    return REGISTRY.effective(metric_id, NOW)


def patch_record(issue_id: str = "ISS-1") -> dict:
    return {"patch_id": f"PA-{issue_id}", "issue_id": issue_id, "branch": f"verifix/{issue_id}"}


def attempt_record(issue_id: str = "ISS-1", index: int = 1) -> dict:
    return {"attempt_id": f"PA-{issue_id}#{index}", "issue_id": issue_id, "attempt_index": index, "patch_id": f"PA-{issue_id}"}


def gate_record(
    issue_id: str = "ISS-1",
    *,
    outcome: str = "PASSED",
    regression_zero_fail: bool = True,
    rescan_new_alerts: int = 0,
    coverage_delta_pp: float = 0.0,
    evidence_missing: bool = False,
    offset_seconds: int = 0,
) -> dict:
    return {
        "patch_id": f"PA-{issue_id}",
        "outcome": outcome,
        "red_green_paired": outcome == "PASSED",
        "regression_zero_fail": regression_zero_fail,
        "rescan_new_alerts": rescan_new_alerts,
        "coverage_delta_pp": coverage_delta_pp,
        "evidence_missing": evidence_missing,
        "observed_at": (BASE + timedelta(seconds=offset_seconds)).isoformat(),
    }


def disposition_record(issue_id: str = "ISS-1", *, level: str = "L1", ready_at=BASE + timedelta(minutes=30), gate_outcome: str = "PASSED") -> dict:
    return {
        "issue_id": issue_id,
        "level": level,
        "gate_outcome": gate_outcome,
        "ready_at": ready_at.isoformat() if ready_at is not None else None,
        "decided_at": (BASE + timedelta(minutes=29)).isoformat(),
    }


def make_view(
    issue_id: str = "ISS-1",
    *,
    status: str = "DISPOSED_L1",
    verdict: str | None = "REACHABLE",
    attempts: list | None = None,
    proof: dict | None = None,
    patch: dict | None = None,
    patch_attempts: list | None = None,
    gate_attempts: list | None = None,
    disposition: dict | None = None,
    history: list | None = None,
    first_observed=BASE,
) -> IssueEvidenceView:
    return IssueEvidenceView(
        issue_id=issue_id,
        channel=MetricChannel.MAIN,
        channel_basis="explicit",
        channel_legacy=False,
        first_observed_at=first_observed,
        fallback_occurred_at=False,
        tz_ok=True,
        status=status,
        in_scope=True,
        verdict={"issue_id": issue_id, "conclusion": verdict} if verdict else None,
        verdict_conclusion=verdict,
        reproduction_attempts=list(attempts or []),
        proof=proof,
        patch_attempts=list(patch_attempts or []),
        latest_patch=patch,
        gate_attempts=list(gate_attempts or []),
        disposition=disposition,
        disposition_history=list(history or []),
    )


def make_evidence(*views: IssueEvidenceView, sample=None, eval_conclusion=None, channel_excluded=0) -> CollectedEvidence:
    return CollectedEvidence(
        window="2026-12",
        tier=__import__("app.domain.enums", fromlist=["StageTier"]).StageTier.PRELIMINARY,
        window_start=datetime(2026, 12, 1, tzinfo=timezone.utc),
        window_end=datetime(2027, 1, 1, tzinfo=timezone.utc),
        issues=list(views),
        channel_excluded_count=channel_excluded,
        self_run_sample=sample,
        eval_conclusion=eval_conclusion,
    )


def full_success(issue_id: str = "ISS-1", **overrides) -> IssueEvidenceView:
    payload = dict(
        status="DISPOSED_L1",
        verdict="REACHABLE",
        attempts=[{"attempt_id": f"RA-{issue_id}#1", "issue_id": issue_id, "attempt_index": 1, "status": "PROVEN", "proof_id": f"P-{issue_id}"}],
        proof={"proof_id": f"P-{issue_id}", "pre_patch_result": "FAIL"},
        patch=patch_record(issue_id),
        patch_attempts=[attempt_record(issue_id, 1)],
        gate_attempts=[gate_record(issue_id)],
        disposition=disposition_record(issue_id),
        history=[{"attempt_id": f"PA-{issue_id}#1", "level": "L1", "gate_outcome": "PASSED", "ready_at": (BASE + timedelta(minutes=30)).isoformat()}],
    )
    payload.update(overrides)
    return make_view(issue_id, **payload)


class M4Test(unittest.TestCase):
    def test_p01_success_is_one(self) -> None:
        result = M4Rule().evaluate(make_evidence(full_success()), definition(MetricId.M4), NOW)
        self.assertEqual(result.covered_count, 1)
        self.assertEqual(result.numerator, 1)
        self.assertEqual(result.value(), 1.0)

    def test_p03_repro_failed_counts_in_denominator(self) -> None:
        view = make_view(
            status="REPRO_FAILED",
            attempts=[{"attempt_id": "RA-ISS-1#1", "issue_id": "ISS-1", "attempt_index": 1, "status": "REPRO_FAILED"}],
        )
        result = M4Rule().evaluate(make_evidence(view), definition(MetricId.M4), NOW)
        self.assertEqual(result.covered_count, 1)
        self.assertEqual(result.numerator, 0)
        self.assertEqual(result.value(), 0.0)

    def test_p05_takes_latest_attempt(self) -> None:
        view = make_view(
            attempts=[
                {"attempt_id": "RA-ISS-1#1", "issue_id": "ISS-1", "attempt_index": 1, "status": "REPRO_FAILED"},
                {"attempt_id": "RA-ISS-1#2", "issue_id": "ISS-1", "attempt_index": 2, "status": "PROVEN", "proof_id": "P-ISS-1"},
            ],
            proof={"proof_id": "P-ISS-1", "pre_patch_result": "FAIL"},
        )
        result = M4Rule().evaluate(make_evidence(view), definition(MetricId.M4), NOW)
        self.assertEqual(result.numerator, 1)

    def test_n01_unreachable_is_not_applicable(self) -> None:
        view = make_view(verdict="UNREACHABLE", status="ARCHIVED")
        result = M4Rule().evaluate(make_evidence(view), definition(MetricId.M4), NOW)
        self.assertEqual(result.covered_count, 0)
        self.assertEqual(result.not_applicable_count, 1)

    def test_repro_failed_with_stale_proof_is_inconsistent(self) -> None:
        view = make_view(
            status="REPRO_FAILED",
            attempts=[{"attempt_id": "RA-ISS-1#1", "issue_id": "ISS-1", "attempt_index": 1, "status": "REPRO_FAILED"}],
            proof={"proof_id": "P-ISS-1", "pre_patch_result": "FAIL"},
        )
        result = M4Rule().evaluate(make_evidence(view), definition(MetricId.M4), NOW)
        self.assertEqual(result.excluded_count, 1)
        self.assertEqual(result.exclusions[0].reason_code.value, "EVIDENCE_INCONSISTENT")

    def test_legacy_proof_without_attempt_counts(self) -> None:
        view = make_view(status="PROVEN", attempts=[], proof={"proof_id": "P-ISS-1", "pre_patch_result": "FAIL"})
        result = M4Rule().evaluate(make_evidence(view), definition(MetricId.M4), NOW)
        self.assertEqual(result.numerator, 1)
        self.assertEqual(result.details.get("legacy_count"), 1)


class M5Test(unittest.TestCase):
    def test_p01_first_attempt_passes(self) -> None:
        result = M5Rule().evaluate(make_evidence(full_success()), definition(MetricId.M5), NOW)
        self.assertEqual(result.covered_count, 1)
        self.assertEqual(result.numerator, 1)
        self.assertEqual(result.value(), 1.0)

    def test_n06_first_failed_second_passed_not_counted(self) -> None:
        view = make_view(
            patch=patch_record(),
            patch_attempts=[attempt_record(index=1), attempt_record(index=2)],
            gate_attempts=[gate_record(outcome="FAILED"), gate_record(outcome="PASSED", offset_seconds=10)],
            disposition=disposition_record(),
            history=[{"attempt_id": "PA-ISS-1#1", "level": "L1", "gate_outcome": "PASSED"}],
        )
        result = M5Rule().evaluate(make_evidence(view), definition(MetricId.M5), NOW)
        self.assertEqual(result.covered_count, 1)
        self.assertEqual(result.numerator, 0)

    def test_n07_no_attempt_history_excluded(self) -> None:
        view = make_view(patch=patch_record(), patch_attempts=[])
        result = M5Rule().evaluate(make_evidence(view), definition(MetricId.M5), NOW)
        self.assertEqual(result.excluded_count, 1)
        self.assertTrue(result.all_first_attempt_missing)

    def test_n08_index_gap_excluded(self) -> None:
        view = make_view(patch=patch_record(), patch_attempts=[attempt_record(index=2)])
        result = M5Rule().evaluate(make_evidence(view), definition(MetricId.M5), NOW)
        self.assertEqual(result.excluded_count, 1)

    def test_n09_claimed_l1_without_passed_gate_excluded(self) -> None:
        view = make_view(
            patch=patch_record(),
            patch_attempts=[attempt_record(index=1)],
            gate_attempts=[gate_record(outcome="FAILED")],
            disposition=disposition_record(level="L1", gate_outcome="PASSED"),
            history=[{"attempt_id": "PA-ISS-1#1", "level": "L1", "gate_outcome": "PASSED"}],
        )
        result = M5Rule().evaluate(make_evidence(view), definition(MetricId.M5), NOW)
        self.assertEqual(result.numerator, 0)

    def test_no_patch_is_not_applicable(self) -> None:
        result = M5Rule().evaluate(make_evidence(make_view()), definition(MetricId.M5), NOW)
        self.assertEqual(result.not_applicable_count, 1)


class M6Test(unittest.TestCase):
    def _evidence(self, coverage: float) -> CollectedEvidence:
        return make_evidence(
            make_view(patch=patch_record(), gate_attempts=[gate_record(coverage_delta_pp=coverage)])
        )

    def test_p06_minus_06_pp_breaks(self) -> None:
        result = M6Rule().evaluate(self._evidence(-0.6), definition(MetricId.M6), NOW)
        self.assertEqual(result.covered_count, 1)
        self.assertEqual(result.numerator, 1)

    def test_p07_minus_04_pp_passes(self) -> None:
        result = M6Rule().evaluate(self._evidence(-0.4), definition(MetricId.M6), NOW)
        self.assertEqual(result.numerator, 0)

    def test_n04_no_gate_marks_source_missing(self) -> None:
        result = M6Rule().evaluate(make_evidence(make_view(patch=patch_record())), definition(MetricId.M6), NOW)
        self.assertFalse(result.evidence_present)
        self.assertEqual(result.details["missing"], "GateAttempt/GateResult 缺失")

    def test_n05_all_not_executed_is_not_applicable(self) -> None:
        view = make_view(patch=patch_record(), gate_attempts=[gate_record(outcome="NOT_EXECUTED")])
        result = M6Rule().evaluate(make_evidence(view), definition(MetricId.M6), NOW)
        self.assertTrue(result.evidence_present)
        self.assertEqual(result.covered_count, 0)
        self.assertEqual(result.not_applicable_count, 1)


class M7Test(unittest.TestCase):
    def test_p01_positive_duration(self) -> None:
        result = M7Rule().evaluate(make_evidence(full_success()), definition(MetricId.M7), NOW)
        self.assertEqual(result.covered_count, 1)
        self.assertAlmostEqual(result.value(), 30.0)

    def test_n10_all_missing_ready_at(self) -> None:
        view = make_view(disposition=disposition_record(ready_at=None))
        result = M7Rule().evaluate(make_evidence(view), definition(MetricId.M7), NOW)
        self.assertEqual(result.covered_count, 0)
        self.assertEqual(result.excluded_count, 1)
        self.assertEqual(result.details["affected_issue_count"], 1)
        self.assertIsNone(result.value())

    def test_n11_negative_duration_excluded(self) -> None:
        view = make_view(disposition=disposition_record(ready_at=BASE - timedelta(hours=1)))
        result = M7Rule().evaluate(make_evidence(view), definition(MetricId.M7), NOW)
        self.assertEqual(result.excluded_count, 1)
        self.assertEqual(result.exclusions[0].reason_code.value, "EVIDENCE_INCONSISTENT")

    def test_n12_naive_ready_at_excluded(self) -> None:
        view = make_view(disposition=disposition_record(ready_at=None))
        view.disposition = dict(view.disposition)
        view.disposition["ready_at"] = "2026-12-05T13:00:00"
        result = M7Rule().evaluate(make_evidence(view), definition(MetricId.M7), NOW)
        self.assertEqual(result.excluded_count, 1)
        self.assertEqual(result.exclusions[0].reason_code.value, "EVIDENCE_MISSING")

    def test_l2_is_not_applicable(self) -> None:
        result = M7Rule().evaluate(make_evidence(make_view(disposition=disposition_record(level="L2"))), definition(MetricId.M7), NOW)
        self.assertEqual(result.not_applicable_count, 1)

    def test_no_decided_at_fallback(self) -> None:
        result = M7Rule().evaluate(make_evidence(make_view(disposition=disposition_record(ready_at=None))), definition(MetricId.M7), NOW)
        self.assertNotIn("decided_at", result.details)


class M8Test(unittest.TestCase):
    def test_p01_p02_rate(self) -> None:
        result = M8Rule().evaluate(make_evidence(full_success()), definition(MetricId.M8), NOW)
        self.assertEqual(result.covered_count, 1)
        self.assertEqual(result.numerator, 1)

    def test_unsettled_issue_counts_in_denominator(self) -> None:
        result = M8Rule().evaluate(make_evidence(full_success(), make_view("ISS-2", status="RECEIVED")), definition(MetricId.M8), NOW)
        self.assertEqual(result.covered_count, 2)
        self.assertEqual(result.numerator, 1)
        self.assertEqual(result.details["unsettled"], 1)

    def test_n09_claimed_l1_without_passed_gate_excluded(self) -> None:
        view = make_view(
            patch=patch_record(),
            gate_attempts=[gate_record(outcome="FAILED")],
            disposition=disposition_record(),
        )
        result = M8Rule().evaluate(make_evidence(view), definition(MetricId.M8), NOW)
        self.assertEqual(result.excluded_count, 1)
        self.assertEqual(result.exclusions[0].reason_code.value, "EVIDENCE_INCONSISTENT")


class M9Test(unittest.TestCase):
    def test_p14_fresh_fixture_sample_is_unverified(self) -> None:
        sample = {"sampled_at": NOW - timedelta(seconds=10), "continuous_seconds": 7200.0, "interruptions": 0, "heartbeat_ok": True}
        result = M9Rule().evaluate(make_evidence(sample=sample), definition(MetricId.M9), NOW)
        self.assertEqual(result.covered_count, 0)
        self.assertTrue(result.details["unverified"])
        self.assertEqual(result.details["trust_reason"], "FIXTURE_ORIGIN")

    def test_p15_interruption_is_unverified(self) -> None:
        sample = {"sampled_at": NOW - timedelta(seconds=10), "continuous_seconds": 0.0, "interruptions": 2, "heartbeat_ok": True}
        result = M9Rule().evaluate(make_evidence(sample=sample), definition(MetricId.M9), NOW)
        self.assertEqual(result.covered_count, 0)
        self.assertEqual(result.details["trust_reason"], "FIXTURE_ORIGIN")

    def test_n28_no_sample_is_unverified(self) -> None:
        result = M9Rule().evaluate(make_evidence(), definition(MetricId.M9), NOW)
        self.assertTrue(result.evidence_present)
        self.assertEqual(result.details["trust_reason"], "MISSING_RUNTIME_EVIDENCE")

    def test_n29_stale_sample_is_unverified(self) -> None:
        sample = {"sampled_at": NOW - timedelta(seconds=200), "continuous_seconds": 7200.0, "interruptions": 0, "heartbeat_ok": True}
        result = M9Rule().evaluate(make_evidence(sample=sample), definition(MetricId.M9), NOW)
        self.assertEqual(result.covered_count, 0)
        self.assertTrue(result.details["unverified"])
        self.assertEqual(result.details["trust_reason"], "FIXTURE_ORIGIN")


class EvalMergeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conclusion = {
            "eval_run_id": "EVALRUN-27714aeffb",
            "set_digest": "a" * 64,
            "digest_match": True,
            "category_stats": {},
            "m1": {"detected": 8, "total": 10},
            "m3": {"agrees": 9, "labelled": 10},
            "m2": None,
            "results": [],
        }

    def test_m1_m3_computable(self) -> None:
        m1 = M1Rule().evaluate(make_evidence(eval_conclusion=self.conclusion), definition(MetricId.M1), NOW)
        m3 = M3Rule().evaluate(make_evidence(eval_conclusion=self.conclusion), definition(MetricId.M3), NOW)
        self.assertAlmostEqual(m1.value(), 0.8)
        self.assertAlmostEqual(m3.value(), 0.9)
        self.assertEqual(m1.details["eval_run_id"], "EVALRUN-27714aeffb")

    def test_m2_source_missing_without_explicit_field(self) -> None:
        m2 = M2Rule().evaluate(make_evidence(eval_conclusion=self.conclusion), definition(MetricId.M2), NOW)
        self.assertFalse(m2.evidence_present)
        self.assertIn("未提供显式漏洞检出字段", m2.details["missing"])

    def test_n25_digest_mismatch_is_inconsistent(self) -> None:
        bad = dict(self.conclusion)
        bad["digest_match"] = False
        result = M1Rule().evaluate(make_evidence(eval_conclusion=bad), definition(MetricId.M1), NOW)
        self.assertEqual(result.excluded_count, 1)
        self.assertEqual(result.exclusions[0].reason_code.value, "EVIDENCE_INCONSISTENT")

    def test_missing_eval_conclusion(self) -> None:
        result = M1Rule().evaluate(make_evidence(), definition(MetricId.M1), NOW)
        self.assertFalse(result.evidence_present)


class RealEvalRunTest(unittest.TestCase):
    def test_existing_eval_run_is_used(self) -> None:
        from app.metrics.collectors.eval_channel import EvalConclusionReader, read_expected_digest

        root = Path(__file__).resolve().parents[2]
        expected = read_expected_digest(root / "eval" / "eval_set.sha256")
        reader = EvalConclusionReader(root / "eval" / "runs", expected)
        conclusion = reader.latest_completed()
        self.assertIsNotNone(conclusion)
        self.assertEqual(conclusion["eval_run_id"], "EVALRUN-27714aeffb")
        self.assertTrue(conclusion["digest_match"])
        evidence = make_evidence(eval_conclusion=conclusion)
        m1 = M1Rule().evaluate(evidence, definition(MetricId.M1), NOW)
        m3 = M3Rule().evaluate(evidence, definition(MetricId.M3), NOW)
        m2 = M2Rule().evaluate(evidence, definition(MetricId.M2), NOW)
        self.assertEqual(m1.covered_count, 30)
        self.assertGreater(m1.numerator, 0)
        self.assertGreater(m3.covered_count, 0)
        self.assertGreater(m3.numerator, 0)
        self.assertFalse(m2.evidence_present)

    def test_digest_mismatch_detected_against_real_run(self) -> None:
        from app.metrics.collectors.eval_channel import EvalConclusionReader

        root = Path(__file__).resolve().parents[2]
        reader = EvalConclusionReader(root / "eval" / "runs", "0" * 64)
        conclusion = reader.latest_completed()
        self.assertFalse(conclusion["digest_match"])


class RulePurityTest(unittest.TestCase):
    def test_deterministic_and_pure(self) -> None:
        evidence = make_evidence(full_success())
        first = M4Rule().evaluate(evidence, definition(MetricId.M4), NOW)
        second = M4Rule().evaluate(evidence, definition(MetricId.M4), NOW)
        self.assertEqual(first.__dict__, second.__dict__)

    def test_illegal_counts_rejected(self) -> None:
        from app.metrics.rules.base import RuleCountError, RuleExclusion, RuleResult

        result = RuleResult(metric_id=MetricId.M4, covered_count=1)
        result.excluded_count = 1
        result.exclusions = []
        with self.assertRaises(RuleCountError):
            result.validate()
        bad = RuleResult(metric_id=MetricId.M4, covered_count=0, excluded_count=1, exclusions=[RuleExclusion("x", "SOURCE_MISSING")])
        with self.assertRaises(RuleCountError):
            bad.validate()


if __name__ == "__main__":
    unittest.main()