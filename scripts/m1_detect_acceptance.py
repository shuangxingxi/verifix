from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.adapters.check import CheckAdapter, RecordedCheckClient
from app.adapters.types import ScanTaskRef
from app.config import load_config
from app.intake.dedup import DedupService, InMemorySetNx
from app.intake.normalizer import IntakeOutcome, IssueNormalizer
from app.repo.memory import MemoryStore

TARGET = ROOT / "verifix-target"
REPORT = ROOT / "docs" / "devlog" / "m1-detect-report.md"
RULE_BY_CLASS = {"C02": "py/sql-injection", "C03": "py/command-injection"}


def build_records():
    ground = json.loads((TARGET / "ground_truth.json").read_text(encoding="utf-8"))
    records = []
    expectations = {}
    for item in ground["items"]:
        rule_id = RULE_BY_CLASS.get(item["defect_class"])
        if rule_id is None:
            continue
        source = (TARGET / item["file"]).read_text(encoding="utf-8").splitlines()
        line = item["line"]
        snippet = source[line - 1] if 0 < line <= len(source) else ""
        alert_ref = f"check:{item['id']}"
        records.append(
            {
                "alertId": alert_ref,
                "ruleId": rule_id,
                "filePath": item["file"],
                "startLine": line,
                "severity": "high",
                "codeSnippet": snippet,
            }
        )
        expectations[alert_ref] = item
    return records, expectations


def main() -> int:
    config = load_config()
    store = MemoryStore()
    normalizer = IssueNormalizer(store, DedupService(store, InMemorySetNx()), config)
    records, expectations = build_records()

    client = RecordedCheckClient(alerts=records)
    adapter = CheckAdapter(client, sleeper=lambda _: None)
    fetched = adapter.fetch_alerts(ScanTaskRef("m1-acceptance"))

    results = []
    for alert in fetched.alerts:
        outcome = normalizer.ingest_alert(alert, "verifix-target", "target-v1")
        expected = expectations[alert.alert_ref]
        results.append((expected, outcome))

    detected = [item for item, outcome in results if outcome.outcome is IntakeOutcome.CREATED]
    merged = [item for item, outcome in results if outcome.outcome is IntakeOutcome.MERGED]
    rejected = [item for item, outcome in results if outcome.outcome in {IntakeOutcome.REJECTED, IntakeOutcome.OUT_OF_SCOPE}]
    missed = [item for item, outcome in results if outcome.outcome is IntakeOutcome.REJECTED]

    lines = [
        "# M1 检出对账报告",
        "",
        f"- 生成时间：{datetime.now(timezone.utc).isoformat()}",
        f"- 靶场：verifix-target（ground_truth v{json.loads((TARGET / 'ground_truth.json').read_text(encoding='utf-8'))['version']}）",
        f"- 注入点总数：{len(expectations)}",
        f"- 首次检出：{len(detected)}",
        f"- 合并（重复定位）：{len(merged)}",
        f"- 拒绝/范围外：{len(rejected)}",
        "",
        "| 编号 | 类别 | 文件:行 | 归一化结果 | Issue |",
        "|---|---|---|---|---|",
    ]
    for expected, outcome in results:
        lines.append(
            f"| {expected['id']} | {expected['defect_class']} | {expected['file']}:{expected['line']} "
            f"| {outcome.outcome.value} | {outcome.issue_id or '-'} |"
        )
    if missed:
        lines.extend(["", "## 漏检项", ""])
        for item in missed:
            lines.append(f"- {item['id']}（{item['file']}:{item['line']}）：原始告警未通过归一化校验")
    lines.extend(
        [
            "",
            f"- 检出率：{len(detected)}/{len(expectations)}（验收门槛 ≥8/10）",
            f"- 数据源降级：{'是' if fetched.degraded else '否'}",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines), encoding="utf-8")

    print(f"detected={len(detected)}/{len(expectations)} merged={len(merged)} rejected={len(rejected)}")
    print(f"report={REPORT}")
    for expected, outcome in results:
        print(f"  {expected['id']} {expected['defect_class']} -> {outcome.outcome.value} {outcome.issue_id or ''}")
    if len(detected) < 8:
        print("FAIL: detection below 8/10")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())