from __future__ import annotations

from datetime import datetime

from app.domain.enums import MetricId
from app.metrics.collectors.main_flow import CollectedEvidence, IssueEvidenceView
from app.metrics.rules.base import RuleExclusion, RuleResult


class M5Rule:
    metric_id = MetricId.M5

    def evaluate(self, evidence: CollectedEvidence, definition, now: datetime) -> RuleResult:
        tolerance = float(getattr(definition, "coverage_delta_tolerance_pp", 0.5))
        result = RuleResult(
            metric_id=self.metric_id,
            channel_excluded_count=evidence.channel_excluded_count,
            source_ref="PatchAttempt(first) + GateAttempt + DispositionHistory",
            details={"first_attempt_missing": 0},
        )
        first_missing = 0
        for view in evidence.issues:
            if view.latest_patch is None:
                result.not_applicable_count += 1
                continue
            first = self._first_attempt(view)
            if first is None:
                result.excluded_count += 1
                first_missing += 1
                result.exclusions.append(
                    RuleExclusion(view.issue_id, "EVIDENCE_MISSING", "缺少可唯一识别的首次补丁尝试", self.metric_id)
                )
                continue
            gate = self._first_gate(view, first)
            if gate is None:
                result.excluded_count += 1
                result.exclusions.append(
                    RuleExclusion(view.issue_id, "EVIDENCE_INCONSISTENT", "首次补丁尝试缺少可关联的门禁结论", self.metric_id)
                )
                continue
            history = self._history_for(view, first)
            if history is None:
                result.excluded_count += 1
                result.exclusions.append(
                    RuleExclusion(view.issue_id, "EVIDENCE_INCONSISTENT", "首次补丁尝试缺少可关联的处置结论", self.metric_id)
                )
                continue
            result.covered_count += 1
            if self._passed(gate, history, tolerance):
                result.numerator += 1
        result.details["first_attempt_missing"] = first_missing
        if result.covered_count == 0 and first_missing > 0:
            result.details["first_attempt_missing_all"] = True
        return result.validate()

    def _first_attempt(self, view: IssueEvidenceView) -> dict | None:
        attempts = view.patch_attempts
        if not attempts:
            return None
        indexes = sorted(int(item.get("attempt_index", 0)) for item in attempts)
        if indexes[0] != 1 or indexes != list(range(1, len(indexes) + 1)):
            return None
        return next(item for item in attempts if int(item.get("attempt_index", 0)) == 1)

    def _first_gate(self, view: IssueEvidenceView, first: dict) -> dict | None:
        patch_id = first.get("patch_id")
        candidates = [item for item in view.gate_attempts if item.get("patch_id") == patch_id]
        if not candidates:
            return None
        candidates.sort(key=lambda item: str(item.get("observed_at", "")))
        return candidates[0]

    def _history_for(self, view: IssueEvidenceView, first: dict) -> dict | None:
        attempt_id = first.get("attempt_id")
        for entry in view.disposition_history:
            if entry.get("attempt_id") == attempt_id:
                return entry
        return None

    def _passed(self, gate: dict, history: dict, tolerance: float) -> bool:
        if history.get("level") not in {"L0", "L1"}:
            return False
        if history.get("gate_outcome") != "PASSED":
            return False
        if gate.get("outcome") != "PASSED":
            return False
        if not gate.get("red_green_paired", False):
            return False
        if not gate.get("regression_zero_fail", False):
            return False
        if float(gate.get("coverage_delta_pp", 0.0)) < -abs(tolerance):
            return False
        if int(gate.get("rescan_new_alerts", 0)) > 0:
            return False
        return True