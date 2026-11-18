from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.envelope import ApiError, ErrorCode
from app.domain.enums import (
    DefectClass,
    EventType,
    IssueStatus,
    RunTerminalState,
    Severity,
    StepKind,
    StepStatus,
)
from app.domain.models import Event, Issue, Run, RunStep, utc_now
from app.orchestration.service import OrchestrationService
from app.orchestration.state_machine import Transition, TransitionContext
from app.repo.memory import AppendOnlyViolation, MemoryStore


def make_issue() -> Issue:
    return Issue(
        issue_id="ISS-900",
        repo="verifix-target",
        code_version="abc123",
        defect_class=DefectClass.SQL_INJECTION,
        severity=Severity.HIGH,
        fingerprint="9" * 64,
    )


class RepoTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = MemoryStore()

    def test_fingerprint_uniqueness(self) -> None:
        issue = make_issue()
        stored = self.store.add(issue)
        duplicate = self.store.add(issue.model_copy(update={"issue_id": "ISS-901"}))
        self.assertEqual(stored.issue_id, duplicate.issue_id)
        self.assertEqual(len(self.store.issues), 1)

    def test_event_chain_and_append_only(self) -> None:
        run = Run(run_id="run-1", issue_id="ISS-900", deadline_at=utc_now() + timedelta(minutes=15))
        self.store.add_run(run)
        first = self.store.append(Event(event_id="e1", run_id="run-1", seq=99, event_type=EventType.INGEST, actor="repo"))
        second = self.store.append(Event(event_id="e2", run_id="run-1", seq=99, event_type=EventType.VERDICT, actor="tracer"))
        self.assertEqual(first.seq, 1)
        self.assertEqual(second.seq, 2)
        self.assertEqual(second.prev_hash, first.self_hash)
        self.assertTrue(self.store.verify_chain("run-1"))
        with self.assertRaises(AppendOnlyViolation):
            self.store.forbid_mutation("run-1")

    def test_tampered_chain_detected(self) -> None:
        run = Run(run_id="run-2", issue_id="ISS-900", deadline_at=utc_now() + timedelta(minutes=15))
        self.store.add_run(run)
        self.store.append(Event(event_id="e1", run_id="run-2", seq=1, event_type=EventType.INGEST, actor="repo"))
        self.store.events["run-2"][0] = self.store.events["run-2"][0].model_copy(update={"actor": "tampered"})
        self.assertFalse(self.store.verify_chain("run-2"))

    def test_transaction_rolls_back(self) -> None:
        issue = make_issue()
        self.store.add(issue)
        with self.assertRaises(RuntimeError):
            with self.store.transaction():
                self.store.update(issue.model_copy(update={"status": IssueStatus.GATING}))
                raise RuntimeError("boom")
        self.assertIs(self.store.get("ISS-900").status, IssueStatus.RECEIVED)

    def test_outbox_flow(self) -> None:
        self.store.enqueue("k1", "publish_branch", "obs://payload/1")
        self.assertEqual(self.store.pending(), ["k1"])
        self.store.mark_done("k1")
        self.assertEqual(self.store.pending(), [])


class OrchestrationServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = MemoryStore()
        self.service = OrchestrationService(self.store, self.store, self.store)
        self.issue = self.store.add(make_issue())
        self.run = self.store.add_run(
            Run(
                run_id="run-900",
                issue_id="ISS-900",
                deadline_at=utc_now() + timedelta(minutes=15),
                steps=[RunStep(kind=kind, status=StepStatus.NOT_RUN) for kind in StepKind],
            )
        )

    def test_transition_and_event_are_atomic(self) -> None:
        ctx = TransitionContext(issue=self.store.get("ISS-900"))
        outcome = self.service.apply(Transition.T1, ctx, EventType.INGEST, "repo-webhook")
        self.assertEqual(outcome.current_status, "TRIAGING")
        self.assertEqual(self.store.get("ISS-900").status, IssueStatus.TRIAGING)
        events = self.store.list_for_run("run-900")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, EventType.INGEST)

    def test_guard_failure_keeps_state(self) -> None:
        ctx = TransitionContext(issue=self.store.get("ISS-900"))
        with self.assertRaises(ApiError) as raised:
            self.service.apply(Transition.T6, ctx, EventType.PROOF, "reproducer")
        self.assertIs(raised.exception.code, ErrorCode.NO_VERDICT)
        self.assertIs(self.store.get("ISS-900").status, IssueStatus.RECEIVED)
        self.assertEqual(self.store.list_for_run("run-900"), [])

    def test_missing_step_marked_not_run(self) -> None:
        missing = self.store.get_run("run-900").missing_steps()
        self.assertEqual(len(missing), len(StepKind))

    def test_finish_run_records_terminal_state(self) -> None:
        finished = self.store.finish_run("run-900", RunTerminalState.TIMEOUT)
        self.assertIs(finished.terminal_state, RunTerminalState.TIMEOUT)
        self.assertIsNotNone(finished.ended_at)


class RunDeadlineGuardTest(unittest.TestCase):
    def test_deadline_and_timeout(self) -> None:
        from app.orchestration.guards import RetryPolicy, RunDeadlineGuard, RunTimeoutError

        guard = RunDeadlineGuard(900)
        started = datetime.now(timezone.utc)
        self.assertFalse(guard.is_expired(started))
        self.assertAlmostEqual(guard.remaining_seconds(started), 900, delta=5)
        with self.assertRaises(RunTimeoutError):
            guard.ensure_alive("run-900", started - timedelta(seconds=901))

        policy = RetryPolicy(max_attempts=3, base_delay_seconds=1.0)
        self.assertTrue(policy.decide(1).retry)
        self.assertEqual(policy.decide(1).delay_seconds, 1.0)
        self.assertEqual(policy.decide(2).delay_seconds, 2.0)
        self.assertFalse(policy.decide(3).retry)


if __name__ == "__main__":
    unittest.main()