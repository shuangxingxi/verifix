"""人工输入解析与草稿生成。

解析只读取负责人填写的字段；草稿只做"抽取与定位"，级别、结论、确认列一律留空。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from app.api.envelope import ApiError, ErrorCode

from .loaders import EVIDENCE_ID_RE, TEMPLATE_ITEMS, load_carriers, locate_template_items
from .models import ClaimRecord

_FIELD_KEYS = ("声称", "载体", "真实来源", "级别", "证据", "样本量", "确认", "缺口等级", "补齐成本")
_HEADING_RE = re.compile(r"^###\s+(CLM-[A-Za-z0-9-]+)\s*$")


def load_manual_claims(path: str | Path) -> list[ClaimRecord]:
    candidate = Path(path)
    if not candidate.is_file():
        raise ApiError(ErrorCode.SELFCHECK_MANUAL_PENDING, f"人工输入缺失：{candidate.name}")
    try:
        text = candidate.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise ApiError(
            ErrorCode.SELFCHECK_MANUAL_PENDING,
            f"人工输入不可解析：{type(exc).__name__}",
        ) from exc
    return parse_manual_text(text, source=candidate.as_posix())


def parse_manual_text(text: str, *, source: str = "selfcheck-manual.md") -> list[ClaimRecord]:
    records: list[ClaimRecord] = []
    current_id: Optional[str] = None
    current: dict[str, str] = {}
    open_block = False

    def flush() -> None:
        nonlocal current_id, current, open_block
        if current_id is None:
            return
        records.append(_to_record(current_id, current, source, closed=open_block))
        current_id = None
        current = {}
        open_block = False

    in_comment = False
    for line in text.splitlines():
        stripped_line = line.strip()
        if in_comment:
            if "-->" in stripped_line:
                in_comment = False
            continue
        if "<!--" in stripped_line:
            if "-->" not in stripped_line:
                in_comment = True
            continue
        heading = _HEADING_RE.match(line.strip())
        if heading:
            flush()
            current_id = heading.group(1)
            open_block = True
            continue
        if current_id is None:
            continue
        stripped = line.strip()
        if stripped.startswith("### "):
            flush()
            continue
        if stripped.startswith("- ") and "：" in stripped:
            key, value = stripped[2:].split("：", 1)
            if key.strip() in _FIELD_KEYS:
                current[key.strip()] = value.strip()
    flush()
    return records


def _to_record(claim_id: str, values: dict[str, str], source: str, *, closed: bool) -> ClaimRecord:
    confirm = values.get("确认", "")
    confirmed: Optional[bool]
    if not closed or not values:
        confirmed = None
    elif confirm == "是":
        confirmed = True
    else:
        confirmed = False
    sample_raw = values.get("样本量", "")
    sample: Optional[int] = None
    if sample_raw.isdigit():
        sample = int(sample_raw)
    evidence_text = values.get("证据", "")
    evidence_refs = sorted({match.group(0) for match in EVIDENCE_ID_RE.finditer(evidence_text)})
    return ClaimRecord(
        claim_id=claim_id,
        text=values.get("声称", ""),
        carrier=values.get("载体", ""),
        location=values.get("载体", ""),
        claim_type="能力型",
        level=values.get("级别") or None,
        source=values.get("真实来源") or None,
        evidence_refs=evidence_refs,
        sample_size=sample,
        confirmed=confirmed,
    )


MANUAL_TEMPLATE = """# 自检人工输入（请负责人填写）

格式：每个条目一个三级标题（`### CLM-001`），字段以 `- 字段名：值` 单行声明。
`确认` 字段只有填写 `是` 才视为已确认；其他任何取值均按“人工待填”处理。
本文件由负责人维护，自检只读，不代填判定。

<!-- 示例（注释块，不参与解析）
### CLM-000
- 声称：示例声称原文
- 载体：README.md §8
- 真实来源：执行命令或报告名
- 级别：L3
- 证据：无
- 样本量：不适用
- 确认：待确认
-->
"""


def ensure_manual_template(path: str | Path, *, dry_run: bool) -> bool:
    candidate = Path(path)
    if candidate.exists() or dry_run:
        return False
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text(MANUAL_TEMPLATE, encoding="utf-8")
    return True


def render_draft(ctx: object) -> tuple[str, int]:
    """生成候选草稿：只给候选声称与模板定位，不做任何判定。"""

    carriers = load_carriers(ctx)
    lines: list[str] = [
        "# 自检人工输入草稿（机器生成，需人工确认）",
        "",
        "本文件只抽取候选声称行与模板项定位；级别、结论、确认列一律留空，",
        "请整理进 `docs/devlog/selfcheck-manual.md` 并填写 `确认：是`。",
        "",
        "## 候选声称",
        "",
    ]
    count = 0
    claimable = ctx.read_text("docs/devlog/m12-closure-and-blockers.md") or ""
    collecting = False
    for line in claimable.splitlines():
        stripped = line.strip()
        if stripped.startswith("**可声称**"):
            collecting = True
            continue
        if collecting and stripped.startswith("**"):
            break
        if collecting and stripped.startswith("- "):
            count += 1
            lines.append(f"### CLM-{count:03d}")
            lines.append(f"- 声称：{stripped[2:].strip()}")
            lines.append("- 载体：（待人工定位）")
            lines.append("- 真实来源：（待人工填写）")
            lines.append("- 级别：")
            lines.append("- 证据：")
            lines.append("- 样本量：")
            lines.append("- 确认：")
            lines.append("")
    if count == 0:
        lines.append("（未从收尾文档抽取到可声称条目）")
        lines.append("")
    lines.extend(["## 候选模板项（D5-1 定位线索）", ""])
    for row in locate_template_items(carriers):
        lines.append(f"- {row['item']}：文件 `{row['file'] or '（缺）'}`，章节 `{row['section'] or '（缺）'}`")
    lines.append("")
    lines.extend(["## 缺口定级（D5-3）", ""])
    for item in TEMPLATE_ITEMS:
        lines.append(f"- {item}：缺口等级（待填）／补齐成本（待填）")
    lines.append("")
    text = "\n".join(lines)
    return text, count