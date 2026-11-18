"""只读读取器：载体遍历、Markdown 字段抽取、证据索引与引用反查。

只读保证：本模块不写入任何文件，也不调用 `EvidencePackWriter` 的写方法。

v1.1-R1：D4 的“固定载体”收敛为 `TEXT_CARRIERS` 三类文字载体；
演示文稿、演示视频、可访问演示入口由 D5-2 承担，不参与 D4 数值比对。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from .models import ConsistencyRow, EvidenceEntry

EVIDENCE_ID_RE = re.compile(
    r"\b(?:VER|SCAN|ISO)-\d{8}T\d{6}[+-]\d{4}(?:-[0-9a-fA-F]{4,8})?\b"
)

TEXT_CARRIERS: tuple[tuple[str, str, str], ...] = (
    ("README", "README.md", "README"),
    ("CLOSURE", "docs/devlog/m12-closure-and-blockers.md", "收尾与阻塞文档"),
    ("DELIVERABLES", "deliverables/CodeArts方案.md", "交付方案文档"),
)

DEMO_CARRIER: tuple[str, str, str] = (
    "DEMO",
    "deliverables/演示材料.md",
    "演示材料（由 D5-2 判定，不参与 D4 数值比对）",
)

# 兼容旧调用名：D4 的载体集合统一由 TEXT_CARRIERS 出口。
CARRIER_SPECS = TEXT_CARRIERS


@dataclass
class Carrier:
    key: str
    path: str
    label: str
    text: str = ""
    exists: bool = False

    @property
    def lines(self) -> list[str]:
        return self.text.splitlines()


@dataclass
class FieldHit:
    field: str
    value: str
    carrier: str
    location: str


@dataclass
class EvidenceIndexLoad:
    entries: list[EvidenceEntry] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    index_files: list[str] = field(default_factory=list)


def load_documents(ctx: object) -> dict[str, Carrier]:
    """证据引用反查需要扫描全部报告，而非仅四类固定载体。"""

    documents: dict[str, Carrier] = {}
    readme = ctx.read_text("README.md")
    if readme is not None:
        documents["README.md"] = Carrier("README", "README.md", "README", readme, True)
    devlog = Path(ctx.root) / "docs" / "devlog"
    if devlog.is_dir():
        for item in sorted(devlog.rglob("*.md")):
            if not item.is_file() or "selfcheck" in item.parts:
                continue
            if item.name in {"selfcheck-manual-draft.md", "m13-selfcheck-report.md"}:
                continue
            relative = ctx.rel(item)
            text = ctx.read_text(relative)
            if text is not None:
                documents[relative] = Carrier(relative, relative, relative, text, True)
    deliverables = Path(ctx.root) / "deliverables"
    if deliverables.is_dir():
        for item in sorted(deliverables.rglob("*.md")):
            if not item.is_file():
                continue
            relative = ctx.rel(item)
            text = ctx.read_text(relative)
            if text is not None:
                documents[relative] = Carrier(relative, relative, relative, text, True)
    return documents


def load_carriers(ctx: object) -> dict[str, Carrier]:
    carriers: dict[str, Carrier] = {}
    for key, relative, label in CARRIER_SPECS:
        text = ctx.read_text(relative)
        carriers[key] = Carrier(
            key=key,
            path=relative,
            label=label,
            text=text or "",
            exists=text is not None,
        )
    return carriers


def load_evidence_index(root: str | Path) -> EvidenceIndexLoad:
    base = Path(root) / ".evidence"
    result = EvidenceIndexLoad()
    if not base.is_dir():
        result.errors.append("证据目录缺失：.evidence")
        return result
    index_files = sorted(item for item in base.rglob("INDEX.json") if item.is_file())
    result.index_files = [item.as_posix() for item in index_files]
    if not index_files:
        result.errors.append("证据索引缺失：.evidence/**/INDEX.json")
        return result
    for index_path in index_files:
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            result.errors.append(f"证据索引不可解析：{index_path.name}（{type(exc).__name__}）")
            continue
        packs = payload.get("packs") if isinstance(payload, dict) else None
        if not isinstance(packs, list):
            result.errors.append(f"证据索引结构非法：{index_path.name}")
            continue
        for pack in packs:
            if not isinstance(pack, dict):
                continue
            evidence_id = str(pack.get("evidence_id", "")).strip()
            if not evidence_id:
                continue
            relative = str(pack.get("path") or evidence_id)
            candidate = index_path.parent / relative
            result.entries.append(
                EvidenceEntry(
                    evidence_id=evidence_id,
                    path=_posix_relative(candidate, Path(root)),
                    index_sha256=str(pack.get("sha256", "")),
                    verification_source=str(pack.get("verification_source", "")),
                )
            )
    return result


def _posix_relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def build_reference_map(carriers: dict[str, Carrier]) -> dict[str, list[str]]:
    references: dict[str, list[str]] = {}
    for carrier in carriers.values():
        if not carrier.exists:
            continue
        for number, line in enumerate(carrier.lines, start=1):
            for match in EVIDENCE_ID_RE.finditer(line):
                references.setdefault(match.group(0), []).append(
                    f"{carrier.path}:{number}"
                )
    return references


def extract_evidence_ids(text: str) -> list[str]:
    return sorted({match.group(0) for match in EVIDENCE_ID_RE.finditer(text)})


# ---- 口径字段抽取 ---------------------------------------------------
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_CASE_RE = re.compile(r"(\d+)\s*(?:条|个)?\s*用例|Ran\s+(\d+)\s+tests")
_HOUR_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:小时|hours?|h)\b")
_CATEGORY_RE = re.compile(r"(\d+)\s*类")
_SAMPLE_RE = re.compile(r"(?:\bn\s*=\s*|\bn=)(\d+)")

FIELD_RULES: dict[str, str] = {
    "覆盖率": "含“覆盖”且不含目标/阈值/要求/缺口/未达字样的百分比",
    "用例数": "N 用例 或 Ran N tests",
    "连续运行时长": "含“连续”的小时数",
    "缺陷类别数": "含“缺陷”的 N 类",
    "支出口径": "合并目标分支表述",
    "样本量": "n=<int>",
}

_EXCLUDE_COVERAGE_WORDS = ("目标", "阈值", "要求", "缺口", "未达", "不低于", "至少")
_METRIC_WORDS = (
    "覆盖", "检出", "修复", "通过率", "成功率", "准确率", "召回", "命中率", "一致率", "真扫", "隔离",
)


def extract_field_hits(carriers: dict[str, Carrier]) -> dict[str, list[FieldHit]]:
    hits: dict[str, list[FieldHit]] = {name: [] for name in FIELD_RULES}
    for carrier in carriers.values():
        if not carrier.exists:
            continue
        for number, line in enumerate(carrier.lines, start=1):
            location = f"{carrier.path}:{number}"
            if "覆盖" in line and not any(word in line for word in _EXCLUDE_COVERAGE_WORDS):
                for match in _PERCENT_RE.finditer(line):
                    hits["覆盖率"].append(
                        FieldHit("覆盖率", normalize_percent(match.group(1)), carrier.path, location)
                    )
            case_match = _CASE_RE.search(line)
            if case_match:
                value = case_match.group(1) or case_match.group(2)
                hits["用例数"].append(FieldHit("用例数", value, carrier.path, location))
            if "连续" in line:
                for match in _HOUR_RE.finditer(line):
                    hits["连续运行时长"].append(
                        FieldHit("连续运行时长", f"{match.group(1)}h", carrier.path, location)
                    )
            if "缺陷" in line:
                for match in _CATEGORY_RE.finditer(line):
                    hits["缺陷类别数"].append(
                        FieldHit("缺陷类别数", match.group(1), carrier.path, location)
                    )
            branch = extract_branch_statement(line)
            if branch:
                hits["支出口径"].append(
                    FieldHit("支出口径", branch, carrier.path, location)
                )
            sample_match = _SAMPLE_RE.search(line)
            if sample_match:
                hits["样本量"].append(
                    FieldHit("样本量", sample_match.group(1), carrier.path, location)
                )
    return hits


def normalize_percent(value: str) -> str:
    return f"{value}%"


def extract_branch_statement(line: str) -> str:
    if "自动合并主干" in line or "自动合并到主干" in line:
        return "自动合并主干"
    if "仅合并预发" in line or "只合并预发" in line:
        return "仅合并预发分支"
    if "release/auto" in line:
        return "release/auto"
    if "永不并 main" in line or "永不合并 main" in line:
        return "永不并 main"
    return ""


def build_consistency_rows(carriers: dict[str, Carrier]) -> list[ConsistencyRow]:
    hits = extract_field_hits(carriers)
    rows: list[ConsistencyRow] = []
    for name in FIELD_RULES:
        collected: dict[str, set[str]] = {}
        for hit in hits[name]:
            collected.setdefault(hit.carrier, set()).add(hit.value)
        values: dict[str, str] = {
            carrier: " / ".join(sorted(items)) for carrier, items in collected.items() if items
        }
        sample = ""
        for sample_hit in hits["样本量"]:
            if sample_hit.carrier in values:
                sample = f"n={sample_hit.value}"
                break
        rows.append(
            ConsistencyRow(
                field=name,
                values_by_carrier=values,
                sample_size=sample,
                definition_version="v1",
                verdict="未比较",
                conflict_level="",
            )
        )
    return rows


def percent_hits_with_sample(carriers: dict[str, Carrier]) -> list[tuple[FieldHit, Optional[str]]]:
    """百分比结论 → 同段/同表样本量；用于 D4-3。"""

    results: list[tuple[FieldHit, Optional[str]]] = []
    for carrier in carriers.values():
        if not carrier.exists:
            continue
        lines = carrier.lines
        for index, line in enumerate(lines):
            if any(word in line for word in _EXCLUDE_COVERAGE_WORDS):
                continue
            if not any(word in line for word in _METRIC_WORDS):
                continue
            match = _PERCENT_RE.search(line)
            if match:
                window = "\n".join(lines[max(0, index - 2): min(len(lines), index + 3)])
                sample_match = _SAMPLE_RE.search(window)
                hit = FieldHit(
                    "覆盖率",
                    normalize_percent(match.group(1)),
                    carrier.path,
                    f"{carrier.path}:{index + 1}",
                )
                results.append((hit, sample_match.group(1) if sample_match else None))
    return results


def find_section(text: str, keyword: str) -> Optional[str]:
    """返回包含关键词的最短标题行（Markdown #），用于 D5 定位。"""

    best: Optional[str] = None
    for line in text.splitlines():
        if keyword in line and line.lstrip().startswith("#"):
            if best is None or len(line) < len(best):
                best = line.strip()
    return best


