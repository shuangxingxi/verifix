from __future__ import annotations

from enum import Enum


class UncomputableReason(str, Enum):
    SOURCE_MISSING = "SOURCE_MISSING"
    DENOMINATOR_EMPTY = "DENOMINATOR_EMPTY"
    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    EVIDENCE_INCONSISTENT = "EVIDENCE_INCONSISTENT"
    COVERAGE_INSUFFICIENT = "COVERAGE_INSUFFICIENT"
    DEFINITION_UNREGISTERED = "DEFINITION_UNREGISTERED"
    WINDOW_NOT_CLOSED = "WINDOW_NOT_CLOSED"
    FIRST_ATTEMPT_EVIDENCE_MISSING = "FIRST_ATTEMPT_EVIDENCE_MISSING"


class JudgmentStage(str, Enum):
    DEFINITION = "DEFINITION"
    SOURCE = "SOURCE"
    EVIDENCE = "EVIDENCE"
    DENOMINATOR = "DENOMINATOR"
    JUDGE = "JUDGE"


REASON_STAGE: dict[UncomputableReason, JudgmentStage] = {
    UncomputableReason.DEFINITION_UNREGISTERED: JudgmentStage.DEFINITION,
    UncomputableReason.SOURCE_MISSING: JudgmentStage.SOURCE,
    UncomputableReason.EVIDENCE_MISSING: JudgmentStage.EVIDENCE,
    UncomputableReason.EVIDENCE_INCONSISTENT: JudgmentStage.EVIDENCE,
    UncomputableReason.COVERAGE_INSUFFICIENT: JudgmentStage.EVIDENCE,
    UncomputableReason.FIRST_ATTEMPT_EVIDENCE_MISSING: JudgmentStage.EVIDENCE,
    UncomputableReason.DENOMINATOR_EMPTY: JudgmentStage.DENOMINATOR,
    UncomputableReason.WINDOW_NOT_CLOSED: JudgmentStage.JUDGE,
}

REASON_LABELS: dict[UncomputableReason, str] = {
    UncomputableReason.SOURCE_MISSING: "采集源缺失",
    UncomputableReason.DENOMINATOR_EMPTY: "分母为空",
    UncomputableReason.EVIDENCE_MISSING: "证据缺失",
    UncomputableReason.EVIDENCE_INCONSISTENT: "证据矛盾",
    UncomputableReason.COVERAGE_INSUFFICIENT: "证据覆盖不足",
    UncomputableReason.DEFINITION_UNREGISTERED: "指标定义未登记",
    UncomputableReason.WINDOW_NOT_CLOSED: "窗口未闭合",
    UncomputableReason.FIRST_ATTEMPT_EVIDENCE_MISSING: "首次尝试证据缺失",
}

EXCLUSION_ALLOWED_REASONS = frozenset(
    {UncomputableReason.EVIDENCE_MISSING, UncomputableReason.EVIDENCE_INCONSISTENT}
)

STAGE_ORDER: tuple[JudgmentStage, ...] = (
    JudgmentStage.DEFINITION,
    JudgmentStage.SOURCE,
    JudgmentStage.EVIDENCE,
    JudgmentStage.DENOMINATOR,
    JudgmentStage.JUDGE,
)


def all_reason_codes() -> frozenset[UncomputableReason]:
    return frozenset(UncomputableReason)


def is_reason_code(value: object) -> bool:
    return isinstance(value, UncomputableReason) or (
        isinstance(value, str) and value in {item.value for item in UncomputableReason}
    )


def coerce_reason(value: str | UncomputableReason) -> UncomputableReason:
    if isinstance(value, UncomputableReason):
        return value
    try:
        return UncomputableReason(value)
    except ValueError as exc:
        raise ValueError(f"unknown uncomputable reason code: {value}") from exc


def reason_label(value: str | UncomputableReason | None) -> str:
    if value is None:
        return ""
    return REASON_LABELS[coerce_reason(value)]


def stage_of(value: str | UncomputableReason) -> JudgmentStage:
    return REASON_STAGE[coerce_reason(value)]