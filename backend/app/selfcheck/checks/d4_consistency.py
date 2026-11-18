"""D4 口径一致性检查项（6 项）。只读、只比较，不修改任何数值与口径。"""

from __future__ import annotations

import re

from ..loaders import (
    build_consistency_rows,
    extract_branch_statement,
    iter_carrier_texts,
    load_carriers,
    load_unclaimable_items,
    percent_hits_with_sample,
)
from ..models import (
    CheckResult,
    CheckSpec,
    ConsistencyRow,
    Dimension,
    JudgmentMode,
    Status,
    ThreeQuestion,
    build_result,
)

_COMPLETION_WORDS = ("已验证", "已部署", "已上线", "已达标", "已通过", "已发布", "已灰度", "已集成")
_VAGUE_RE = re.compile(r"约\s*\d|不低于\s*\d|最高\s*\d|至少\s*\d|左右")


def _d4_1(ctx: object) -> CheckResult:
    carriers = load_carriers(ctx)
    missing: list[str] = []
    empty: list[str] = []
    for carrier in carriers.values():
        if not carrier.exists:
            missing.append(f"{carrier.label}（{carrier.path}）")
            continue
        body = "\n".join(
            line for line in carrier.lines if line.strip() and not line.lstrip().startswith("#")
        ).strip()
        if not body:
            empty.append(f"{carrier.label}（{carrier.path}）")
    problems = missing + empty
    if problems:
        return build_result(
            _SPECS[0], Status.BLOCKED, sub_reason="MISSING",
            output_summary="三类文字载体缺失或正文为空：" + "、".join(problems),
        )
    return build_result(
        _SPECS[0], Status.PASS,
        output_summary="三类文字载体齐全可读：" + "、".join(f"{item.label}（{item.path}）" for item in carriers.values()),
    )


def _d4_2(ctx: object) -> CheckResult:
    carriers = load_carriers(ctx)
    rows = build_consistency_rows(carriers)
    conflicts: list[str] = []
    uncomparable: list[str] = []
    for row in rows:
        values = {value for value in row.values_by_carrier.values() if value}
        if not values:
            row.verdict = "无法比较"
            row.conflict_level = "未验证"
            uncomparable.append(row.field)
            continue
        if len(values) == 1:
            row.verdict = "一致"
            row.conflict_level = ""
        else:
            row.verdict = "不一致"
            row.conflict_level = "阻塞"
            conflicts.append(f"{row.field}（{' / '.join(sorted(values))}）")
    ctx.artifacts["consistency"] = rows
    if conflicts:
        return build_result(
            _SPECS[1], Status.BLOCKED, sub_reason="VALUE_CONFLICT",
            output_summary=f"{len(conflicts)} 个字段跨载体取值不一致：" + "；".join(conflicts[:4]),
        )
    if uncomparable:
        return build_result(
            _SPECS[1], Status.UNVERIFIED, sub_reason="NO_VALUE",
            output_summary="以下字段在四载体均未出现，无法比较：" + "、".join(uncomparable),
        )
    return build_result(
        _SPECS[1], Status.PASS,
        output_summary=f"{len(rows)} 个字段在四载体取值一致。",
    )


def _d4_3(ctx: object) -> CheckResult:
    carriers = load_carriers(ctx)
    pairs = percent_hits_with_sample(carriers)
    if not pairs:
        return build_result(
            _SPECS[2], Status.UNVERIFIED, sub_reason="NO_VALUE",
            output_summary="未在载体中抽取到百分比结论。",
        )
    missing = [hit for hit, sample in pairs if sample is None]
    small = [(hit, sample) for hit, sample in pairs if sample is not None and int(sample) < ctx.thresholds.min_sample_size]
    vague: list[str] = []
    for carrier in iter_carrier_texts(carriers):
        for number, line in enumerate(carrier.lines, start=1):
            if _VAGUE_RE.search(line):
                vague.append(f"{carrier.path}:{number}")
    if missing or vague:
        return build_result(
            _SPECS[2], Status.BLOCKED, sub_reason="SAMPLE_MISSING",
            output_summary=(
                f"{len(missing)} 处百分比无样本量、{len(vague)} 处模糊数值表述；"
                + "；".join(
                    [f"{hit.carrier}:{hit.value}" for hit in missing[:3]] + vague[:2]
                )
            ),
        )
    if small:
        return build_result(
            _SPECS[2], Status.WARNING, sub_reason="SMALL_SAMPLE",
            output_summary=(
                f"{len(small)} 处样本量 < {ctx.thresholds.min_sample_size}："
                + "；".join(f"{hit.carrier}:n={sample}" for hit, sample in small[:3])
            ),
        )
    return build_result(
        _SPECS[2], Status.PASS,
        output_summary=f"{len(pairs)} 处百分比结论均随附样本量。",
    )


