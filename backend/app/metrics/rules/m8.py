from __future__ import annotations

from datetime import datetime

from app.domain.enums import MetricId
from app.metrics.collectors.main_flow import CollectedEvidence
from app.metrics.rules.base import RuleExclusion, RuleResult


class M8Rule:
    metric_id = MetricId.M8

    def evaluate(self, evidence: CollectedEvidence, definition, now: datetime) -> RuleResult:
        result = RuleResult(
            metric_id=self.metric_id,
            channel_excluded_count=evidence.channel_excluded_count,
            source_ref="Disposition + GateAttempt",
            details={"unsettled": 0},
        )
        for view in evidence.issues:
            disposition = view.disposition
            result.covered_count += 1
            if disposition is None:
                result.details["unsettled"] += 1
                continue
            level = disposition.get("level")
            if level not in {"L0", "L1"}:
                continue
            passed_gate = any(item.get("outcome") == "PASSED" for item in view.gate_attempts)
            if disposition.get("gate_outcome") != "PASSED" or not passed_gate:
                result.covered_count -= 1
                result.excluded_count += 1
                result.exclusions.append(
                    RuleExclusion(view.issue_id, "EVIDENCE_INCONSISTENT", "处置声称 L0/L1 但缺少 PASSED 门禁证据", self.metric_id)
                )
                continue
            result.numerator += 1
        return result.validate()