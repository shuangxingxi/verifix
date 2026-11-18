from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.domain.enums import EventType, RunTerminalState, StepKind, StepStatus
from app.domain.models import Event, Run, RunStep
from app.repo.memory import MemoryStore, RecordNotFound


class ReplayStep(BaseModel):
    kind: StepKind
    status: StepStatus
    executed: bool
    started_at: datetime | None = None
    ended_at: datetime | None = None
    evidence_ref: str | None = None
    detail: str = ""


class ReplayEvent(BaseModel):
    seq: int
    event_type: EventType
    occurred_at: datetime
    actor: str
    step: StepKind | None = None
    payload_ref: str | None = None
    prev_hash: str = ""
    self_hash: str = ""


class RunReplay(BaseModel):
    run_id: str
    issue_id: str
    terminal_state: RunTerminalState | None = None
    started_at: datetime
    ended_at: datetime | None = None
    steps: list[ReplayStep]
    missing_steps: list[str]
    events: list[ReplayEvent]
    chain_valid: bool


class ReplayService:
    def __init__(self, store: MemoryStore):
        self.store = store

    def replay(self, run_id: str) -> RunReplay:
        try:
            run: Run = self.store.get_run(run_id)
        except RecordNotFound as exc:
            raise KeyError(run_id) from exc
        events: list[Event] = self.store.list_for_run(run_id)
        steps = [
            ReplayStep(
                kind=step.kind,
                status=step.status,
                executed=step.status is not StepStatus.NOT_RUN,
                started_at=step.started_at,
                ended_at=step.ended_at,
                evidence_ref=step.evidence_ref,
                detail=step.detail,
            )
            for step in run.steps
        ]
        return RunReplay(
            run_id=run.run_id,
            issue_id=run.issue_id,
            terminal_state=run.terminal_state,
            started_at=run.started_at,
            ended_at=run.ended_at,
            steps=steps,
            missing_steps=run.missing_steps(),
            events=[
                ReplayEvent(
                    seq=event.seq,
                    event_type=event.event_type,
                    occurred_at=event.occurred_at,
                    actor=event.actor,
                    step=event.step,
                    payload_ref=event.payload_ref,
                    prev_hash=event.prev_hash,
                    self_hash=event.self_hash,
                )
                for event in events
            ],
            chain_valid=self.store.verify_chain(run_id),
        )

    def mark_terminal(self, run_id: str, terminal: RunTerminalState) -> Run:
        return self.store.finish_run(run_id, terminal)