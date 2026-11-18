from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.domain.enums import RunTerminalState
from app.orchestration.guards import RunDeadlineGuard


@dataclass(frozen=True)
class DeadlineEnforcement:
    run_id: str
    expired: bool
    terminal_state: RunTerminalState | None
    evidence_refs: tuple[str, ...]
    released: bool


class RuntimeSupervisor:
    def __init__(self, store, deadline_guard: RunDeadlineGuard):
        self.store = store
        self.deadline_guard = deadline_guard

    def enforce_deadline(self, run_id: str, now: datetime | None = None) -> DeadlineEnforcement:
        run = self.store.get_run(run_id)
        current = now or datetime.now(timezone.utc)
        expired = self.deadline_guard.is_expired(run.started_at, current)
        if not expired:
            return DeadlineEnforcement(run_id, False, None, (), False)
        if run.terminal_state is not None:
            return DeadlineEnforcement(run_id, True, run.terminal_state, self._evidence(run_id), False)
        finished = self.store.finish_run(run_id, RunTerminalState.TIMEOUT)
        return DeadlineEnforcement(
            run_id=run_id,
            expired=True,
            terminal_state=finished.terminal_state,
            evidence_refs=self._evidence(run_id),
            released=True,
        )

    def _evidence(self, run_id: str) -> tuple[str, ...]:
        refs = [event.payload_ref for event in self.store.list_for_run(run_id) if event.payload_ref]
        return tuple(refs)