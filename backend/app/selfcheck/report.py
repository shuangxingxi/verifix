"""报告渲染与归档：JSON、Markdown、staging 原子改名、索引只追加、入口副本。

本模块是四个写盘通道中的三个（归档、索引、入口副本）的唯一实现处。
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from app.api.envelope import ApiError, ErrorCode

from .context import mask, run_stamp
from .models import CheckResult, Dimension, SelfcheckResult, Status, WriteOutcome

SUMMARY_HEADING = "## 13. 报告自摘要"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _cell(value: Any, limit: int = 160) -> str:
    text = mask(str(value or "")).replace("\r", " ").replace("\n", "<br>")
    text = text.replace("|", "\\|")
    if len(text) > limit:
        text = text[:limit] + "…"
    return text or "—"


def to_json(result: SelfcheckResult) -> dict[str, Any]:
    payload = asdict(result)
    payload["self_digest"] = None
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)
    digest = _sha256_text(serialized)
    payload["self_digest"] = digest
    result.self_digest = digest
    return payload


def render_markdown(result: SelfcheckResult, ctx: Any) -> str:
    checks = result.checks
    blocked = [item for item in checks if item.status is Status.BLOCKED]
    warnings = [item for item in checks if item.status is Status.WARNING]
    pending = [item for item in checks if item.status is Status.MANUAL_PENDING]
    unverified = [item for item in checks if item.status is Status.UNVERIFIED]
    scope_text = "全量" if result.scope == [item.value for item in Dimension] else ", ".join(result.scope)
    readonly_files = getattr(result, "readonly_files", {}) or {}
    notes = getattr(result, "notes", []) or []
    exemptions = []
    if getattr(ctx, "allow_writes", False):
        exemptions.append("`--allow-writes`：D1-4 可写 eval/runs 与 docs/devlog/eval-report.md")
    if getattr(ctx, "refresh_evidence", False):
        exemptions.append("`--refresh-evidence`：D1-6 可写 .evidence/sandbox-realscan")
    readonly_text = "全量只读成立" if result.readonly_ok else "只读违规（见第 6 章）"
    if exemptions:
        readonly_text += "；豁免范围：" + "；".join(exemptions)

    lines: list[str] = [
        "# M13 自检报告",
        "",
        f"- 生成时间：{result.generated_at}",
        f"- 运行标识：{result.run_id or '（未分配）'}",
        f"- 基线：{result.baseline_id or '无基线'}",
        f"- 范围：{scope_text}",
        f"- 退出码：{result.exit_code}",
        f"- 执行域：本机默认环境（不预设 PYTHONUTF8）",
        f"- 只读状态：{readonly_text}",
        f"- 指纹：{result.fingerprint}",
        f"- 口径版本：{result.definition_version}",
        "- 口径修订：R1 D4-1 载体四类 → 三类文字载体（演示材料移交 D5-2）；"
        "R2 D5-1 去除 D4-1 依赖；definition_version v1 → v2",
        "",
        "## 1. 总体结论",
        "",
        f"- 结论：**{result.overall}**（退出码 {result.exit_code}）",
        f"- 实质阻塞：{len(blocked)} 项",
        f"- 人工待填：{len(pending)} 项（与实质阻塞分列，不混计）",
        f"- 警告：{len(warnings)} 项；未验证：{len(unverified)} 项",
        "- 推导依据：按“全局阻塞/阻塞 → 人工待填 → 警告 → 未验证 → 全通过”顺序命中即停，不以通过项数量判定。",
        "",
        "## 2. 五维度汇总",
        "",
        "| 维度 | 通过 | 警告 | 阻塞 | 未验证 | 人工待填 |",
        "|---|---|---|---|---|---|",
    ]
    for row in result.dimensions:
        lines.append(
            f"| {row.dimension.value} {row.dimension.label} | {row.passed} | {row.warning} | "
            f"{row.blocked} | {row.unverified} | {row.manual_pending} |"
        )
    lines.extend(
        [
            "",
            "## 3. 三问必答",
            "",
            f"- 最弱环节：{result.weakest_link}",
        ]
    )
    for item in result.top_questions:
        lines.append(f"- 评委高危提问：{item}")
    lines.append("- 工期与顺序：人工待填（自检不推断）")
    lines.extend(
        [
            "",
            "## 4. 检查项明细",
            "",
            "| 编号 | 状态 | 方式 | 命令/依据 | 输出摘要 | 耗时(s) | 基线变化 | 证据 |",
            "|---|---|---|---|---|---|---|---|",
        ]
    )
    for item in checks:
        evidence = ", ".join(item.evidence_refs) if item.evidence_refs else "无"
        basis = item.command or (item.sub_reason or "")
        change_text = (
            "口径变更，不视为回归"
            if item.baseline_change == "DEFINITION_CHANGED"
            else item.baseline_change
        )
        lines.append(
            f"| {item.check_id} | {item.status.value} | {item.mode.value} | {_cell(basis)} | "
            f"{_cell(item.output_summary)} | {item.duration_seconds:.2f} | {_cell(change_text, 20)} | {_cell(evidence, 60)} |"
        )
    lines.extend(["", "## 5. 阻塞与警告清单", ""])
    flagged = blocked + pending + warnings
    if not flagged:
        lines.append("本次运行未发现阻塞、警告或人工待填项。")
    else:
        lines.extend(["| 编号 | 状态 | 原因 | 解除条件 |", "|---|---|---|---|"])
        for item in flagged:
            lines.append(
                f"| {item.check_id} | {item.status.value} | {_cell(item.sub_reason or item.output_summary)} | {_cell(item.output_summary)} |"
            )
    if not result.readonly_ok:
        lines.extend(["", "**只读违规明细**", ""])
        for kind, values in readonly_files.items():
            lines.append(f"- {kind}：{', '.join(values) if values else '无'}")
    lines.extend(["", "## 6. 修复优先级", ""])
    for item in result.fix_priority:
        lines.append(f"- {item}")
    lines.extend(["", "## 7. 声称来源追溯表", ""])
    if not result.claims:
        lines.append("本次未抽取到已确认的声称条目（D2 为人工骨架，见第 12 章）。")
    else:
        lines.extend(
            [
                "| 编号 | 声称 | 载体 | 真实来源 | 级别 | 证据 | 确认 | 可否对外 |",
                "|---|---|---|---|---|---|---|---|",
            ]
        )
        for claim in result.claims:
            confirmed = "是" if claim.confirmed else "待确认"
            external = "可" if claim.level in {"L3", "L4"} and confirmed == "是" else "不可"
            lines.append(
                f"| {claim.claim_id} | {_cell(claim.text)} | {_cell(claim.carrier, 60)} | "
                f"{_cell(claim.source, 60)} | {claim.level or '—'} | "
                f"{_cell(', '.join(claim.evidence_refs) or '无', 60)} | {confirmed} | {external} |"
            )
    lines.extend(["", "## 8. 口径冲突清单", ""])
    lines.append("核对载体：三类文字载体（README / 收尾与阻塞文档 / 交付方案文档）；演示材料不参与 D4 数值比对。")
    lines.append("")
    if not result.consistency:
        lines.append("本次未产生口径比对结果。")
    else:
        lines.extend(
            [
                "| 字段 | 各载体取值 | 样本量 | 一致性 | 冲突级别 | 处置建议 |",
                "|---|---|---|---|---|---|",
            ]
        )
        for row in result.consistency:
            values = "；".join(f"{key}={value}" for key, value in row.values_by_carrier.items()) or "未出现"
            advice = {"阻塞": "先统一口径，禁止只改口径不改数值", "警告": "补充样本量或改为方向性结论"}.get(row.conflict_level, "保持现状并复核")
            lines.append(
                f"| {row.field} | {_cell(values, 240)} | {row.sample_size or '—'} | {row.verdict} | {row.conflict_level or '—'} | {advice} |"
            )
    lines.extend(["", "## 9. 证据完整性明细", ""])
    if not result.evidence:
        lines.append("本次未读取到证据索引或未产生证据明细。")
    else:
        lines.extend(
            [
                "| 证据 | 索引摘要 | 完整性 | 被引用位置 | 不一致项 |",
                "|---|---|---|---|---|",
            ]
        )
        for entry in result.evidence:
            lines.append(
                f"| {entry.evidence_id} | {entry.index_sha256[:16]}… | {'通过' if entry.integrity_ok else '不通过'} | "
                f"{_cell(', '.join(entry.referenced_by) or '未引用', 120)} | {_cell(', '.join(entry.mismatches) or '无', 120)} |"
            )
    lines.extend(["", "## 10. 交付缺口清单", ""])
    lines.append("清单范围：模板十项 + 模板外必交三件（演示文稿 / 演示视频 / 可访问演示入口）。")
    lines.append("")
    if not result.delivery:
        lines.append("本次未产生模板映射结果。")
    else:
        lines.extend(
            [
                "| 模板项 | 映射文件 | 映射章节 | 缺口等级 | 补齐方式 |",
                "|---|---|---|---|---|",
            ]
        )
        for row in result.delivery:
            lines.append(
                f"| {row.template_item} | {row.mapped_file or '缺'} | {row.mapped_section or '缺'} | "
                f"{row.gap_level or '—'} | {row.cost_estimate or '—'} |"
            )
    lines.extend(["", "## 11. 未执行与未验证说明", ""])
    unverified_rows = [item for item in unverified]
    if not unverified_rows:
        lines.append("本次无未验证项。")
    else:
        lines.extend(["| 编号 | 原因 | 说明 |", "|---|---|---|"])
        for item in unverified_rows:
            lines.append(
                f"| {item.check_id} | {_cell(item.sub_reason or 'UNVERIFIED', 40)} | {_cell(item.output_summary)} |"
            )
    if notes:
        lines.extend(["", "补充说明：", ""])
        for note in notes:
            lines.append(f"- {note}")
    lines.extend(["", "## 12. 口径与执行域声明", ""])
    lines.append("- 本报告只诊断“声称是否有证据支撑”与“口径是否一致”，不修复被检问题、不补造证据、不代填人工判定。")
    lines.append("- 标注“未验证”的项表示环境不可用或执行条件未成立，不得外推为通过。")
    body = "\n".join(lines)
    digest = _sha256_text(body)
    body += (
        "\n\n"
        + SUMMARY_HEADING
        + "\n"
        + f"- sha256：{digest}\n"
        + f"- 归档路径：{result.run_id or '未归档'}/report.md\n"
    )
    return body


class ReportWriter:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    def write(self, result: SelfcheckResult) -> WriteOutcome:
        output_dir: Path = self.ctx.output_dir
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            run_id = self._next_run_id()
            result.run_id = run_id
            payload = to_json(result)
            json_text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            markdown = render_markdown(result, self.ctx)
            report_sha = _sha256_text(markdown)
            json_sha = _sha256_text(json_text)

            staging = output_dir / "staging" / run_id
            staging.mkdir(parents=True, exist_ok=False)
            (staging / "report.md").write_text(markdown, encoding="utf-8", newline="\n")
            (staging / "selfcheck.json").write_text(json_text, encoding="utf-8", newline="\n")
            archive = output_dir / run_id
            os.replace(staging, archive)
            try:
                staging.parent.rmdir()
            except OSError:
                pass
            index_updated = self._append_index(
                {
                    "run_id": run_id,
                    "generated_at": result.generated_at,
                    "scope": result.scope,
                    "overall": result.overall,
                    "exit_code": result.exit_code,
                    "fingerprint": result.fingerprint,
                    "report_sha256": report_sha,
                    "json_sha256": json_sha,
                }
            )
            entry_updated = self._update_entry(markdown, json_text, run_id)
        except OSError as exc:
            raise ApiError(
                ErrorCode.SELFCHECK_REPORT_WRITE_FAILED,
                f"{type(exc).__name__}: {exc}",
            ) from exc
        return WriteOutcome(
            run_id=run_id,
            archive_dir=str(archive),
            report_path=str(archive / "report.md"),
            json_path=str(archive / "selfcheck.json"),
            index_updated=index_updated,
            entry_updated=entry_updated,
            self_digest=str(payload.get("self_digest", "")),
        )

    def _next_run_id(self) -> str:
        version = len(self._index_entries()) + 1
        return f"SC-{run_stamp(self.ctx.clock)}-v{version}"

    def _index_path(self) -> Path:
        return self.ctx.output_dir / "index.json"

    def _index_entries(self) -> list[dict[str, Any]]:
        path = self._index_path()
        if not path.is_file():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        entries = payload.get("entries") if isinstance(payload, dict) else None
        return list(entries) if isinstance(entries, list) else []

    def _append_index(self, entry: dict[str, Any]) -> bool:
        try:
            entries = self._index_entries()
            entries.append(entry)
            path = self._index_path()
            temporary = path.with_name("index.json.tmp")
            temporary.write_text(
                json.dumps({"entries": entries}, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, path)
        except OSError:
            return False
        return True

    def _update_entry(self, markdown: str, json_text: str, run_id: str) -> bool:
        try:
            self.ctx.entry_json.parent.mkdir(parents=True, exist_ok=True)
            self.ctx.entry_json.write_text(json_text, encoding="utf-8", newline="\n")
            self.ctx.entry_report.write_text(
                markdown + f"\n<!-- archive: {run_id} -->\n", encoding="utf-8", newline="\n"
            )
        except OSError:
            return False
        return True

    def repair_index(self) -> int:
        """扫描归档目录补登记缺失条目，幂等。"""

        output_dir: Path = self.ctx.output_dir
        if not output_dir.is_dir():
            return 0
        known = {item.get("run_id") for item in self._index_entries()}
        added = 0
        for candidate in sorted(output_dir.iterdir()):
            if not candidate.is_dir() or candidate.name in {"staging"}:
                continue
            if candidate.name in known:
                continue
            report = candidate / "report.md"
            payload = candidate / "selfcheck.json"
            if not report.is_file() or not payload.is_file():
                continue
            try:
                data = json.loads(payload.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if self._append_index(
                {
                    "run_id": candidate.name,
                    "generated_at": data.get("generated_at", ""),
                    "scope": data.get("scope", []),
                    "overall": data.get("overall", ""),
                    "exit_code": data.get("exit_code", 3),
                    "fingerprint": data.get("fingerprint", ""),
                    "report_sha256": _sha256_text(report.read_text(encoding="utf-8")),
                    "json_sha256": _sha256_text(payload.read_text(encoding="utf-8")),
                }
            ):
                added += 1
        return added


def verify_report(path: str | Path) -> bool:
    candidate = Path(path)
    if not candidate.is_file():
        return False
    text = candidate.read_text(encoding="utf-8")
    if candidate.suffix.lower() == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return False
        recorded = payload.get("self_digest")
        payload["self_digest"] = None
        recomputed = _sha256_text(
            json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)
        )
        return recorded == recomputed
    marker = "\n" + SUMMARY_HEADING
    body, separator, tail = text.rpartition(marker)
    if not separator:
        return False
    if body.endswith("\n"):
        body = body[:-1]
    digest = _sha256_text(body)
    return f"- sha256：{digest}" in tail