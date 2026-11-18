from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.adapters.check import CheckAdapter, RecordedCheckClient
from app.adapters.types import ScanTaskRef
from app.agents.patcher.service import PatcherService
from app.agents.reproducer.executor import LocalTestExecutor
from app.agents.reproducer.service import ReproducerService, ReproductionStatus
from app.config import load_config
from app.intake.dedup import DedupService, InMemorySetNx
from app.intake.normalizer import IntakeOutcome, IssueNormalizer
from app.repo.memory import MemoryStore
from app.tracing.service import ReachabilityService

TARGET = ROOT / "verifix-target"
REPORT = ROOT / "docs" / "devlog" / "m3-patch-report.md"
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
        ScanTaskRef("m3-acceptance")
    )

    issue_map: dict[str, dict] = {}
    for alert in fetched.alerts:
        outcome = normalizer.ingest_alert(alert, "verifix-target", "target-v1")
        if outcome.outcome is IntakeOutcome.CREATED and outcome.issue_id:
            issue_map[outcome.issue_id] = expectations[alert.alert_ref]

    reachability = ReachabilityService(store, config)
    reproducer = ReproducerService(store, LocalTestExecutor(), config)
    patcher = PatcherService(store, config)

    rows = []
    patched = 0
    rejected = 0
    generated_failed = 0
    for issue_id, expected in issue_map.items():
        reachability.analyze(store.get(issue_id), TARGET)
        repro = reproducer.reproduce(store.get(issue_id), TARGET)
        if repro.status is not ReproductionStatus.PROVEN:
            rows.append((expected, repro.status.value, "REPRO_NOT_PROVEN", repro.message, 0, 0.0))
            generated_failed += 1
            continue
        outcome = patcher.patch(store.get(issue_id), TARGET)
        if outcome.status == "PATCHED":
            patched += 1
        elif outcome.status == "REJECTED":
            rejected += 1
        else:
            generated_failed += 1
        patch = outcome.patch
        rows.append(
            (
                expected,
                repro.status.value,
                outcome.status,
                outcome.message,
                patch.lines_changed if patch else 0,
                patch.patch_strength if patch else 0.0,
            )
        )

    lines = [
        "# M3 补丁生成验收报告",
        "",
        f"- 生成时间：{datetime.now(timezone.utc).isoformat()}",
        f"- 判定对象：靶场注入点 Issue {len(issue_map)} 条",
        f"- 补丁通过前置校验：{patched}　被拒：{rejected}　生成失败：{generated_failed}",
        "",
        "| 编号 | 类别 | 补丁状态 | 变更行 | 强度 | 说明 |",
        "|---|---|---|---|---|---|",
    ]
    for expected, repro_state, status, message, changed, strength in rows:
        lines.append(
            f"| {expected['id']} | {expected['defect_class']} | {status} | {changed} | {strength:.2f} | {message} |"
        )
    lines.extend(
        [
            "",
            f"- 通过率：{patched}/{len(issue_map)}",
            "- 约束：≤30 行 / ≤3 文件；强度 <0.60 锁 L2；黑名单式过滤、无关注释/格式化/新增依赖一律拒绝",
            f"- 报告路径：{REPORT}",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines), encoding="utf-8")

    print(f"patched={patched} rejected={rejected} failed={generated_failed} total={len(issue_map)}")
    print(f"report={REPORT}")
    for expected, repro_state, status, message, changed, strength in rows:
        print(f"  {expected['id']} {status} lines={changed} strength={strength:.2f} {message}")
    if patched < 8:
        print("FAIL: fewer than 8 patches passed pre-checks")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())