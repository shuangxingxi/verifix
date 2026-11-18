from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.domain.enums import MetricId
from app.metrics.collectors.main_flow import CollectedEvidence
from app.metrics.rules.base import RuleResult

MIN_CONTINUOUS_SECONDS = 86400
MIN_SAMPLE_GAP_SECONDS = 60
MAX_SAMPLE_GAP_SECONDS = 120
MAX_SAMPLE_AGE_SECONDS = 150
MAX_TRACKER_SKEW_SECONDS = 60

MISSING_RUNTIME_EVIDENCE = "MISSING_RUNTIME_EVIDENCE"
FIXTURE_ORIGIN = "FIXTURE_ORIGIN"
MISSING_TRACKER_START = "MISSING_TRACKER_START"
INTERRUPTED = "INTERRUPTED"
MANUAL_INTERVENTION = "MANUAL_INTERVENTION"
INSUFFICIENT_DURATION = "INSUFFICIENT_DURATION"
SAMPLE_GAP = "SAMPLE_GAP"
SAMPLE_STALE = "SAMPLE_STALE"
DURATION_SKEW = "DURATION_SKEW"

REASON_LABELS = {
    MISSING_RUNTIME_EVIDENCE: "缺少真实连续运行证据：未发现运行采样记录",
    FIXTURE_ORIGIN: "缺少真实连续运行证据：采样来源为夹具",
    MISSING_TRACKER_START: "缺少真实连续运行证据：采样未记录追踪起点",
    INTERRUPTED: "缺少真实连续运行证据：运行期间存在中断",
    MANUAL_INTERVENTION: "缺少真实连续运行证据：运行期间存在人工干预",
    INSUFFICIENT_DURATION: "缺少真实连续运行证据：连续时长不足 24 小时",
    SAMPLE_GAP: "缺少真实连续运行证据：采样间隔超过 120 秒",
    SAMPLE_STALE: "缺少真实连续运行证据：最近采样已超过 150 秒",
    DURATION_SKEW: "缺少真实连续运行证据：连续时长与追踪起点偏差超过 60 秒",
}


@dataclass(frozen=True)
class TrustVerdict:
    trusted: bool
    reason: str
    evidence: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return "" if self.trusted else REASON_LABELS.get(self.reason, "缺少真实连续运行证据")


