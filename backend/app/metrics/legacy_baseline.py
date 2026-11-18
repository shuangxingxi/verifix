from __future__ import annotations

from app.domain.enums import MetricId


HISTORICAL_ENTRIES: dict[str, dict[str, str]] = {
    MetricId.M1.value: {
        "historical": "1.0000（可计算）",
        "reason": "历史 m5 报告以单文件评测集口径记 1.0；新口径为裁决后的正例+边界检出率，分母固定 30",
    },
    MetricId.M2.value: {
        "historical": "1.0000（可计算）",
        "reason": "历史报告记录 1.0；新口径要求显式漏洞检出字段，缺失即 SOURCE_MISSING，不本地推导",
    },
    MetricId.M3.value: {
        "historical": "1.0000（可计算）",
        "reason": "历史报告记录 1.0；新口径分母为有可达性标注样本数，须由裁决结论披露分子分母",
    },
    MetricId.M4.value: {
        "historical": "不可计算",
        "reason": "历史 m5 报告只覆盖评测通道；新口径按 v2 主流程复现证据计算",
    },
    MetricId.M5.value: {
        "historical": "不可计算",
        "reason": "历史 m5 报告未采集首次补丁尝试；新口径取门禁结论与门禁尝试",
    },
    MetricId.M6.value: {
        "historical": "不可计算",
        "reason": "历史文本曾以日志口径描述 M6；新口径采集源为门禁结论与门禁尝试",
    },
    MetricId.M7.value: {
        "historical": "不可计算",
        "reason": "历史 m5 报告未覆盖主流程时效；新口径按告警首次观测与 PR 就绪时间差计算",
    },
    MetricId.M8.value: {
        "historical": "不可计算",
        "reason": "历史 m5 报告未覆盖主流程处置率；新口径按 v2 主流程处置与门禁证据计算",
    },
    MetricId.M9.value: {
        "historical": "24.0000（可计算、达标）",
        "reason": "历史值来自夹具采样；新口径要求真实运行时连续 24 小时证据，否则为未验证",
    },
}


class LegacyBaselineRegistry:
    def entries(self) -> list[dict[str, str]]:
        return [
            {
                "metric_id": metric_id,
                "historical": item["historical"],
                "reason": item["reason"],
            }
            for metric_id, item in HISTORICAL_ENTRIES.items()
        ]

    def render(self, rows: list[dict]) -> str:
        by_id = {row["metric_id"]: row for row in rows}
        lines = [
            "",
            "## 与历史 m5 报告的口径差异对照",
            "",
            "| 指标 | 历史值/状态 | 新值/状态 | 差异原因 |",
            "|---|---|---|---|",
        ]
        for entry in self.entries():
            row = by_id.get(entry["metric_id"], {})
            if row.get("unverified"):
                current = "未验证（不可计算，达标 -）"
            elif row.get("computable"):
                current = f"{float(row.get('value') or 0.0):.4f}（可计算）"
            else:
                current = "-（不可计算，原因码 SOURCE_MISSING）"
            lines.append(
                f"| {entry['metric_id']} | {entry['historical']} | {current} | {entry['reason']} |"
            )
        lines.append("")
        return "\n".join(lines)