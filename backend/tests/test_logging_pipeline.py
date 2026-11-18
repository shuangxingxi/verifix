from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.envelope import ApiError
from app.domain.enums import DefectClass, EventType, IssueStatus, Severity
from app.domain.models import Issue
from app.ops.structured_log import StructuredLogger
from app.orchestration.service import OrchestrationService
from app.orchestration.state_machine import StateMachine, Transition, TransitionContext
from app.repo.memory import MemoryStore


def _issue(status: IssueStatus = IssueStatus.RECEIVED) -> Issue:
    return Issue(
        issue_id="ISS-LOG-1",
        repo="verifix-target",
        code_version="abc123",
        defect_class=DefectClass.SQL_INJECTION,
        severity=Severity.HIGH,
        status=status,
        fingerprint="f" * 64,
    )


class OrchestrationLoggingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = MemoryStore()
        self.logger = StructuredLogger()
        self.service = OrchestrationService(self.store, self.store, self.store, StateMachine(), self.logger)

    def test_success_transition_is_logged_with_run_id(self) -> None:
        issue = _issue()
        self.store.add(issue)
        outcome = self.service.apply(Transition.T1, TransitionContext(issue=issue), EventType.INGEST, "normalizer")
        records = self.logger.by_run(outcome.event.run_id)
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["run_id"], outcome.event.run_id)
        self.assertEqual(record["issue_id"], "ISS-LOG-1")
        self.assertEqual(record["stage"], "T1")
        self.assertEqual(record["result"], "DONE")
        self.assertEqual(record["status"], "TRIAGING")
        self.assertGreaterEqual(record["duration_ms"], 0)

    def test_failed_transition_is_logged_and_still_raises(self) -> None:
        issue = _issue(IssueStatus.TRIAGING)
        self.store.add(issue)
        with self.assertRaises(ApiError):
            self.service.apply(Transition.T2, TransitionContext(issue=issue), EventType.VERDICT, "tracer")
        records = self.logger.by_run("run-ISS-LOG-1")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["result"], "FAILED")
        self.assertEqual(records[0]["stage"], "T2")
        self.assertIn("Verdict required", records[0]["reason"])

    def test_reason_is_redacted_in_log(self) -> None:
        issue = _issue(IssueStatus.TRIAGING)
        self.store.add(issue)
        self.service.apply(
            Transition.T4,
            TransitionContext(issue=issue, reason="password=supersecret123"),
            EventType.VERDICT,
            "tracer",
        )
        record = self.logger.records()[0]
        self.assertEqual(record["reason"], "***REDACTED***")
        self.assertTrue(record["redacted"])

    def test_same_run_chains_multiple_stages(self) -> None:
        issue = _issue()
        self.store.add(issue)
        first = self.service.apply(Transition.T1, TransitionContext(issue=issue), EventType.INGEST, "normalizer")
        current = self.store.get("ISS-LOG-1")
        second = self.service.apply(
            Transition.T4,
            TransitionContext(issue=current, reason="低置信度"),
            EventType.VERDICT,
            "tracer",
        )
        self.assertEqual(first.event.run_id, second.event.run_id)
        stages = [item["stage"] for item in self.logger.by_run(first.event.run_id)]
        self.assertEqual(stages, ["T1", "T4"])

    def test_logger_failure_does_not_break_transition(self) -> None:
        class BrokenLogger(StructuredLogger):
            def emit(self, *args, **kwargs):
                raise RuntimeError("sink down")

        service = OrchestrationService(self.store, self.store, self.store, StateMachine(), BrokenLogger())
        issue = _issue()
        self.store.add(issue)
        outcome = service.apply(Transition.T1, TransitionContext(issue=issue), EventType.INGEST, "normalizer")
        self.assertEqual(outcome.current_status, "TRIAGING")


if __name__ == "__main__":
    unittest.main()