@dataclass(frozen=True)
class M9Thresholds:
    min_continuous_seconds: int = MIN_CONTINUOUS_SECONDS
    min_sample_gap_seconds: int = MIN_SAMPLE_GAP_SECONDS
    max_sample_gap_seconds: int = MAX_SAMPLE_GAP_SECONDS
    max_sample_age_seconds: int = MAX_SAMPLE_AGE_SECONDS
    max_tracker_skew_seconds: int = MAX_TRACKER_SKEW_SECONDS

    @classmethod
    def from_config(cls, config) -> "M9Thresholds":
        metrics = getattr(config, "metrics", config)
        return cls(
            min_continuous_seconds=int(getattr(metrics, "m9_min_continuous_seconds", MIN_CONTINUOUS_SECONDS)),
            min_sample_gap_seconds=int(getattr(metrics, "m9_min_sample_gap_seconds", MIN_SAMPLE_GAP_SECONDS)),
            max_sample_gap_seconds=int(getattr(metrics, "m9_max_sample_gap_seconds", MAX_SAMPLE_GAP_SECONDS)),
            max_sample_age_seconds=int(getattr(metrics, "m9_max_sample_age_seconds", MAX_SAMPLE_AGE_SECONDS)),
            max_tracker_skew_seconds=int(getattr(metrics, "m9_max_tracker_skew_seconds", MAX_TRACKER_SKEW_SECONDS)),
        )


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _dt(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _as_utc(value)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_utc(parsed)


class M9TrustPolicy:
    def __init__(self, thresholds: M9Thresholds | None = None) -> None:
        self.thresholds = thresholds or M9Thresholds()

    def evaluate(self, samples: list[dict], now: datetime) -> TrustVerdict:
        if not samples:
            return TrustVerdict(False, MISSING_RUNTIME_EVIDENCE)
        ordered = [item for item in samples if _dt(item.get("sampled_at")) is not None]
        ordered.sort(key=lambda item: _dt(item.get("sampled_at")))
        if not ordered:
            return TrustVerdict(False, MISSING_RUNTIME_EVIDENCE)
        latest = ordered[-1]
        evidence = {
            "samples": len(ordered),
            "origin": latest.get("origin"),
            "tracker_started_at": latest.get("tracker_started_at"),
            "continuous_seconds": latest.get("continuous_seconds"),
            "interruptions": latest.get("interruptions", 0),
            "manual_interventions": latest.get("manual_interventions", 0),
        }
        if str(latest.get("origin") or "fixture") != "runtime":
            return TrustVerdict(False, FIXTURE_ORIGIN, evidence)
        started = _dt(latest.get("tracker_started_at"))
        if started is None:
            return TrustVerdict(False, MISSING_TRACKER_START, evidence)
        if int(latest.get("interruptions", 0)) != 0 or int(latest.get("manual_interventions", 0)) != 0:
            reason = INTERRUPTED if int(latest.get("interruptions", 0)) != 0 else MANUAL_INTERVENTION
            return TrustVerdict(False, reason, evidence)
        continuous = float(latest.get("continuous_seconds") or 0.0)
        if continuous < self.thresholds.min_continuous_seconds:
            return TrustVerdict(False, INSUFFICIENT_DURATION, evidence)
        previous = None
        for item in ordered:
            current = _dt(item.get("sampled_at"))
            if previous is not None and current is not None:
                if (current - previous).total_seconds() > self.thresholds.max_sample_gap_seconds:
                    return TrustVerdict(False, SAMPLE_GAP, evidence)
            previous = current
        current = _as_utc(now)
        sampled_at = _dt(latest.get("sampled_at"))
        age = (current - sampled_at).total_seconds() if sampled_at is not None else None
        if age is None or age > self.thresholds.max_sample_age_seconds:
            evidence["age_seconds"] = age
            return TrustVerdict(False, SAMPLE_STALE, evidence)
        span = (sampled_at - started).total_seconds()
        if abs(span - continuous) > self.thresholds.max_tracker_skew_seconds:
            evidence["span_seconds"] = span
            return TrustVerdict(False, DURATION_SKEW, evidence)
        evidence["age_seconds"] = age
        return TrustVerdict(True, "", evidence)

class M9Rule:
    metric_id = MetricId.M9

    def __init__(self, thresholds: M9Thresholds | None = None) -> None:
        self.policy = M9TrustPolicy(thresholds)

    def evaluate(self, evidence: CollectedEvidence, definition, now: datetime) -> RuleResult:
        samples = list(getattr(evidence, "self_run_samples", None) or [])
        if not samples and evidence.self_run_sample is not None:
            samples = [evidence.self_run_sample]
        verdict = self.policy.evaluate(samples, now)
        if not verdict.trusted:
            return RuleResult(
                metric_id=self.metric_id,
                channel_excluded_count=evidence.channel_excluded_count,
                source_ref="runtime self-run samples",
                evidence_present=True,
                details={
                    "unverified": True,
                    "unverified_reason": verdict.label,
                    "trust_reason": verdict.reason,
                    **{key: value for key, value in verdict.evidence.items() if key not in {"samples"}},
                },
            ).validate()
        continuous = float(verdict.evidence.get("continuous_seconds") or 0.0)
        result = RuleResult(
            metric_id=self.metric_id,
            channel_excluded_count=evidence.channel_excluded_count,
            source_ref="runtime self-run samples",
            covered_count=1,
            numerator=continuous / 3600.0,
            details={
                "trust_reason": "",
                **verdict.evidence,
            },
        )
        result.details["continuous_hours"] = result.numerator
        return result.validate()
