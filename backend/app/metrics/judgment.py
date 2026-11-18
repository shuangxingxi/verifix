from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.domain.enums import MetricId
from app.metrics.collectors.main_flow import CollectedEvidence
from app.metrics.definitions import MetricDefinition
from app.metrics.reason_codes import (
    EXCLUSION_ALLOWED_REASONS,
    JudgmentStage,
    REASON_STAGE,
    UncomputableReason,
    coerce_reason,
)
from app.metrics.rules.base import RuleExclusion, RuleResult


class JudgmentError(ValueError):
    pass


@dataclass
class MetricComputation:
    metric_id: MetricId
    computable: bool
    value: float | None = None
    reason_code: UncomputableReason | None = None
    definition_version: str = "v2"
    source_ref: str = ""
    numerator: float = 0.0
    denominator: int = 0
    covered_count: int = 0
    excluded_count: int = 0
    channel_excluded_count: int = 0
    not_applicable_count: int = 0
    exclusions: list[RuleExclusion] = field(default_factory=list)
    trial: bool = False
    missing: str = ""
    details: dict = field(default_factory=dict)
    stage: JudgmentStage | None = None
    unverified: bool = False
    unverified_reason: str | None = None

    def __post_init__(self) -> None:
        if self.computable and self.value is None:
            raise JudgmentError("computable metric requires a finite value")
        if self.computable and self.reason_code is not None:
            raise JudgmentError("computable metric must not carry a reason code")
        if self.computable and self.trial:
            raise JudgmentError("trial metric must not be computable")
        if not self.computable:
            if self.value is not None:
                raise JudgmentError("uncomputable metric must not carry a value")
            if self.reason_code is None:
                raise JudgmentError("uncomputable metric requires a reason code")
            coerce_reason(self.reason_code)
        if self.reason_code is not None:
            self.stage = REASON_STAGE[coerce_reason(self.reason_code)]
        if self.trial and self.reason_code is not UncomputableReason.WINDOW_NOT_CLOSED:
            raise JudgmentError("trial metric must use WINDOW_NOT_CLOSED")
        if self.covered_count + self.excluded_count != self.denominator:
            raise JudgmentError("covered_count + excluded_count must equal denominator")


