from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.domain.enums import EventType
from app.domain.models import Event, utc_now

CONTROL_RUN_ID = "RUN-CONTROL"
CONTROL_ACTOR_MAX = 64


@dataclass(frozen=True)
class ControlRecord:
    action: str
    actor: str
    reason: str
    scope: str
    occurred_at: datetime


class ControlEventWriter:
    def __init__(self, store):
        self.store = store

    def write(self, action: str, actor: str, reason: str, scope: str) -> Event:
        event = Event(
            event_id=f"CONTROL-{action}-{int(utc_now().timestamp() * 1000)}",
            run_id=CONTROL_RUN_ID,
            seq=1,
            event_type=EventType.CONTROL,
            occurred_at=utc_now(),
            actor=actor[:CONTROL_ACTOR_MAX],
            payload_ref=f"{action}|{scope}|{reason}",
        )
        return self.store.append(event)

    def recent(self, limit: int = 50) -> list[Event]:
        events = self.store.list_for_run(CONTROL_RUN_ID)
        return events[-limit:]

    def records(self, limit: int = 50) -> list[ControlRecord]:
        records: list[ControlRecord] = []
        for event in self.recent(limit):
            parts = (event.payload_ref or "").split("|")
            action = parts[0] if parts else ""
            scope = parts[1] if len(parts) > 1 else ""
            reason = "|".join(parts[2:]) if len(parts) > 2 else ""
            records.append(
                ControlRecord(
                    action=action,
                    actor=event.actor,
                    reason=reason,
                    scope=scope,
                    occurred_at=event.occurred_at,
                )
            )
        return records