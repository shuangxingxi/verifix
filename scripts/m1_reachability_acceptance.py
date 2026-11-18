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
from app.domain.enums import IssueStatus, VerdictConclusion
from app.intake.dedup import DedupService, InMemorySetNx
from app.intake.normalizer import IntakeOutcome, IssueNormalizer
from app.repo.memory import MemoryStore
from app.tracing.service import ReachabilityService

TARGET = ROOT / "verifix-target"
REPORT = ROOT / "docs" / "devlog" / "m1-reachability-report.md"
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
    fetched = CheckAdapter(RecordedCheckClient(alerts=records), sleeper=lambda _: None).fetch_alerts(
        ScanTaskRef("m1-reachability")
    )

    mapping: dict[str, dict] = {}
    for alert in fetched.alerts:
        outcome = normalizer.ingest_alert(alert, "verifix-target", "target-v1")
        if outcome.outcome is IntakeOutcome.CREATED and outcome.issue_id:
            mapping[outcome.issue_id] = expectations[alert.alert_ref]

    service = ReachabilityService(store, config)
    rows = []
    reached = unreachable = suspected = 0
    consistent = 0
    for issue_id, expected in mapping.items():
        issue = store.get(issue_id)
        outcome = service.analyze(issue, TARGET)
        status = outcome.issue_status
        conclusion = outcome.verdict.conclusion if outcome.verdict else None
        if status is IssueStatus.REACHABLE:
            reached += 1
        elif status is IssueStatus.ARCHIVED:
            unreachable += 1
        else:
            suspected += 1
        agrees = (expected["reachable"] and conclusion is VerdictConclusion.REACHABLE) or (
            not expected["reachable"] and conclusion is VerdictConclusion.UNREACHABLE
        )
        if agrees:
            consistent += 1
        rows.append((expected, outcome, agrees))

    lines = [
        "# M1 可达性判定报告",
        "",
        f"- 生成时间：{datetime.now(timezone.utc).isoformat()}",
        f"- 判定对象：靶场注入点 Issue {len(mapping)} 条",
        f"- 可达：{reached}　不可达：{unreachable}　可疑：{suspected}",
        f"- 与人工标注一致：{consistent}/{len(mapping)}",
        "",
        "| 编号 | 类别 | 文件:行 | 结论 | 置信度 | 路径 |",
        "|---|---|---|---|---|---|",
    ]
    for expected, outcome, agrees in rows:
        verdict = outcome.verdict
        path = " → ".join(verdict.taint_path) if verdict and verdict.taint_path else "-"
        lines.append(
            f"| {expected['id']} | {expected['defect_class']} | {expected['file']}:{expected['line']} "
            f"| {verdict.conclusion.value if verdict else '-'} | {verdict.confidence if verdict else '-'} | {path} |"
        )
        if not agrees:
            lines.append(f"| ! | 与人工标注不一致 | | | | {outcome.message} |")
    lines.extend(["", f"报告路径：{REPORT}", ""])
    REPORT.write_text("\n".join(lines), encoding="utf-8")

    print(f"reachable={reached} unreachable={unreachable} suspected={suspected} consistent={consistent}/{len(mapping)}")
    print(f"report={REPORT}")
    if len(mapping) < 8:
        print("FAIL: fewer than 8 injection issues analyzed")
        return 1
    if any(outcome.verdict is None for _, outcome, _ in rows):
        print("FAIL: issue without verdict")
        return 1
    if consistent < 8:
        print(f"FAIL: reachability consistency {consistent}/{len(mapping)} below 8")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())