def load_unclaimable_items(ctx: object) -> list[str]:
    text = ctx.read_text("docs/devlog/m12-closure-and-blockers.md") or ""
    items: list[str] = []
    collecting = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("**不可声称**"):
            collecting = True
            continue
        if collecting and stripped.startswith("**") and "不可声称" not in stripped:
            break
        if collecting and stripped.startswith("## "):
            break
        if collecting and stripped.startswith("- "):
            items.append(stripped[2:].strip())
    return items


def load_claimable_items(ctx: object) -> list[str]:
    text = ctx.read_text("docs/devlog/m12-closure-and-blockers.md") or ""
    items: list[str] = []
    collecting = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("**可声称**"):
            collecting = True
            continue
        if collecting and stripped.startswith("**"):
            break
        if collecting and stripped.startswith("## "):
            break
        if collecting and stripped.startswith("- "):
            items.append(stripped[2:].strip())
    return items


TEMPLATE_ITEMS: tuple[str, ...] = (
    "作品名称与一句话",
    "背景与价值",
    "创新性解读",
    "方案设计",
    "数据集与处理",
    "关键代码解读",
    "可量化指标",
    "CodeArts 使用说明",
    "部署与演示",
    "团队分工与排期",
)

_TEMPLATE_SECTION_HINTS: dict[str, tuple[str, ...]] = {
    "作品名称与一句话": ("一页速览", "作品", "名称"),
    "背景与价值": ("项目背景与价值", "背景"),
    "创新性解读": ("创新性解读", "创新"),
    "方案设计": ("系统设计", "方案设计"),
    "数据集与处理": ("数据集与处理", "数据集"),
    "关键代码解读": ("关键代码", "代码解读"),
    "可量化指标": ("可量化指标", "指标"),
    "CodeArts 使用说明": ("CodeArts 使用设计", "CodeArts"),
    "部署与演示": ("部署与演示", "部署"),
    "团队分工与排期": ("团队分工与排期", "团队分工"),
}


def locate_template_items(carriers: dict[str, Carrier]) -> list[dict[str, str]]:
    deliverables = carriers.get("DELIVERABLES")
    rows: list[dict[str, str]] = []
    for item in TEMPLATE_ITEMS:
        mapped_file = deliverables.path if deliverables and deliverables.exists else ""
        section = ""
        if deliverables and deliverables.exists:
            for hint in _TEMPLATE_SECTION_HINTS[item]:
                found = find_section(deliverables.text, hint)
                if found:
                    section = found
                    break
        rows.append({"item": item, "file": mapped_file, "section": section})
    return rows


def iter_carrier_texts(carriers: dict[str, Carrier]) -> Iterable[Carrier]:
    for carrier in carriers.values():
        if carrier.exists:
            yield carrier