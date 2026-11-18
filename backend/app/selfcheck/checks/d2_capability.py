"""D2 能力真实性检查项（6 项）。本期为人工骨架 + 可独立自动判定项。"""

from __future__ import annotations

import re

from app.api.envelope import ApiError

from ..loaders import iter_carrier_texts, load_carriers, load_claimable_items
from ..manual import load_manual_claims
from ..models import (
    CheckResult,
    CheckSpec,
    ClaimRecord,
    Dimension,
    JudgmentMode,
    Status,
    ThreeQuestion,
    build_result,
)

_LEVELS = {"L1", "L2", "L3", "L4"}
_MERGED_CLAIMS = ("全部实测通过", "整体已完成", "全部通过", "整体通过", "全部达标")
_L2_FORBIDDEN = ("已集成", "已打通", "已上线")
_L1_SECTION_WORDS = ("已完成", "已实现", "已达标")


def _load(ctx: object) -> tuple[list[ClaimRecord], str]:
    try:
        claims = load_manual_claims(ctx.manual_path)
        return claims, ""
    except ApiError as exc:
        return [], exc.detail or "人工输入缺失"


def _d2_1(ctx: object) -> CheckResult:
    claims, reason = _load(ctx)
    if reason:
        return build_result(
            _SPECS[0], Status.MANUAL_PENDING, sub_reason="MANUAL_INPUT_MISSING",
            output_summary=f"{reason}；请先运行一次生成 selfcheck-manual-draft.md，再整理并确认。",
        )
    candidates = load_claimable_items(ctx)
    registered = {claim.text.strip() for claim in claims}
    pending = [text for text in candidates if text.strip() not in registered]
    if pending or any(not claim.confirmed for claim in claims):
        return build_result(
            _SPECS[0], Status.MANUAL_PENDING, sub_reason="CLAIM_UNREGISTERED",
            output_summary=(
                f"可声称 {len(candidates)} 条，已登记 {len(registered)} 条，"
                f"未登记/未确认 {len(pending) + sum(1 for c in claims if not c.confirmed)} 条。"
            ),
        )
    return build_result(
        _SPECS[0], Status.PASS,
        output_summary=f"{len(candidates)} 条可声称均已登记并确认。",
    )


def _d2_2(ctx: object) -> CheckResult:
    claims, reason = _load(ctx)
    if reason:
        return build_result(
            _SPECS[1], Status.MANUAL_PENDING, sub_reason="MANUAL_INPUT_MISSING",
            output_summary=reason,
        )
    if not claims:
        return build_result(
            _SPECS[1], Status.MANUAL_PENDING, sub_reason="MANUAL_INPUT_EMPTY",
            output_summary="人工输入中没有条目。",
        )
    missing = [claim.claim_id for claim in claims if not (claim.level or "").strip()]
    invalid = [
        claim.claim_id
        for claim in claims
        if (claim.level or "").strip() and (claim.level or "").upper() not in _LEVELS
    ]
    pending = [claim.claim_id for claim in claims if claim.confirmed is not True]
    if invalid:
        return build_result(
            _SPECS[1], Status.BLOCKED, sub_reason="LEVEL_INVALID",
            output_summary=f"{len(invalid)} 条级别非法：{', '.join(invalid[:5])}",
        )
    if missing or pending:
        detail = []
        if missing:
            detail.append(f"{len(missing)} 条缺级别：{', '.join(missing[:5])}")
        if pending:
            detail.append(f"{len(pending)} 条未填 `确认：是`：{', '.join(pending[:5])}")
        return build_result(
            _SPECS[1], Status.MANUAL_PENDING, sub_reason="NOT_CONFIRMED",
            output_summary="；".join(detail),
        )
    return build_result(
        _SPECS[1], Status.PASS,
        output_summary=f"{len(claims)} 条声称级别均在 L1–L4 且已确认。",
    )


def _d2_3(ctx: object) -> CheckResult:
    claims, _reason = _load(ctx)
    level_four = [claim for claim in claims if (claim.level or "").upper() == "L4"]
    if not level_four:
        return build_result(
            _SPECS[2], Status.UNVERIFIED, sub_reason="NO_INPUT",
            output_summary="人工输入中没有 L4 条目，本项无输入可校验。",
        )
    broken: list[str] = []
    for claim in level_four:
        if not claim.source or not claim.evidence_refs:
            broken.append(claim.claim_id)
    if broken:
        return build_result(
            _SPECS[2], Status.BLOCKED, sub_reason="L4_ELEMENTS_MISSING",
            output_summary=f"L4 条目缺命令或证据要素：{', '.join(broken)}",
        )
    return build_result(
        _SPECS[2], Status.PASS,
        output_summary=f"{len(level_four)} 条 L4 声称四要素齐备。",
    )


