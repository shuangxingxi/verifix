from __future__ import annotations

from datetime import datetime

from app.domain.enums import MetricId
from app.metrics.collectors.main_flow import CollectedEvidence
from app.metrics.rules.base import RuleExclusion, RuleResult


class M6Rule:
    metric_id = MetricId.M6

    def evaluate(self, evidence: CollectedEvidence, definition, now: datetime) -> RuleResult:
        tolerance = abs(float(getattr(definition, "coverage_delta_tolerance_pp", 0.5)))
        result = RuleResult(
            metric_id=self.metric_id,
            channel_excluded_count=evidence.channel_excluded_count,
            source_ref="GateResult + GateAttempt",
        )
        source_present = False
        for view in evidence.issues:
            if view.latest_patch is None:
                result.not_applicable_count += 1
                continue
            if view.gate_attempts or view.gate_results:
                source_present = True
            for gate in view.gate_attempts:
                outcome = gate.get("outcome")
                if outcome not in {"PASSED", "FAILED"} or gate.get("evidence_missing"):
                    result.not_applicable_count += 1
                    continue
                result.covered_count += 1
                if self._broke(gate, tolerance):
                    result.numerator += 1
        if not source_present:
            return RuleResult(
                metric_id=self.metric_id,
                channel_excluded_count=evidence.channel_excluded_count,
                source_ref="GateResult + GateAttempt",
                evidence_present=False,
                details={"missing": "GateAttempt/GateResult 缺失"},
            ).validate()
        return result.validate()

    def _broke(self, gate: dict, tolerance: float) -> bool:
        if not gate.get("regression_zero_fail", False):
            return True
        if int(gate.get("rescan_new_alerts", 0)) > 0:
            return True
        return float(gate.get("coverage_delta_pp", 0.0)) < -tolerance