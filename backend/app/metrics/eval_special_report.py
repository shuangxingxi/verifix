from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.api.envelope import ApiError, ErrorCode
from app.domain.enums import MetricId
from app.eval.models import EvalLoadRecord, EvalVerdict
from app.metrics.report import ReportOutcome, _fmt, _fmt_row

EVAL_REF_METRICS = (MetricId.M1, MetricId.M2, MetricId.M3)
REF_ONLY_METRICS = (MetricId.M4, MetricId.M5, MetricId.M6, MetricId.M7, MetricId.M8, MetricId.M9)
ARCHIVE_PREFIX = "EVALRPT-"


@dataclass
class SpecialReportOutcome:
    report_id: str
    markdown: str
    rows: list[dict]
    conclusion: str
    markdown_path: Path | None = None


class EvalSpecialReportBuilder:
    def __init__(self, report_dir: Path | str = "docs/devlog") -> None:
        self.report_dir = Path(report_dir)

    def build(
        self,
        main: ReportOutcome,
        verdict: EvalVerdict | None = None,
        load_record: EvalLoadRecord | None = None,
        actor: str = "judge",
        now: datetime | None = None,
        version: int = 1,
    ) -> SpecialReportOutcome:
        if verdict is None:
            raise ApiError(ErrorCode.EVAL_NOT_ADJUDICATED, "运行未完成裁决，不输出 M1–M3")
        current = now or datetime.now(timezone.utc)
        report_id = f"{ARCHIVE_PREFIX}{main.record.window}-{main.record.tier.value}-{version:04d}"
        rows: list[dict] = []
        for metric_id in EVAL_REF_METRICS:
            row = next((item for item in main.rows if item["metric_id"] == metric_id.value), None)
            if row is None:
                raise ApiError(ErrorCode.REPORT_INCONSISTENT, f"主报告缺少 {metric_id.value}")
            rows.append(row)
        for metric_id in REF_ONLY_METRICS:
            rows.append({"metric_id": metric_id.value, "ref": f"{main.record.report_id}#{metric_id.value}"})

        lines = [
            f"# 评测通道专项报告 {report_id}",
            "",
            f"- 窗口：{main.record.window}",
            f"- 阶段档：{main.record.tier.value}",
            f"- 定义版本：{main.record.definition_version}",
            f"- 生成时间：{current.isoformat()}",
            f"- 发起主体：{actor}",
            f"- 评测运行：{verdict.eval_run_id}",
            f"- 用例摘要：{load_record.cases_digest if load_record else '-'}",
            f"- 绑定摘要：{verdict.binding_digest}",
            f"- 主报告：{main.record.report_id}",
            f"- 结论：{main.record.conclusion}",
            "",
            "## 四类通过率（独立标注，不可替代 M1）",
            "",
            "| 类别 | 数量 | 通过 | 通过率 |",
            "|---|---|---|---|",
        ]
        for item in verdict.category_stats:
            rate = (item.passed / item.total) if item.total else 0.0
            lines.append(f"| {item.category.value} | {item.total} | {item.passed} | {rate:.0%} |")
        lines.extend(
            [
                "",
                "## M1–M3（直接引用主报告，不重算）",
                "",
                "| 指标 | 值 | 可计算 | 未验证 | 原因码 | 分子 | 分母 | 采集源 |",
                "|---|---|---|---|---|---|---|---|",
            ]
        )
        for row in rows[:3]:
            lines.append(
                "| {metric_id} | {value} | {computable} | {unverified} | {reason_code} | {numerator} | {denominator} | {source_ref} |".format(
                    **{key: _fmt(row.get(key)) for key in ("metric_id", "computable", "unverified", "reason_code", "numerator", "denominator", "source_ref")},
                    value=_fmt_row(row),
                )
            )
        lines.extend(
            [
                "",
                "## M4–M9（只引用主报告，不含数值与自判文案）",
                "",
                "| 指标 | 引用 |",
                "|---|---|",
            ]
        )
        for row in rows[3:]:
            lines.append(f"| {row['metric_id']} | {row['ref']} |")
        lines.append("")
        markdown = "\n".join(lines)
        path = None
        try:
            self.report_dir.mkdir(parents=True, exist_ok=True)
            path = self.report_dir / "eval-report.md"
            path.write_text(markdown, encoding="utf-8")
        except OSError:
            path = None
        return SpecialReportOutcome(
            report_id=report_id,
            markdown=markdown,
            rows=rows,
            conclusion=main.record.conclusion,
            markdown_path=path,
        )