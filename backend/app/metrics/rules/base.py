from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from app.domain.enums import MetricId
from app.metrics.collectors.main_flow import CollectedEvidence
from app.metrics.definitions import MetricDefinition
from app.metrics.reason_codes import EXCLUSION_ALLOWED_REASONS, UncomputableReason, coerce_reason


class RuleCountError(ValueError):
    pass


@dataclass(frozen=True)
class RuleExclusion:
    issue_id: str
    reason_code: UncomputableReason | str
    detail: str = ""
    metric_id: MetricId | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason_code", coerce_reason(self.reason_code))


@dataclass
class RuleResult:
    metric_id: MetricId
    numerator: float = 0.0
    covered_count: int = 0
    excluded_count: int = 0
    not_applicable_count: int = 0
    channel_excluded_count: int = 0
    exclusions: list[RuleExclusion] = field(default_factory=list)
    source_ref: str = ""
    evidence_present: bool = True
    details: dict = field(default_factory=dict)

    @property
    def denominator(self) -> int:
        return self.covered_count + self.excluded_count

    @property
    def exclusion_ratio(self) -> float:
        return (self.excluded_count / self.denominator) if self.denominator else 0.0

    @property
    def all_first_attempt_missing(self) -> bool:
        return bool(self.details.get("first_attempt_missing_all", False))

    def value(self) -> float | None:
        if self.covered_count <= 0:
            return None
        return self.numerator / self.covered_count

    def validate(self) -> "RuleResult":
        if self.covered_count < 0 or self.excluded_count < 0 or self.not_applicable_count < 0:
            raise RuleCountError("counts must not be negative")
        if self.channel_excluded_count < 0:
            raise RuleCountError("channel_excluded_count must not be negative")
        if len(self.exclusions) != self.excluded_count:
            raise RuleCountError("exclusions length must equal excluded_count")
        for item in self.exclusions:
            reason = coerce_reason(item.reason_code)
            if reason not in EXCLUSION_ALLOWED_REASONS:
                raise RuleCountError(f"exclusion reason not allowed: {reason.value}")
        if not self.evidence_present and self.covered_count > 0:
            raise RuleCountError("evidence_present=false requires covered_count=0")
        return self


class MetricRule(Protocol):
    metric_id: MetricId

    def evaluate(
        self,
        evidence: CollectedEvidence,
        definition: MetricDefinition,
        now: datetime,
    ) -> RuleResult: ...