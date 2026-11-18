from __future__ import annotations

import time
from dataclasses import dataclass

from app.api.envelope import ApiError, ErrorCode
from app.domain.enums import EventType, StepKind, StepStatus
from app.domain.models import Event, Issue, RunStep, utc_now
from app.orchestration.state_machine import (
    StateMachine,
    StateTransitionError,
    Transition,
    TransitionContext,
)
from app.ops.structured_log import StructuredLogger
from app.repo.memory import RecordNotFound
from app.repo.interfaces import EventStore, IssueStore, RunStore


@dataclass(frozen=True)
class TransitionOutcome:
    transition: Transition
    previous_status: str
    current_status: str
    event: Event


class OrchestrationService:
    def __init__(
        self,
        issues: IssueStore,
        runs: RunStore,
        events: EventStore,
        state_machine: StateMachine | None = None,
        logger: StructuredLogger | None = None,
    ):
        self.issues = issues
        self.runs = runs
        self.events = events
        self.state_machine = state_machine or StateMachine()
        self.logger = logger or StructuredLogger()

    def apply(self, transition: Transition, ctx: TransitionContext, event_type: EventType, actor: str) -> TransitionOutcome:
        issue: Issue = ctx.issue
        started = time.perf_counter()
        try:
            target = self.state_machine.target_status(issue.status, transition, ctx)
        except StateTransitionError as exc:
            self._log(issue, transition, "FAILED", started, reason=exc.reason)
            raise exc.to_api_error() from exc
        except ApiError as exc:
            self._log(issue, transition, "FAILED", started, reason=str(exc.detail))
            raise
        updated = issue.model_copy(update={"status": target, "updated_at": utc_now()})
        ctx.issue = updated
        self.issues.update(updated)
        run = self.runs.run_for_issue(updated.issue_id) if hasattr(self.runs, "run_for_issue") else None
        event = Event(
            event_id=f"{transition.value}-{updated.issue_id}",
            run_id=run.run_id if run else f"run-{updated.issue_id}",
            seq=1,
            event_type=event_type,
            actor=actor,
            step=self._step_for(event_type),
            payload_ref=ctx.reason or None,
        )
        sealed = self.events.append(event)
        if run is not None:
            step_status = StepStatus.FAILED if target.value.startswith("DISPOSED_L2") else StepStatus.DONE
            self.runs.append_step(
                run.run_id,
                RunStep(
                    kind=self._step_for(event_type),
                    status=step_status,
                    started_at=sealed.occurred_at,
                    ended_at=sealed.occurred_at,
                    evidence_ref=sealed.payload_ref,
                ),
            )
        self._log(issue, transition, "DONE", started, status=target.value, reason=ctx.reason, run_id=event.run_id)
        return TransitionOutcome(transition, issue.status.value, target.value, sealed)

    def _log(
        self,
        issue: Issue,
        transition: Transition,
        result: str,
        started: float,
        status: str = "",
        reason: str = "",
        run_id: str | None = None,
    ) -> None:
        try:
            self.logger.emit(
                run_id=run_id or f"run-{issue.issue_id}",
                issue_id=issue.issue_id,
                stage=transition.value,
                result=result,
                duration_ms=int((time.perf_counter() - started) * 1000),
                status=status,
                reason=reason,
            )
        except Exception:
            return

    @staticmethod
    def _step_for(event_type: EventType) -> StepKind:
        mapping = {
            EventType.INGEST: StepKind.INGEST,
            EventType.VERDICT: StepKind.VERDICT,
            EventType.PROOF: StepKind.PROOF,
            EventType.PATCH: StepKind.PATCH,
            EventType.AUDIT: StepKind.AUDIT,
            EventType.GATE: StepKind.GATE,
            EventType.DISPOSITION: StepKind.DISPOSITION,
            EventType.ROLLBACK: StepKind.DISPOSITION,
            EventType.CIRCUIT: StepKind.DISPOSITION,
            EventType.ALERT: StepKind.DISPOSITION,
            EventType.REDACTION: StepKind.DISPOSITION,
            EventType.CONTROL: StepKind.DISPOSITION,
        }
        return mapping[event_type]

    def fetch_issue(self, issue_id: str) -> Issue:
        try:
            return self.issues.get(issue_id)
        except RecordNotFound as exc:
            raise ApiError(ErrorCode.NOT_NORMALIZED, f"issue {issue_id} not found") from exc