class ComputabilityPipeline:
    def __init__(self, exclusion_ratio_limit: float = 0.10) -> None:
        self.exclusion_ratio_limit = exclusion_ratio_limit

    def evaluate(
        self,
        metric_id: MetricId,
        definition: MetricDefinition | None,
        rule_result: RuleResult,
        evidence: CollectedEvidence,
        now: datetime,
    ) -> MetricComputation:
        merged = self._merge_pre_exclusions(rule_result, evidence)
        denominator = merged.covered_count + merged.excluded_count

        if definition is None:
            return self._fail(metric_id, merged, UncomputableReason.DEFINITION_UNREGISTERED, "指标定义未登记", denominator)

        if merged.details.get("unverified"):
            return MetricComputation(
                metric_id=metric_id,
                computable=False,
                value=None,
                reason_code=UncomputableReason.EVIDENCE_MISSING,
                definition_version=definition.definition_version,
                source_ref=merged.source_ref,
                numerator=0.0,
                denominator=0,
                covered_count=0,
                excluded_count=0,
                channel_excluded_count=merged.channel_excluded_count,
                not_applicable_count=merged.not_applicable_count,
                details=dict(merged.details),
                unverified=True,
                unverified_reason=str(merged.details.get("unverified_reason") or "缺少真实连续运行证据"),
            )

        if not merged.evidence_present:
            return self._fail(
                metric_id,
                merged,
                UncomputableReason.SOURCE_MISSING,
                merged.details.get("missing", merged.source_ref),
                denominator,
            )

        if denominator == 0:
            return self._fail(
                metric_id,
                merged,
                UncomputableReason.DENOMINATOR_EMPTY,
                merged.details.get("missing", f"{metric_id.value} 分母为空"),
                denominator,
            )

        if metric_id is MetricId.M5 and merged.all_first_attempt_missing:
            return self._fail(
                metric_id,
                merged,
                UncomputableReason.FIRST_ATTEMPT_EVIDENCE_MISSING,
                "分母内全部 Issue 无法识别首次补丁尝试",
                denominator,
            )

        if merged.exclusion_ratio > self.exclusion_ratio_limit:
            reason = self._coverage_reason(merged)
            return self._fail(
                metric_id,
                merged,
                reason,
                "剔除比例超过阈值 " + f"{self.exclusion_ratio_limit:.2%}",
                denominator,
            )

        value = merged.value()
        if value is None or not math.isfinite(value):
            return self._fail(metric_id, merged, UncomputableReason.EVIDENCE_INCONSISTENT, "计算结果非有限值", denominator)

        window_end = evidence.window_end
        current = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
        if current < window_end:
            return self._fail(
                metric_id,
                merged,
                UncomputableReason.WINDOW_NOT_CLOSED,
                f"窗口 {evidence.window} 尚未闭合",
                denominator,
                trial=True,
            )

        return MetricComputation(
            metric_id=metric_id,
            computable=True,
            value=value,
            definition_version=definition.definition_version,
            source_ref=merged.source_ref,
            numerator=merged.numerator,
            denominator=denominator,
            covered_count=merged.covered_count,
            excluded_count=merged.excluded_count,
            channel_excluded_count=merged.channel_excluded_count,
            not_applicable_count=merged.not_applicable_count,
            exclusions=list(merged.exclusions),
            details=dict(merged.details),
        )

    def _merge_pre_exclusions(self, rule_result: RuleResult, evidence: CollectedEvidence) -> RuleResult:
        if not evidence.pre_exclusions:
            return rule_result
        merged = RuleResult(
            metric_id=rule_result.metric_id,
            numerator=rule_result.numerator,
            covered_count=rule_result.covered_count,
            excluded_count=rule_result.excluded_count,
            not_applicable_count=rule_result.not_applicable_count,
            channel_excluded_count=rule_result.channel_excluded_count,
            exclusions=list(rule_result.exclusions),
            source_ref=rule_result.source_ref,
            evidence_present=rule_result.evidence_present,
            details=dict(rule_result.details),
        )
        seen = {item.issue_id for item in merged.exclusions}
        for item in evidence.pre_exclusions:
            if item.get("issue_id") in seen:
                continue
            merged.exclusions.append(
                RuleExclusion(
                    issue_id=item.get("issue_id", ""),
                    reason_code=item.get("reason_code", "EVIDENCE_MISSING"),
                    detail=item.get("detail", ""),
                    metric_id=rule_result.metric_id,
                )
            )
            merged.excluded_count += 1
        return merged

    def _coverage_reason(self, result: RuleResult) -> UncomputableReason:
        reasons = {item.reason_code for item in result.exclusions}
        if result.covered_count == 0 and reasons and reasons <= {UncomputableReason.EVIDENCE_INCONSISTENT}:
            return UncomputableReason.EVIDENCE_INCONSISTENT
        return UncomputableReason.COVERAGE_INSUFFICIENT

    def _fail(
        self,
        metric_id: MetricId,
        result: RuleResult,
        reason: UncomputableReason,
        detail: str,
        denominator: int,
        trial: bool = False,
    ) -> MetricComputation:
        if reason not in {UncomputableReason.EVIDENCE_MISSING, UncomputableReason.EVIDENCE_INCONSISTENT}:
            allowed = {item.reason_code for item in result.exclusions}
            if not allowed <= EXCLUSION_ALLOWED_REASONS:
                raise JudgmentError("exclusion entries must use evidence reason codes only")
        return MetricComputation(
            metric_id=metric_id,
            computable=False,
            value=None,
            reason_code=reason,
            source_ref=result.source_ref,
            numerator=result.numerator,
            denominator=denominator,
            covered_count=result.covered_count,
            excluded_count=result.excluded_count,
            channel_excluded_count=result.channel_excluded_count,
            not_applicable_count=result.not_applicable_count,
            exclusions=list(result.exclusions),
            trial=trial,
            missing=detail,
            details=dict(result.details),
        )


def evaluation_stage(reason: UncomputableReason | None) -> JudgmentStage | None:
    return None if reason is None else REASON_STAGE[coerce_reason(reason)]