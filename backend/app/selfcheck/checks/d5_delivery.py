"""D5 交付完整性检查项（5 项）。自动定位 + 人工确认骨架。"""

from __future__ import annotations

import re

from ..loaders import iter_carrier_texts, load_carriers, locate_template_items
from ..manual import load_manual_claims
from ..models import (
    CheckResult,
    CheckSpec,
    DeliveryRow,
    Dimension,
    JudgmentMode,
    Status,
    ThreeQuestion,
    build_result,
)

_PLACEHOLDER_WORDS = ("TODO", "TBD", "待补", "占位", "待填写", "XXX")
_TRACE_WORDS = ("截图", "日志", "发布单", "运行记录", "流水线", "Pipeline", "留痕")
_MEDIA_SUFFIXES = {
    "presentation": (".pptx", ".ppt", ".key"),
    "video": (".mp4", ".mov", ".avi", ".mkv"),
}


def _d5_1(ctx: object) -> CheckResult:
    carriers = load_carriers(ctx)
    rows = locate_template_items(carriers)
    ctx.artifacts["delivery"] = [
        DeliveryRow(
            template_item=row["item"],
            mapped_file=row["file"] or None,
            mapped_section=row["section"] or None,
            gap_level="待人工确认",
            cost_estimate="",
        )
        for row in rows
    ]
    if not carriers["DELIVERABLES"].exists:
        return build_result(
            _SPECS[0], Status.MANUAL_PENDING, sub_reason="NEED_CONFIRM",
            output_summary=(
                "交付方案文档缺失，模板十项无法自动定位；覆盖度与缺口定级需负责人确认"
                "（本项独立判定，不因其他检查项结果被传导为阻塞）。"
            ),
        )
    missing_section = [row["item"] for row in rows if not row["section"]]
    return build_result(
        _SPECS[0], Status.MANUAL_PENDING, sub_reason="NEED_CONFIRM",
        output_summary=(
            f"已自动定位模板 {len(rows)} 项；其中 {len(missing_section)} 项缺章节位置，"
            "覆盖度需负责人确认并填写缺口等级。"
        ),
    )


def _d5_2(ctx: object) -> CheckResult:
    deliverables = ctx.root / "deliverables"
    found: dict[str, list[str]] = {"presentation": [], "video": []}
    if deliverables.is_dir():
        for key, suffixes in _MEDIA_SUFFIXES.items():
            for item in deliverables.rglob("*"):
                if item.is_file() and item.suffix.lower() in suffixes:
                    found[key].append(ctx.rel(item))
    demo: list[str] = []
    for carrier in iter_carrier_texts(load_carriers(ctx)):
        for number, line in enumerate(carrier.lines, start=1):
            if re.search(r"https?://", line) and any(
                word in line.lower() for word in ("demo", "演示", "可访问")
            ):
                demo.append(f"{carrier.path}:{number}")
    gaps = []
    if not found["presentation"]:
        gaps.append("演示文稿缺失")
    if not found["video"]:
        gaps.append("演示视频缺失")
    if not demo:
        gaps.append("可访问演示入口缺失")
    if gaps:
        return build_result(
            _SPECS[1], Status.BLOCKED, sub_reason="DELIVERY_GAP",
            output_summary="模板外必交三件不完备：" + "、".join(gaps),
        )
    return build_result(
        _SPECS[1], Status.PASS,
        output_summary="演示文稿、演示视频、可访问演示入口三项齐备。",
    )


def _d5_3(ctx: object) -> CheckResult:
    try:
        claims = load_manual_claims(ctx.manual_path)
    except Exception:  # noqa: BLE001 - 人工输入缺失统一按待填
        claims = []
    graded = [
        claim
        for claim in claims
        if claim.confirmed is True and claim.level
    ]
    if not graded:
        return build_result(
            _SPECS[2], Status.MANUAL_PENDING, sub_reason="MANUAL_INPUT_MISSING",
            output_summary="人工输入中没有已确认的缺口等级与补齐成本，按待填处理。",
        )
    return build_result(
        _SPECS[2], Status.MANUAL_PENDING, sub_reason="NEED_CONFIRM",
        output_summary=f"已登记 {len(graded)} 条，缺口定级仍需负责人确认。",
    )


def _d5_4(ctx: object) -> CheckResult:
    target = ctx.root / "deliverables" / "CodeArts方案.md"
    if not target.is_file():
        return build_result(
            _SPECS[3], Status.BLOCKED, sub_reason="MISSING",
            output_summary="deliverables/CodeArts方案.md 缺失。",
        )
    text = target.read_text(encoding="utf-8", errors="replace")
    standalone = [
        line.strip()
        for line in text.splitlines()
        if line.strip() in _PLACEHOLDER_WORDS
        or line.strip().startswith(("TODO", "TBD", "待补", "待填写"))
    ]
    placeholders = sorted({item for item in standalone if item})
    if len(text.strip()) < 500 or placeholders:
        return build_result(
            _SPECS[3], Status.BLOCKED, sub_reason="PLACEHOLDER",
            output_summary=(
                f"材料正文 {len(text)} 字符；占位特征：{', '.join(placeholders) or '无'}。"
            ),
        )
    return build_result(
        _SPECS[3], Status.PASS,
        output_summary=f"交付方案可打开，正文 {len(text)} 字符，无占位特征。",
    )


def _d5_5(ctx: object) -> CheckResult:
    clues: list[str] = []
    for carrier in iter_carrier_texts(load_carriers(ctx)):
        for number, line in enumerate(carrier.lines, start=1):
            if any(word in line for word in _TRACE_WORDS):
                clues.append(f"{carrier.path}:{number}")
    if not clues:
        return build_result(
            _SPECS[4], Status.WARNING, sub_reason="NO_TRACE",
            output_summary="未检索到日志/截图/发布单/运行记录引用。",
        )
    return build_result(
        _SPECS[4], Status.MANUAL_PENDING, sub_reason="NEED_CONFIRM",
        output_summary=f"自动检索到 {len(clues)} 处痕迹线索，充分性需负责人确认。",
    )


_SPECS: tuple[CheckSpec, ...] = (
    CheckSpec("D5-1", "模板十项映射", Dimension.DELIVERY, JudgmentMode.MANUAL,
              ThreeQuestion.BOUNDARY, "十项均有文件 + 章节位置并由人确认覆盖度",
              depends_on=(), handler=_d5_1),
    CheckSpec("D5-2", "模板外必交三件", Dimension.DELIVERY, JudgmentMode.AUTO,
              ThreeQuestion.BOUNDARY, "演示文稿、视频、可访问入口三项齐备", handler=_d5_2),
    CheckSpec("D5-3", "缺项定级与补齐成本", Dimension.DELIVERY, JudgmentMode.MANUAL,
              ThreeQuestion.BOUNDARY, "每缺项有等级与成本估计", handler=_d5_3),
    CheckSpec("D5-4", "材料可打开且非占位", Dimension.DELIVERY, JudgmentMode.AUTO,
              ThreeQuestion.REAL, "正文非空超过阈值且无占位特征", handler=_d5_4),
    CheckSpec("D5-5", "使用说明真实痕迹", Dimension.DELIVERY, JudgmentMode.MANUAL,
              ThreeQuestion.REAL, "≥1 处真实痕迹并由人确认充分性", handler=_d5_5),
)

SPECS = _SPECS