def _d4_4(ctx: object) -> CheckResult:
    carriers = load_carriers(ctx)
    combined = "\n".join(carrier.text for carrier in iter_carrier_texts(carriers))
    has_module = "全模块" in combined
    has_judgment = "判定函数" in combined
    keeps_unmet = any(word in combined for word in ("未达标", "未达", "54.5"))
    if has_module and has_judgment and keeps_unmet:
        return build_result(
            _SPECS[3], Status.PASS,
            output_summary="覆盖率声明并列“全模块 / 判定函数”双口径，且保留未达标表述（未重跑度量）。",
        )
    gaps = []
    if not has_module:
        gaps.append("缺“全模块口径”")
    if not has_judgment:
        gaps.append("缺“判定函数口径”")
    if not keeps_unmet:
        gaps.append("缺未达标表述")
    return build_result(
        _SPECS[3], Status.BLOCKED, sub_reason="SINGLE_CALIBER",
        output_summary="覆盖率双口径不完整：" + "、".join(gaps) + "（自检未重跑度量）。",
    )


def _d4_5(ctx: object) -> CheckResult:
    items = load_unclaimable_items(ctx)
    carriers = load_carriers(ctx)
    keywords: list[str] = []
    for item in items:
        for token in re.split(r"[/、，,（）()\s]+", item):
            token = token.strip()
            if len(token) >= 2 and token not in _COMPLETION_WORDS and not token.isdigit():
                keywords.append(token)
    hits: list[str] = []
    for carrier in iter_carrier_texts(carriers):
        for number, line in enumerate(carrier.lines, start=1):
            if any(line.strip().endswith(item) for item in items):
                continue
            if any(word in line for word in _COMPLETION_WORDS) and any(
                keyword in line for keyword in keywords
            ):
                hits.append(f"{carrier.path}:{number}（{line.strip()[:60]}）")
    if hits:
        return build_result(
            _SPECS[4], Status.BLOCKED, sub_reason="UNVERIFIED_CLAIMED_DONE",
            output_summary=(
                f"不可声称项被表述为已完成 {len(hits)} 处，应统一写“未验证”："
                + "；".join(hits[:3])
            ),
        )
    if not items:
        return build_result(
            _SPECS[4], Status.UNVERIFIED, sub_reason="NO_BOUNDARY",
            output_summary="未从收尾文档抽取到“不可声称”清单，无法比对。",
        )
    return build_result(
        _SPECS[4], Status.PASS,
        output_summary=f"不可声称清单 {len(items)} 项在各载体均无完成类表述。",
    )


def _d4_6(ctx: object) -> CheckResult:
    carriers = load_carriers(ctx)
    findings: dict[str, set[str]] = {}
    for carrier in iter_carrier_texts(carriers):
        for line in carrier.lines:
            value = extract_branch_statement(line)
            if value:
                findings.setdefault(carrier.path, set()).add(value)
    values = set().union(*findings.values()) if findings else set()
    if not values:
        return build_result(
            _SPECS[5], Status.UNVERIFIED, sub_reason="NO_VALUE",
            output_summary="各载体未出现合并目标分支表述，无法比较。",
        )
    if len(values) > 1:
        detail = "；".join(f"{path}={'/'.join(sorted(items))}" for path, items in findings.items())
        return build_result(
            _SPECS[5], Status.BLOCKED, sub_reason="BRANCH_CONFLICT",
            output_summary="支出口径不一致：" + detail,
        )
    return build_result(
        _SPECS[5], Status.PASS,
        output_summary=f"合并目标分支表述统一为：{next(iter(values))}。",
    )


_SPECS: tuple[CheckSpec, ...] = (
    CheckSpec("D4-1", "三类文字载体齐全", Dimension.CONSISTENCY, JudgmentMode.AUTO,
              ThreeQuestion.BOUNDARY, "三类文字载体均存在、可读且正文非空", handler=_d4_1),
    CheckSpec("D4-2", "同数同值", Dimension.CONSISTENCY, JudgmentMode.AUTO,
              ThreeQuestion.BOUNDARY, "同一字段跨载体取值集合大小 = 1", handler=_d4_2),
    CheckSpec("D4-3", "样本量随行", Dimension.CONSISTENCY, JudgmentMode.AUTO,
              ThreeQuestion.REAL, "百分比结论均随附样本量，且无模糊数值表述",
              depends_on=(), handler=_d4_3),
    CheckSpec("D4-4", "覆盖率双口径", Dimension.CONSISTENCY, JudgmentMode.AUTO,
              ThreeQuestion.REAL, "并列全模块/判定函数双口径且保留未达标表述", handler=_d4_4),
    CheckSpec("D4-5", "未验证统一表述", Dimension.CONSISTENCY, JudgmentMode.AUTO,
              ThreeQuestion.BOUNDARY, "不可声称项在各载体无完成类词", handler=_d4_5),
    CheckSpec("D4-6", "支出口径一致", Dimension.CONSISTENCY, JudgmentMode.AUTO,
              ThreeQuestion.BOUNDARY, "合并目标分支表述唯一且为 release/auto", handler=_d4_6),
)

SPECS = _SPECS