from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


class RunTimeoutError(Exception):
    def __init__(self, run_id: str, deadline_seconds: int):
        self.run_id = run_id
        self.deadline_seconds = deadline_seconds
        super().__init__(f"run {run_id} exceeded deadline of {deadline_seconds}s")


class RunDeadlineGuard:
    def __init__(self, deadline_seconds: int):
        if deadline_seconds <= 0:
            raise ValueError("deadline_seconds must be positive")
        self.deadline_seconds = deadline_seconds

    def deadline_from(self, started_at: datetime) -> datetime:
        return started_at + timedelta(seconds=self.deadline_seconds)

    def is_expired(self, started_at: datetime, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        return current >= self.deadline_from(started_at)

    def remaining_seconds(self, started_at: datetime, now: datetime | None = None) -> float:
        current = now or datetime.now(timezone.utc)
        return max(0.0, (self.deadline_from(started_at) - current).total_seconds())

    def ensure_alive(self, run_id: str, started_at: datetime, now: datetime | None = None) -> None:
        if self.is_expired(started_at, now):
            raise RunTimeoutError(run_id, self.deadline_seconds)


@dataclass(frozen=True)
class RetryDecision:
    retry: bool
    attempt: int
    delay_seconds: float


class RetryPolicy:
    def __init__(self, max_attempts: int = 3, base_delay_seconds: float = 1.0, max_delay_seconds: float = 30.0):
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self.max_attempts = max_attempts
        self.base_delay_seconds = base_delay_seconds
        self.max_delay_seconds = max_delay_seconds

    def decide(self, attempt: int) -> RetryDecision:
        if attempt >= self.max_attempts:
            return RetryDecision(False, attempt, 0.0)
        delay = min(self.base_delay_seconds * (2 ** max(0, attempt - 1)), self.max_delay_seconds)
        return RetryDecision(True, attempt + 1, delay)


class ConcurrencyController:
    def __init__(self, max_concurrency: int = 3):
        if not 1 <= max_concurrency <= 8:
            raise ValueError("max_concurrency must be within [1, 8]")
        self.max_concurrency = max_concurrency
        self._slots = asyncio.Semaphore(max_concurrency)
        self._issue_locks: dict[str, asyncio.Lock] = {}
        self._file_locks: dict[str, asyncio.Lock] = {}
        self._registry_guard = asyncio.Lock()

    async def _lock_for(self, registry: dict[str, asyncio.Lock], key: str) -> asyncio.Lock:
        async with self._registry_guard:
            lock = registry.get(key)
            if lock is None:
                lock = asyncio.Lock()
                registry[key] = lock
            return lock

    @asynccontextmanager
    async def issue_lock(self, issue_id: str):
        lock = await self._lock_for(self._issue_locks, issue_id)
        if lock.locked():
            raise RuntimeError(f"issue {issue_id} is already being processed")
        async with lock:
            yield

    @asynccontextmanager
    async def file_lock(self, repo: str, file_path: str):
        lock = await self._lock_for(self._file_locks, f"{repo}:{file_path}")
        if lock.locked():
            raise RuntimeError(f"file {file_path} in {repo} has a parallel task; queued")
        async with lock:
            yield

    @asynccontextmanager
    async def slot(self):
        async with self._slots:
            yield

    def active_slots(self) -> int:
        return self.max_concurrency - self._slots._value

    def queued_issues(self) -> int:
        return sum(1 for lock in self._issue_locks.values() if lock.locked())