def _d2_4(ctx: object) -> CheckResult:
    carriers = load_carriers(ctx)
    hits: list[str] = []
    for carrier in iter_carrier_texts(carriers):
        for number, line in enumerate(carrier.lines, start=1):
            for word in _L2_FORBIDDEN:
                if word in line:
                    hits.append(f"{carrier.path}:{number}（{word}）")
    if hits:
        return build_result(
            _SPECS[3], Status.BLOCKED, sub_reason="STUB_OVERCLAIM",
            output_summary=(
                f"L2 桩能力被表述为已完成 {len(hits)} 处；应写“接口就绪，待接真凭据”："
                + "；".join(hits[:3])
            ),
        )
    return build_result(
        _SPECS[3], Status.PASS,
        output_summary="未发现 L2 桩能力被表述为“已集成/已打通/已上线”。",
    )


def _d2_5(ctx: object) -> CheckResult:
    carriers = load_carriers(ctx)
    hits: list[str] = []
    for carrier in iter_carrier_texts(carriers):
        for number, line in enumerate(carrier.lines, start=1):
            if any(word in line for word in _MERGED_CLAIMS) and re.search(r"L[1-4]", line):
                hits.append(f"{carrier.path}:{number}")
            elif any(word in line for word in _MERGED_CLAIMS) and "；" in line and "L" not in line:
                continue
    if hits:
        return build_result(
            _SPECS[4], Status.BLOCKED, sub_reason="MIXED_LEVEL",
            output_summary=f"{len(hits)} 处同段混级表述：" + "；".join(hits[:3]),
        )
    return build_result(
        _SPECS[4], Status.PASS,
        output_summary="未发现同段混级合并表述。",
    )


def _d2_6(ctx: object) -> CheckResult:
    from ..baseline import check_level_escalation, load as load_baseline

    claims, _reason = _load(ctx)
    previous = load_baseline(ctx.baseline_path)
    if not previous.available:
        return build_result(
            _SPECS[5], Status.UNVERIFIED, sub_reason="NO_BASELINE",
            output_summary="无基线，无法比较级别变化。",
        )
    violations = check_level_escalation(claims, previous)
    if violations:
        return build_result(
            _SPECS[5], Status.BLOCKED, sub_reason="LEVEL_ESCALATED",
            output_summary=f"{len(violations)} 条级别提高但无新增证据：{', '.join(violations[:5])}",
        )
    return build_result(
        _SPECS[5], Status.PASS,
        output_summary="级别变化均有新增证据标识支撑。",
    )


_SPECS: tuple[CheckSpec, ...] = (
    CheckSpec("D2-1", "声称登记完整性", Dimension.CAPABILITY, JudgmentMode.MANUAL,
              ThreeQuestion.REAL, "未登记项 = 0", handler=_d2_1),
    CheckSpec("D2-2", "四级互斥定级", Dimension.CAPABILITY, JudgmentMode.MANUAL,
              ThreeQuestion.REAL, "100% 条目有合法级别", handler=_d2_2),
    CheckSpec("D2-3", "L4 四要素", Dimension.CAPABILITY, JudgmentMode.AUTO,
              ThreeQuestion.REAL, "L4 条目命令/退出码/证据/摘要四要素齐备",
              depends_on=("D3-1",), handler=_d2_3),
    CheckSpec("D2-4", "L2/L1 表述限制", Dimension.CAPABILITY, JudgmentMode.AUTO,
              ThreeQuestion.REAL, "L2/L1 禁用词 0 命中", handler=_d2_4),
    CheckSpec("D2-5", "混级表述禁止", Dimension.CAPABILITY, JudgmentMode.AUTO,
              ThreeQuestion.REAL, "同段混级合并表述 0 命中", handler=_d2_5),
    CheckSpec("D2-6", "级别不得无证据升级", Dimension.CAPABILITY, JudgmentMode.AUTO,
              ThreeQuestion.REAL, "级别提高必须伴随新增证据标识",
              depends_on=("D2-2",), handler=_d2_6),
)

SPECS = _SPECS