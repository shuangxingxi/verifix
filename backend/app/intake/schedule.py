from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from pydantic import BaseModel, Field

from app.domain.enums import EventType
from app.domain.models import Event, Run, utc_now
from app.intake.dedup import InMemorySetNx, SetNxPort


class ScheduleTriggerInput(BaseModel):
    repo: str = Field(min_length=1)
    window: str = Field(min_length=1, pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}$")
    idempotency_key: str = Field(min_length=1)
    base_sha: str = "HEAD"


@dataclass(frozen=True)
class ScheduleOutcome:
    accepted: bool
    duplicate: bool
    run_id: str
    window: str


class ScheduledTriggerService:
    def __init__(self, store, setnx: SetNxPort | None = None, ttl_seconds: int = 3600):
        self.store = store
        self.setnx = setnx or InMemorySetNx()
        self.ttl_seconds = ttl_seconds
        self._registrations: dict[str, str] = {}

    def register(self, payload: ScheduleTriggerInput, actor: str = "scheduler") -> ScheduleOutcome:
        key = f"schedule:{payload.repo}:{payload.window}:{payload.idempotency_key}"
        existing = self._registrations.get(key)
        if existing is not None:
            return ScheduleOutcome(accepted=False, duplicate=True, run_id=existing, window=payload.window)
        if not self.setnx.set_if_absent(key, self.ttl_seconds):
            return ScheduleOutcome(
                accepted=False,
                duplicate=True,
                run_id=self._registrations.get(key, ""),
                window=payload.window,
            )

        run_id = f"RUN-TRIG-{uuid.uuid4().hex[:12]}"
        now = utc_now()
        run = Run(
            run_id=run_id,
            issue_id="SYS-SCHEDULE",
            started_at=now,
            deadline_at=now + timedelta(seconds=60),
            steps=[],
        )
        with self.store.transaction():
            self.store.add_run(run)
            self.store.append(
                Event(
                    event_id=f"TRIGGER-{run_id}",
                    run_id=run_id,
                    seq=1,
                    event_type=EventType.INGEST,
                    actor=actor,
                    payload_ref=f"schedule/{payload.window}",
                )
            )
            self.store.enqueue(f"scan:{payload.repo}:{payload.window}", "scheduled_scan", f"repo/{payload.repo}")
        self._registrations[key] = run_id
        return ScheduleOutcome(accepted=True, duplicate=False, run_id=run_id, window=payload.window)