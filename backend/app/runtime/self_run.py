from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

HEARTBEAT_TIMEOUT_SECONDS = 120
DEADLINE_SECONDS = 900


@dataclass(frozen=True)
class SelfRunSample:
    sampled_at: datetime
    continuous_seconds: float
    interruptions: int
    heartbeat_ok: bool
    tracker_started_at: datetime | None

    def to_dict(self) -> dict:
        return {
            "sampled_at": self.sampled_at.isoformat(),
            "continuous_seconds": self.continuous_seconds,
            "interruptions": self.interruptions,
            "heartbeat_ok": self.heartbeat_ok,
            "tracker_started_at": self.tracker_started_at.isoformat() if self.tracker_started_at else None,
        }


@dataclass
class SelfRunTracker:
    heartbeat_timeout_seconds: float = HEARTBEAT_TIMEOUT_SECONDS
    clock: Callable[[], float] = time.monotonic
    _started_at: float | None = None
    _last_heartbeat: float | None = None
    _interruptions: int = 0

    def heartbeat(self) -> None:
        now = self.clock()
        if self._last_heartbeat is None:
            self._started_at = now
        elif now - self._last_heartbeat > self.heartbeat_timeout_seconds:
            self._interruptions += 1
            self._started_at = now
        self._last_heartbeat = now

    def interrupt(self) -> None:
        self._interruptions += 1
        self._started_at = None
        self._last_heartbeat = None

    def is_healthy(self) -> bool:
        if self._last_heartbeat is None:
            return False
        return (self.clock() - self._last_heartbeat) <= self.heartbeat_timeout_seconds

    def continuous_seconds(self) -> float:
        if self._started_at is None or not self.is_healthy():
            return 0.0
        return max(0.0, self.clock() - self._started_at)

    def continuous_hours(self) -> float:
        return self.continuous_seconds() / 3600.0

    def interruptions(self) -> int:
        return self._interruptions

    def sample(self, now: datetime | None = None) -> SelfRunSample:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        healthy = self.is_healthy()
        seconds = self.continuous_seconds()
        started = (current - timedelta(seconds=seconds)) if healthy and seconds > 0 else None
        return SelfRunSample(
            sampled_at=current,
            continuous_seconds=seconds,
            interruptions=self._interruptions,
            heartbeat_ok=healthy,
            tracker_started_at=started,
        )


@dataclass(frozen=True)
class DeadlineVerdict:
    expired: bool
    remaining_seconds: float


def check_deadline(started_at: datetime, now: datetime | None = None, deadline_seconds: int = DEADLINE_SECONDS) -> DeadlineVerdict:
    current = now or datetime.now(timezone.utc)
    remaining = deadline_seconds - (current - started_at).total_seconds()
    return DeadlineVerdict(expired=remaining <= 0, remaining_seconds=max(0.0, remaining))


@dataclass
class WorkerSlot:
    name: str
    busy: bool = False
    current_task: str | None = None
    completed: int = 0


@dataclass
class ConcurrencyReport:
    slots: list[WorkerSlot] = field(default_factory=list)
    queued: int = 0


def build_slots(size: int) -> list[WorkerSlot]:
    return [WorkerSlot(name=f"worker-{index + 1}") for index in range(size)]