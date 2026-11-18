from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.reproducer.executor import LocalTestExecutor
from app.agents.reproducer.service import ReproducerService, ReproductionStatus
from app.adapters.check import CheckAdapter, RecordedCheckClient
from app.adapters.types import ScanTaskRef
from app.config import load_config
from app.intake.dedup import DedupService, InMemorySetNx
from app.intake.normalizer import IntakeOutcome, IssueNormalizer
from app.repo.memory import MemoryStore
from app.tracing.service import ReachabilityService

TARGET = ROOT / "verifix-target"
REPORT = ROOT / "docs" / "devlog" / "m2-reproduce-report.md"
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
        ScanTaskRef("m2-acceptance")
    )

    issue_map: dict[str, dict] = {}
    for alert in fetched.alerts:
        outcome = normalizer.ingest_alert(alert, "verifix-target", "target-v1")
        if outcome.outcome is IntakeOutcome.CREATED and outcome.issue_id:
            issue_map[outcome.issue_id] = expectations[alert.alert_ref]

    reachability = ReachabilityService(store, config)
    reproducer = ReproducerService(store, LocalTestExecutor(), config)

    rows = []
    proven = 0
    failed = 0
    infra = 0
    for issue_id, expected in issue_map.items():
        reachability.analyze(store.get(issue_id), TARGET)
        outcome = reproducer.reproduce(store.get(issue_id), TARGET)
        if outcome.status is ReproductionStatus.PROVEN:
            proven += 1
        elif outcome.status is ReproductionStatus.INFRA_ERROR:
            infra += 1
        else:
            failed += 1
        rows.append((expected, outcome))

    lines = [
        "# M2 造红验收报告",
        "",
        f"- 生成时间：{datetime.now(timezone.utc).isoformat()}",
        f"- 执行后端：local-dev（本机无 Docker；生产必须走沙箱 TOOL-05）",
        f"- 判定对象：靶场注入点 Issue {len(issue_map)} 条",
        f"- 造红成功：{proven}　失败：{failed}　基础设施异常：{infra}",
        "",
        "| 编号 | 类别 | 文件:行 | 行为 | 结果 | 说明 |",
        "|---|---|---|---|---|---|",
    ]
    for expected, outcome in rows:
        lines.append(
            f"| {expected['id']} | {expected['defect_class']} | {expected['file']}:{expected['line']} "
            f"| {outcome.behavior or '-'} | {outcome.status.value} | {outcome.message} |"
        )
    lines.extend(
        [
            "",
            f"- 造红率：{proven}/{len(issue_map)}（验收门槛 ≥6/10）",
            f"- 报告路径：{REPORT}",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines), encoding="utf-8")

    print(f"proven={proven} failed={failed} infra={infra} total={len(issue_map)}")
    print(f"report={REPORT}")
    for expected, outcome in rows:
        print(f"  {expected['id']} {outcome.status.value} {outcome.message}")
    if proven < 6:
        print("FAIL: red-state proof below 6/10")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())