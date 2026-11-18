from __future__ import annotations

from datetime import datetime

from app.domain.enums import MetricId
from app.metrics.collectors.main_flow import CollectedEvidence, parse_dt
from app.metrics.rules.base import RuleExclusion, RuleResult


def _aware_text(value) -> bool:
    text = str(value or "")
    return text.endswith("Z") or "+" in text[10:] or text.endswith("+00:00")


class M7Rule:
    metric_id = MetricId.M7

    def evaluate(self, evidence: CollectedEvidence, definition, now: datetime) -> RuleResult:
        result = RuleResult(
            metric_id=self.metric_id,
            channel_excluded_count=evidence.channel_excluded_count,
            source_ref="Alert.observed_at + Disposition.ready_at",
            details={"missing_ready_at": 0},
        )
        for view in evidence.issues:
            disposition = view.disposition
            if disposition is None or disposition.get("level") not in {"L0", "L1"}:
                result.not_applicable_count += 1
                continue
            raw_ready = disposition.get("ready_at")
            ready_at = parse_dt(raw_ready)
            if ready_at is None:
                result.excluded_count += 1
                result.details["missing_ready_at"] += 1
                result.exclusions.append(
                    RuleExclusion(view.issue_id, "EVIDENCE_MISSING", "PR 就绪时刻未采集", self.metric_id)
                )
                continue
            if not _aware_text(raw_ready) or view.first_observed_at is None:
                result.excluded_count += 1
                result.exclusions.append(
                    RuleExclusion(view.issue_id, "EVIDENCE_MISSING", "时间戳缺少时区", self.metric_id)
                )
                continue
            if ready_at < view.first_observed_at:
                result.excluded_count += 1
                result.exclusions.append(
                    RuleExclusion(view.issue_id, "EVIDENCE_INCONSISTENT", "PR 就绪时刻早于告警首次观测", self.metric_id)
                )
                continue
            result.covered_count += 1
            result.numerator += (ready_at - view.first_observed_at).total_seconds() / 60.0
        if result.covered_count == 0 and result.details["missing_ready_at"] > 0:
            result.details["affected_issue_count"] = result.details["missing_ready_at"]

        return result.validate()