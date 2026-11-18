from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.domain.enums import MetricId, StageTier
from app.domain.models import Metric, MetricReport
from app.metrics.definitions import DefinitionRegistry, MetricDirection
from app.metrics.legacy_baseline import LegacyBaselineRegistry


class ReportInconsistent(Exception):
    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__("; ".join(issues))


REQUIRED_PRELIMINARY = (MetricId.M1, MetricId.M4, MetricId.M5, MetricId.M9)
EVAL_METRICS = {MetricId.M1, MetricId.M2, MetricId.M3}


@dataclass
class ReportOutcome:
    record: MetricReport
    markdown: str
    rows: list[dict]


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _fmt_row(row: dict) -> str:
    if row.get("unverified"):
        return "未验证"
    return _fmt(row.get("value"))


class MetricReportService:
    def __init__(
        self,
        store,
        definitions: DefinitionRegistry | None = None,
        report_dir: Path | str | None = None,
        clock=None,
    ) -> None:
        self.store = store
        self.definitions = definitions or DefinitionRegistry()
        self.report_dir = Path(report_dir) if report_dir is not None else None
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def generate(
        self,
        window: str,
        tier: StageTier,
        actor: str,
        now: datetime | None = None,
        history_digest: str | None = None,
    ) -> ReportOutcome:
        current = now or self.clock()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        missing = self.definitions.missing(current)
        if missing:
            raise ReportInconsistent(["指标定义缺失：" + ",".join(sorted(item.value for item in missing))])

        records: dict[MetricId, Metric] = {}
        for metric_id in MetricId:
            record = self.store.metrics.get((metric_id.value, tier.value, window))
            if record is not None:
                records[metric_id] = record
        if len(records) != 9:
            absent = sorted(item.value for item in MetricId if item not in records)
            raise ReportInconsistent(["指标记录缺失：" + ",".join(absent)])

        self._validate(records, window, tier)

        definitions = self.definitions.all_effective(current)
        rows = [self._row(record, definitions[metric_id]) for metric_id, record in records.items()]
        publishable = [row for row in rows if row["publishable"]]
        conclusion = self._conclusion(records, definitions, tier, rows)
        version = self.store.next_report_version(window, tier)
        report_id = f"RPT-{window}-{tier.value}-{version:04d}"
        eval_run_id = next((row["eval_run_id"] for row in rows if row.get("eval_run_id")), "")
        binding = next((getattr(record, "binding_digest", None) for record in records.values() if getattr(record, "binding_digest", None)), None)
        markdown = self._markdown(
            report_id, window, tier, actor, conclusion, publishable, current,
            eval_run_id=eval_run_id, history_digest=history_digest, rows_all=rows,
        )
        digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()

        archive_ref = ""
        archived_at = None
        if self.report_dir is not None:
            self.report_dir.mkdir(parents=True, exist_ok=True)
            md_path = self.report_dir / f"{report_id}.md"
            json_path = self.report_dir / f"{report_id}.json"
            md_path.write_text(markdown, encoding="utf-8")
            json_path.write_text(
                json.dumps(
                    {
                        "report_id": report_id,
                        "version": version,
                        "window": window,
                        "tier": tier.value,
                        "conclusion": conclusion,
                        "generated_at": current.isoformat(),
                        "rows": rows,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            archive_ref = str(md_path)
            archived_at = current

        record = MetricReport(
            report_id=report_id,
            version=version,
            window=window,
            tier=tier,
            definition_version=sorted({item.definition_version for item in records.values()})[0],
            conclusion=conclusion,
            generated_at=current,
            content_digest=digest,
            archive_ref=archive_ref,
            archived_at=archived_at,
            eval_run_id=eval_run_id or None,
            binding_digest=binding,
            history_digest=history_digest,
        )
        self.store.put_report(record)
        return ReportOutcome(record=record, markdown=markdown, rows=rows)

    def _validate(self, records: dict[MetricId, Metric], window: str, tier: StageTier) -> None:
        issues: list[str] = []
        versions = {record.definition_version for record in records.values()}
        if len(versions) != 1:
            issues.append("混合定义版本：" + ",".join(sorted(versions)))
        recalc_ids = {record.recalc_id for record in records.values()}
        if None in recalc_ids or len(recalc_ids) != 1:
            issues.append("复算标识不一致或缺失")
        for metric_id, record in records.items():
            if record.window != window or record.stage_tier is not tier:
                issues.append(f"{metric_id.value}: 窗口/档位与请求不一致")
            if record.computable and record.reason_code is not None:
                issues.append(f"{metric_id.value}: 可计算却带原因码")
            if not record.computable and record.reason_code is None:
                issues.append(f"{metric_id.value}: 不可计算缺原因码")
            if record.trial and record.computable:
                issues.append(f"{metric_id.value}: 试算不得可计算")
            if record.computable and record.covered_count > 0 and record.numerator is not None:
                expected = record.numerator / record.covered_count
                if abs(expected - float(record.value)) > 1e-6:
                    issues.append(f"{metric_id.value}: 值与分子/覆盖数不一致")
        if issues:
            raise ReportInconsistent(issues)

    def _row(self, record: Metric, definition) -> dict:
        eval_run_id = ""
        for part in record.source_ref.split(" / "):
            if part.startswith("eval_run_id="):
                eval_run_id = part.split("=", 1)[1]
        publishable = True
        if record.metric_id in EVAL_METRICS:
            publishable = (bool(eval_run_id) or not record.computable) and "legacy_conclusion=True" not in record.source_ref
        else:
            publishable = bool(record.snapshot_digest)
        return {
            "metric_id": record.metric_id.value,
            "name": definition.name,
            "definition_version": record.definition_version,
            "unit": definition.unit.value,
            "value": record.value,
            "computable": record.computable,
            "unverified": record.unverified,
            "unverified_reason": record.unverified_reason,
            "reason_code": record.reason_code,
            "numerator": record.numerator,
            "denominator": record.denominator,
            "covered_count": record.covered_count,
            "excluded_count": record.excluded_count,
            "channel_excluded_count": record.channel_excluded_count,
            "not_applicable_count": record.not_applicable_count,
            "source_ref": record.source_ref,
            "trial": record.trial,
            "recalc_id": record.recalc_id,
            "snapshot_digest": record.snapshot_digest,
            "eval_run_id": eval_run_id,
            "computed_at": record.computed_at.isoformat(),
            "preliminary_target": definition.preliminary_target,
            "met": self._met(record, definition),
            "publishable": publishable,
        }

    def _met(self, record: Metric, definition) -> bool | None:
        if record.unverified or not record.computable or definition.preliminary_target in (None, 0.0):
            return None
        target = float(definition.preliminary_target)
        if definition.direction is MetricDirection.LOWER_IS_BETTER:
            return float(record.value) <= target
        return float(record.value) >= target

    def _conclusion(self, records: dict[MetricId, Metric], definitions: dict, tier: StageTier, rows: list[dict]) -> str:
        if any(row["trial"] for row in rows):
            return "UNDETERMINED"
        if any(not row["publishable"] for row in rows):
            return "UNDETERMINED"
        if tier is StageTier.PRELIMINARY:
            for metric_id in REQUIRED_PRELIMINARY:
                if not records[metric_id].computable:
                    return "UNDETERMINED"
        for metric_id, record in records.items():
            if not record.computable:
                continue
            met = self._met(record, definitions[metric_id])
            if met is False:
                return "FAIL"
        return "PASS"

    def _markdown(
        self,
        report_id,
        window,
        tier,
        actor,
        conclusion,
        rows,
        now,
        eval_run_id: str = "",
        history_digest: str | None = None,
        rows_all: list[dict] | None = None,
    ) -> str:
        lines = [
            f"# 主流程指标报告 {report_id}",
            "",
            f"- 窗口：{window}",
            f"- 阶段档：{tier.value}",
            f"- 定义版本：v2",
            f"- 生成时间：{now.isoformat()}",
            f"- 发起主体：{actor}",
            f"- 评测运行：{eval_run_id or '-'}",
            f"- 历史留痕摘要：{history_digest or '-'}",
            f"- 结论：{conclusion}",
            "",
            "| 指标 | 定义版本 | 值 | 可计算 | 原因码 | 分子 | 分母 | 覆盖 | 剔除 | 通道排除 | 不适用 | 采集源 | 复算标识 | 快照摘要 | 评测运行 | 初赛目标 | 达标 |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for row in rows:
            display = {key: _fmt(value) for key, value in row.items()}
            display["value"] = _fmt_row(row)
            lines.append(
                "| {metric_id} {name} | {definition_version} | {value} | {computable} | {reason_code} | {numerator} | {denominator} | {covered_count} | {excluded_count} | {channel_excluded_count} | {not_applicable_count} | {source_ref} | {recalc_id} | {snapshot_digest} | {eval_run_id} | {preliminary_target} | {met} |".format(
                    **display
                )
            )
        lines.append(LegacyBaselineRegistry().render(rows_all if rows_all is not None else rows))
        return "\n".join(lines)