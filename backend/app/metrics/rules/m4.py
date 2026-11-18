from __future__ import annotations

from datetime import datetime

from app.domain.enums import MetricId
from app.metrics.collectors.main_flow import CollectedEvidence, IssueEvidenceView
from app.metrics.rules.base import RuleExclusion, RuleResult


class M4Rule:
    metric_id = MetricId.M4

    def evaluate(self, evidence: CollectedEvidence, definition, now: datetime) -> RuleResult:
        result = RuleResult(
            metric_id=self.metric_id,
            channel_excluded_count=evidence.channel_excluded_count,
            source_ref="ReproductionAttempt + Proof + Verdict",
        )
        for view in evidence.issues:
            if view.verdict_conclusion != "REACHABLE":
                result.not_applicable_count += 1
                continue
            if not view.entered_reproduction:
                result.not_applicable_count += 1
                continue
            if self._exclude(view, result):
                continue
            result.covered_count += 1
            if self._is_proven(view):
                result.numerator += 1
                if not view.reproduction_attempts and view.proof is not None:
                    result.details["legacy_count"] = result.details.get("legacy_count", 0) + 1
        return result.validate()

    def _is_proven(self, view: IssueEvidenceView) -> bool:
        latest = view.latest_reproduction_status
        if latest is not None:
            if latest != "PROVEN":
                return False
            proof = view.proof
            return bool(proof and proof.get("pre_patch_result") == "FAIL" and proof.get("proof_id"))
        return bool(view.proof and view.proof.get("pre_patch_result") == "FAIL")

    def _exclude(self, view: IssueEvidenceView, result: RuleResult) -> bool:
        latest = view.latest_reproduction_status
        proof = view.proof
        if latest == "PROVEN" and (proof is None or proof.get("pre_patch_result") != "FAIL"):
            result.excluded_count += 1
            result.exclusions.append(
                RuleExclusion(view.issue_id, "EVIDENCE_INCONSISTENT", "复现结论为 PROVEN 但缺少可复核的必红证明", self.metric_id)
            )
            return True
        if latest == "REPRO_FAILED" and proof is not None:
            result.excluded_count += 1
            result.exclusions.append(
                RuleExclusion(view.issue_id, "EVIDENCE_INCONSISTENT", "最新复现失败但存在旧证明", self.metric_id)
            )
            return True
        if latest is None and proof is None and view.entered_reproduction:
            result.excluded_count += 1
            result.exclusions.append(
                RuleExclusion(view.issue_id, "EVIDENCE_MISSING", "缺少复现尝试记录与证明", self.metric_id)
            )
            return True
        return False