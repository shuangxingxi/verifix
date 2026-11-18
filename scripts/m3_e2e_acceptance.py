from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.adapters.check import CheckAdapter, RecordedCheckClient
from app.adapters.pipeline import RecordedPipelineClient
from app.adapters.repo import LocalRepoAdapter
from app.adapters.types import ScanTaskRef
from app.agents.critic.service import CriticService
from app.agents.gatekeeper.service import GatekeeperService
from app.agents.patcher.service import PatcherService
from app.agents.reproducer.executor import LocalTestExecutor
from app.agents.reproducer.service import ReproducerService, ReproductionStatus
from app.config import load_config
from app.intake.dedup import DedupService, InMemorySetNx
from app.intake.normalizer import IntakeOutcome, IssueNormalizer
from app.repo.memory import MemoryStore
from app.tracing.service import ReachabilityService

TARGET = ROOT / "verifix-target"
REPORT = ROOT / "docs" / "devlog" / "m3-e2e-report.md"
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
        ScanTaskRef("m3-e2e")
    )

    issue_map: dict[str, dict] = {}
    for alert in fetched.alerts:
        outcome = normalizer.ingest_alert(alert, "verifix-target", "target-v1")
        if outcome.outcome is IntakeOutcome.CREATED and outcome.issue_id:
            issue_map[outcome.issue_id] = expectations[alert.alert_ref]

    reachability = ReachabilityService(store, config)
    reproducer = ReproducerService(store, LocalTestExecutor(), config)
    patcher = PatcherService(store, config)
    critic_agent = CriticService(store, config, LocalTestExecutor())
    repo = LocalRepoAdapter()
    repo.load_from_directory(TARGET)
    pipeline = RecordedPipelineClient.all_passed()
    gatekeeper = GatekeeperService(store, config, repo, pipeline)

    rows = []
    levels: dict[str, int] = {}
    fixed = 0
    for index, (issue_id, expected) in enumerate(issue_map.items(), start=1):
        reachability.analyze(store.get(issue_id), TARGET)
        repro = reproducer.reproduce(store.get(issue_id), TARGET)
        if repro.status is not ReproductionStatus.PROVEN:
            rows.append((expected, repro.status.value, repro.status.value, "-", repro.message))
            levels["REPRO_FAILED"] = levels.get("REPRO_FAILED", 0) + 1
            continue
        patch_outcome = patcher.patch(store.get(issue_id), TARGET)
        if patch_outcome.status != "PATCHED":
            rows.append((expected, repro.status.value, patch_outcome.status, "-", patch_outcome.message))
            levels[patch_outcome.status] = levels.get(patch_outcome.status, 0) + 1
            continue
        issue = store.get(issue_id)
        patch = patch_outcome.patch
        candidate = patch_outcome.candidate
        assert patch is not None and candidate is not None
        critic = critic_agent.evaluate(issue, patch, candidate, TARGET)
        if repo.branch_base.get(patch.branch) is None:
            repo.base_files = dict(repo.base_files)
        outcome = gatekeeper.dispose(issue, patch, repro.proof, candidate, critic, f"run-{index}")
        levels[outcome.status] = levels.get(outcome.status, 0) + 1
        if outcome.status == "L1":
            fixed += 1
        rows.append(
            (
                expected,
                repro.status.value,
                f"{critic.status}->{outcome.status}",
                patch.patch_strength,
                outcome.message,
            )
        )

    lines = [
        "# M3 端到端修复验收报告",
        "",
        f"- 生成时间：{datetime.now(timezone.utc).isoformat()}",
        f"- 执行后端：local-dev（无 Docker；沙箱路径未验证）",
        f"- 判定对象：靶场注入点 Issue {len(issue_map)} 条",
        f"- 分级分布：{levels}",
        f"- 一次修好（L1）：{fixed}",
        "",
        "| 编号 | 类别 | 复现 | 审计→处置 | 强度 | 说明 |",
        "|---|---|---|---|---|---|",
    ]
    for expected, repro_state, status, strength, message in rows:
        lines.append(
            f"| {expected['id']} | {expected['defect_class']} | {repro_state} | {status} | {strength} | {message} |"
        )
    lines.extend(
        [
            "",
            f"- 一次修好率：{fixed}/{len(issue_map)}（验收门槛 ≥4/6）",
            f"- 报告路径：{REPORT}",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines), encoding="utf-8")

    print(f"levels={levels} fixed={fixed}/{len(issue_map)}")
    print(f"report={REPORT}")
    for expected, repro_state, status, strength, message in rows:
        print(f"  {expected['id']} {repro_state} {status} {message}")
    if fixed < 4:
        print("FAIL: end-to-end fix below 4/6")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())