from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_config
from app.container import AppContainer
from app.domain.enums import DefectClass, EventType, IssueStatus, RunTerminalState, Severity
from app.evidence.replay import ReplayService
from app.intake.service import IntakeService, ManualIssueInput, compute_fingerprint
from app.orchestration.state_machine import Transition, TransitionContext


def payload(**overrides) -> ManualIssueInput:
    base = dict(
        repo="verifix-target",
        code_version="abc123",
        rule_id="py/sql-injection",
        severity=Severity.HIGH,
        file="app/main.py",
        line=31,
        defect_class=DefectClass.SQL_INJECTION,
        snippet="SELECT * FROM users WHERE id = '%s' % uid",
    )
    base.update(overrides)
    return ManualIssueInput(**base)


class IntakeAndReplayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config()
        self.box = AppContainer(self.config)
        self.store = self.box.store
        self.intake = IntakeService(self.store, self.config)
        self.orchestration = self.box.orchestration()
        self.replay = ReplayService(self.store)

    def test_manual_submit_creates_run_with_seven_steps(self) -> None:
        result = self.intake.submit_manual(payload())
        self.assertEqual(result.status, IssueStatus.RECEIVED)
        self.assertFalse(result.idempotent)
        run = self.store.get_run(result.run_id)
        self.assertEqual(len(run.steps), 7)
        self.assertEqual(len(run.missing_steps()), 7)
        self.assertEqual(self.store.pending(), [f"triage:{result.issue_id}"])

    def test_duplicate_submit_is_idempotent(self) -> None:
        first = self.intake.submit_manual(payload())
        second = self.intake.submit_manual(payload())
        self.assertTrue(second.idempotent)
        self.assertEqual(first.issue_id, second.issue_id)
        self.assertEqual(len(self.store.issues), 1)

    def test_fingerprint_ignores_whitespace_but_not_code(self) -> None:
        from app.domain.models import Location

        loc = Location(file="app/main.py", line=31)
        a = compute_fingerprint("r", "v1", loc, "py/sql-injection", "x  =  1")
        b = compute_fingerprint("r", "v1", loc, "py/sql-injection", "x = 1")
        c = compute_fingerprint("r", "v1", loc, "py/sql-injection", "x = 2")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_out_of_scope_issue_has_no_class(self) -> None:
        result = self.intake.submit_manual(payload(defect_class=None, rule_id="py/path-traversal", line=7))
        self.assertFalse(result.in_scope)
        self.assertIsNone(self.store.get(result.issue_id).defect_class)

    def test_empty_run_reaches_l2_and_replays(self) -> None:
        submission = self.intake.submit_manual(payload())
        issue = self.store.get(submission.issue_id)
        self.orchestration.apply(Transition.T1, TransitionContext(issue=issue), EventType.INGEST, "normalizer")
        issue = self.store.get(submission.issue_id)
        self.orchestration.apply(
            Transition.T4,
            TransitionContext(issue=issue, reason="entry points unresolved"),
            EventType.VERDICT,
            "tracer",
        )
        issue = self.store.get(submission.issue_id)
        self.orchestration.apply(
            Transition.T17,
            TransitionContext(issue=issue, reason="no fix in empty run", actor="security-lead"),
            EventType.DISPOSITION,
            "security-lead",
        )
        self.store.finish_run(submission.run_id, RunTerminalState.FAILED)
        snapshot = self.replay.replay(submission.run_id)
        self.assertEqual(snapshot.terminal_state, RunTerminalState.FAILED)
        self.assertEqual(len(snapshot.events), 4)
        self.assertTrue(snapshot.chain_valid)
        self.assertEqual(len(snapshot.missing_steps), 4)
        self.assertEqual(self.store.get(submission.issue_id).status, IssueStatus.DISPOSED_L2)

    def test_replay_unknown_run_raises(self) -> None:
        with self.assertRaises(KeyError):
            self.replay.replay("RUN-missing")


if __name__ == "__main__":
    unittest.main()