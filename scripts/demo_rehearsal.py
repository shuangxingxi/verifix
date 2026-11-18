from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient

from app.agents.critic.service import CriticService
from app.agents.patcher.service import PatcherService
from app.agents.reproducer.executor import LocalTestExecutor
from app.agents.reproducer.service import ReproducerService
from app.config import load_config
from app.container import AppContainer
from app.domain.enums import CircuitStatus, DefectClass
from app.intake.auth import AuthGuard
from app.main import create_app
from app.tracing.service import ReachabilityService

TARGET = ROOT / "verifix-target"
REPORT = ROOT / "docs" / "devlog" / "m4-demo-report.md"


def main() -> int:
    config = load_config()
    box = AppContainer(config)
    client = TestClient(create_app(config, box))
    guard = AuthGuard(secret=os.environ.get("VERIFIX_WEBHOOK_SECRET", "dev-secret"))
    checks: list[tuple[str, bool, str]] = []

    manual = client.post(
        "/api/v1/issues",
        json={
            "repo": "verifix-target",
            "code_version": "target-v1",
            "rule_id": "py/sql-injection",
            "severity": "HIGH",
            "file": "app/main.py",
            "line": 31,
            "defect_class": "C02",
            "snippet": "rows = conn.execute(\"SELECT id FROM users WHERE id = '%s'\" % uid)",
        },
    )
    manual_data = manual.json()["data"]
    checks.append(("入口1 人工提交", manual.status_code == 202 and bool(manual_data["issue_id"]), manual_data["issue_id"]))

    window = {"repo": "verifix-target", "window": "2026-11-11T22", "idempotency_key": "demo"}
    first = client.post("/api/v1/triggers/scheduled", json=window)
    second = client.post("/api/v1/triggers/scheduled", json=window)
    checks.append(
        (
            "入口2 定时扫描（幂等）",
            first.json()["code"] == 0 and second.json()["code"] == "VF-1003",
            f"{first.json()['data']['run_id']} / {second.json()['data']['run_id']}",
        )
    )

    webhook_body = json.dumps({"repo": "verifix-target", "branch": "verifix/demo", "base_sha": "abc"}).encode("utf-8")
    webhook = client.post(
        "/api/v1/webhooks/codearts-repo",
        content=webhook_body,
        headers={"content-type": "application/json", "x-codearts-signature": guard.sign(webhook_body)},
    )
    checks.append(("入口3 Repo Webhook", webhook.status_code == 202, webhook.json()["message"]))

    cve = client.post(
        "/api/v1/triggers/cve",
        json={
            "repo": "verifix-target",
            "code_version": "target-v1",
            "package": "requests",
            "current_version": "2.19.1",
            "fixed_version": "2.32.3",
            "severity": "HIGH",
        },
    )
    checks.append(("入口4 CVE 订阅", cve.status_code == 202 and bool(cve.json()["data"]["issue_id"]), cve.json()["message"]))

    runtime = client.post(
        "/api/v1/runtime/alerts",
        json={
            "repo": "verifix-target",
            "code_version": "target-v1",
            "rule_id": "py/command-injection",
            "file": "app/main.py",
            "line": 81,
            "severity": "HIGH",
            "evidence_ref": "runtime/demo",
        },
    )
    checks.append(("入口5 运行时告警", runtime.status_code == 202, runtime.json()["message"]))

    issue_id = manual_data["issue_id"]
    issue = box.store.get(issue_id)
    reachability = ReachabilityService(box.store, config, box.state_machine)
    reachability.analyze(issue, TARGET)
    reproducer = ReproducerService(box.store, LocalTestExecutor(), config)
    repro = reproducer.reproduce(box.store.get(issue_id), TARGET)
    patcher = PatcherService(box.store, config)
    patch_outcome = patcher.patch(box.store.get(issue_id), TARGET)
    critic = CriticService(box.store, config, LocalTestExecutor())
    critic_outcome = critic.evaluate(
        box.store.get(issue_id), patch_outcome.patch, patch_outcome.candidate, TARGET
    )
    checks.append(
        (
            "判定→复现→补丁→审计",
            repro.status.value == "PROVEN" and patch_outcome.status == "PATCHED" and critic_outcome.status == "PASSED",
            f"{repro.status.value}/{patch_outcome.status}/{critic_outcome.status}",
        )
    )

    run = box.store.run_for_issue(issue_id)
    replay = client.get(f"/api/v1/runs/{run.run_id}/replay").json()["data"]
    checks.append(
        (
            "回放七步",
            len(replay["steps"]) == 7 and len(replay["events"]) >= 3 and replay["chain_valid"],
            f"steps={len(replay['steps'])} events={len(replay['events'])} chain={replay['chain_valid']}",
        )
    )

    breaker = client.app.state.breaker
    for index in range(3):
        breaker.record_failure(DefectClass.SQL_INJECTION, f"demo-fp-{index}")
    decision = breaker.check(DefectClass.SQL_INJECTION, "demo-fp-new")
    circuit_open = decision.code == "VF-6001"
    reset = client.post("/api/v1/circuits/C02/reset", json={"actor": "lead", "reason": "demo"})
    circuit_reset = reset.json()["data"]["state"] == CircuitStatus.CLOSED.value
    checks.append(("熔断与解除", circuit_open and circuit_reset, f"{decision.code} -> {reset.json()['data']['state']}"))

    pause = client.post("/api/v1/control/pause", json={"actor": "lead", "reason": "demo"})
    queued = client.post(
        "/api/v1/issues",
        json={
            "repo": "verifix-target",
            "code_version": "target-v1",
            "rule_id": "py/sql-injection",
            "severity": "HIGH",
            "file": "app/main.py",
            "line": 50,
            "defect_class": "C02",
            "snippet": "search-demo",
        },
    )
    resume = client.post("/api/v1/control/resume")
    pause_ok = (
        pause.json()["data"]["paused"]
        and "QUEUED_BY_PAUSE" in queued.json()["message"]
        and not resume.json()["data"]["paused"]
    )
    checks.append(("暂停与恢复", pause_ok, queued.json()["message"]))

    summary = client.get("/api/v1/dashboard/summary").json()["data"]
    elements = {
        "在办数": "in_progress" in summary,
        "级别分布": "level_distribution" in summary,
        "熔断状态": "circuit_states" in summary,
        "连续自运行时": "self_run_hours" in summary,
        "失败原因 Top N": "failure_reasons" in summary,
        "指标": "metrics" in summary,
    }
    checks.append(("看板六类要素", all(elements.values()), ",".join(f"{k}={'有' if v else '无'}" for k, v in elements.items())))

    ok = all(passed for _, passed, _ in checks)
    lines = [
        "# M4 演示排练报告",
        "",
        f"- 生成时间：{datetime.now(timezone.utc).isoformat()}",
        "- 方式：进程内 TestClient + 真实服务链路（local-dev 执行器，无 Docker）",
        "",
        "| 检查项 | 结果 | 说明 |",
        "|---|---|---|",
    ]
    for name, passed, detail in checks:
        lines.append(f"| {name} | {'通过' if passed else '失败'} | {detail} |")
    lines.extend(["", f"结论：{'PASS' if ok else 'FAIL'}", "", f"报告路径：{REPORT}", ""])
    REPORT.write_text("\n".join(lines), encoding="utf-8")

    for name, passed, detail in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}: {detail}")
    print(f"report={REPORT}")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())