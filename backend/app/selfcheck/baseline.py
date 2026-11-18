"""基线读取与比较：只用于"比较"，不得把基线状态填入本次结果。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .models import ClaimRecord, CheckResult, Status

_LEVEL_ORDER = {"L1": 1, "L2": 2, "L3": 3, "L4": 4}


@dataclass
class Baseline:
    baseline_id: Optional[str] = None
    run_id: Optional[str] = None
    definition_version: str = ""
    statuses: dict[str, str] = field(default_factory=dict)
    levels: dict[str, str] = field(default_factory=dict)
    raw: dict = field(default_factory=dict)
    note: str = ""

    @property
    def available(self) -> bool:
        return self.baseline_id is not None


def load(path: str | Path) -> Baseline:
    candidate = Path(path)
    if not candidate.is_file():
        return Baseline(note="无基线")
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Baseline(note="基线不可解析，按首次执行")
    if not isinstance(payload, dict):
        return Baseline(note="基线结构非法，按首次执行")
    if str(payload.get("format_version", "")) not in {"1.0"}:
        return Baseline(note="基线格式版本未知，按首次执行")
    statuses: dict[str, str] = {}
    for item in payload.get("checks") or []:
        if isinstance(item, dict) and item.get("check_id"):
            statuses[str(item["check_id"])] = str(item.get("status", ""))
    levels = {
        str(item.get("claim_id")): str(item.get("level"))
        for item in payload.get("claims") or []
        if isinstance(item, dict) and item.get("claim_id") and item.get("level")
    }
    baseline_id = str(payload.get("fingerprint") or payload.get("run_id") or "") or None
    return Baseline(
        baseline_id=baseline_id,
        run_id=str(payload.get("run_id") or "") or None,
        definition_version=str(payload.get("definition_version", "")),
        statuses=statuses,
        levels=levels,
        raw=payload,
        note="基线可读",
    )


def compare(
    previous: Baseline,
    current: list[CheckResult],
    *,
    definition_version: str = "",
) -> dict[str, str]:
    if not previous.available:
        return {item.check_id: "UNCHANGED" for item in current}
    if (
        definition_version
        and previous.definition_version
        and previous.definition_version != definition_version
    ):
        return {item.check_id: "DEFINITION_CHANGED" for item in current}
    changes: dict[str, str] = {}
    blocked = Status.BLOCKED.value
    for item in current:
        before = previous.statuses.get(item.check_id)
        now = item.status.value
        if before is None:
            changes[item.check_id] = "UNCHANGED"
        elif before != blocked and now == blocked:
            changes[item.check_id] = "NEW_BLOCKER"
        elif before == blocked and now != blocked:
            changes[item.check_id] = "RESOLVED"
        else:
            changes[item.check_id] = "UNCHANGED"
    return changes


def check_level_escalation(
    claims: list[ClaimRecord], previous: Baseline
) -> list[str]:
    """级别高于基线但无新增证据标识 → 违规（供 D2-6 消费）。"""

    violations: list[str] = []
    for claim in claims:
        if not claim.level or claim.claim_id not in previous.levels:
            continue
        before = _LEVEL_ORDER.get(previous.levels[claim.claim_id], 0)
        now = _LEVEL_ORDER.get(claim.level, 0)
        if now > before and not claim.evidence_refs:
            violations.append(claim.claim_id)
    return violations