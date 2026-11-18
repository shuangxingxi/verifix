from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from app.config import load_config
from app.container import AppContainer
from app.domain.enums import DefectClass, EventType, IssueStatus, RunTerminalState, Severity
from app.evidence.replay import ReplayService
from app.intake.service import IntakeService, ManualIssueInput
from app.orchestration.state_machine import Transition, TransitionContext


def main() -> int:
    config = load_config()
    box = AppContainer(config)
    store = box.store
    orchestration = box.orchestration()
    replay = ReplayService(store)

    intake = IntakeService(store, config)
    submission = intake.submit_manual(
        ManualIssueInput(
            repo="verifix-target",
            code_version="smoke-m0",
            rule_id="py/sql-injection",
            severity=Severity.HIGH,
            file="app/main.py",
            line=31,
            defect_class=DefectClass.SQL_INJECTION,
            snippet="rows = conn.execute(\"SELECT id, name FROM users WHERE id = '%s'\" % uid)",
        )
    )
    print(f"[smoke] submitted issue={submission.issue_id} run={submission.run_id} status={submission.status.value}")

    issue = store.get(submission.issue_id)
    orchestration.apply(Transition.T1, TransitionContext(issue=issue), EventType.INGEST, "event-normalizer")

    issue = store.get(submission.issue_id)
    orchestration.apply(
        Transition.T4,
        TransitionContext(issue=issue, reason="entry points unresolved in empty run"),
        EventType.VERDICT,
        "tracer",
    )

    issue = store.get(submission.issue_id)
    orchestration.apply(
        Transition.T17,
        TransitionContext(issue=issue, reason="smoke run keeps no fix", actor="security-lead"),
        EventType.DISPOSITION,
        "security-lead",
    )

    store.finish_run(submission.run_id, RunTerminalState.FAILED)
    snapshot = replay.replay(submission.run_id)
    print(f"[smoke] terminal={snapshot.terminal_state.value if snapshot.terminal_state else None}")
    print(f"[smoke] steps={[f'{step.kind.value}:{step.status.value}' for step in snapshot.steps]}")
    print(f"[smoke] missing={snapshot.missing_steps}")
    print(f"[smoke] events={[(event.seq, event.event_type.value, event.actor) for event in snapshot.events]}")
    print(f"[smoke] chain_valid={snapshot.chain_valid}")
    print(f"[smoke] outbox_pending={store.pending()}")

    final_issue = store.get(submission.issue_id)
    if final_issue.status is not IssueStatus.DISPOSED_L2:
        print(f"[smoke] FAIL expected DISPOSED_L2, got {final_issue.status.value}")
        return 1
    if len(snapshot.events) != 4 or not snapshot.chain_valid:
        print("[smoke] FAIL event chain incomplete or broken")
        return 1
    if len(snapshot.missing_steps) != 4:
        print(f"[smoke] FAIL expected 4 not-run steps, got {snapshot.missing_steps}")
        return 1
    print("[smoke] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())