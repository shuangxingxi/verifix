from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.orchestration.guards import (
    ConcurrencyController,
    RetryPolicy,
    RunDeadlineGuard,
    RunTimeoutError,
)


class DeadlineGuardTest(unittest.TestCase):
    def test_rejects_non_positive_deadline(self) -> None:
        with self.assertRaises(ValueError):
            RunDeadlineGuard(0)
        with self.assertRaises(ValueError):
            RunDeadlineGuard(-1)

    def test_deadline_from_and_expiry_boundary(self) -> None:
        guard = RunDeadlineGuard(900)
        started = datetime(2026, 11, 14, 10, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(guard.deadline_from(started), started + timedelta(seconds=900))
        self.assertFalse(guard.is_expired(started, started + timedelta(seconds=899)))
        self.assertTrue(guard.is_expired(started, started + timedelta(seconds=900)))

    def test_remaining_seconds_is_clamped(self) -> None:
        guard = RunDeadlineGuard(900)
        started = datetime(2026, 11, 14, 10, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(guard.remaining_seconds(started, started + timedelta(seconds=100)), 800.0)
        self.assertEqual(guard.remaining_seconds(started, started + timedelta(seconds=1000)), 0.0)

    def test_ensure_alive_raises_after_deadline(self) -> None:
        guard = RunDeadlineGuard(60)
        started = datetime(2026, 11, 14, 10, 0, 0, tzinfo=timezone.utc)
        guard.ensure_alive("RUN-1", started, started + timedelta(seconds=59))
        with self.assertRaises(RunTimeoutError) as raised:
            guard.ensure_alive("RUN-1", started, started + timedelta(seconds=61))
        self.assertEqual(raised.exception.run_id, "RUN-1")
        self.assertEqual(raised.exception.deadline_seconds, 60)


class RetryPolicyTest(unittest.TestCase):
    def test_backoff_sequence_and_cap(self) -> None:
        policy = RetryPolicy(max_attempts=3, base_delay_seconds=1.0, max_delay_seconds=30.0)
        first = policy.decide(1)
        self.assertTrue(first.retry)
        self.assertEqual(first.attempt, 2)
        self.assertEqual(first.delay_seconds, 1.0)
        self.assertEqual(policy.decide(2).delay_seconds, 2.0)
        final = policy.decide(3)
        self.assertFalse(final.retry)
        self.assertEqual(final.attempt, 3)
        self.assertEqual(final.delay_seconds, 0.0)

    def test_delay_is_capped(self) -> None:
        policy = RetryPolicy(max_attempts=6, base_delay_seconds=10.0, max_delay_seconds=15.0)
        self.assertEqual(policy.decide(2).delay_seconds, 15.0)

    def test_rejects_invalid_max_attempts(self) -> None:
        with self.assertRaises(ValueError):
            RetryPolicy(max_attempts=0)


class ConcurrencyTest(unittest.IsolatedAsyncioTestCase):
    def test_rejects_invalid_concurrency(self) -> None:
        with self.assertRaises(ValueError):
            ConcurrencyController(0)
        with self.assertRaises(ValueError):
            ConcurrencyController(9)

    async def test_issue_lock_and_queued_count(self) -> None:
        controller = ConcurrencyController(2)
        async with controller.issue_lock("ISS-1"):
            self.assertEqual(controller.queued_issues(), 1)
        self.assertEqual(controller.queued_issues(), 0)

    async def test_file_lock_round_trip(self) -> None:
        controller = ConcurrencyController(2)
        async with controller.file_lock("repo", "app/main.py"):
            self.assertIn("repo:app/main.py", controller._file_locks)

    async def test_slot_accounting(self) -> None:
        controller = ConcurrencyController(3)
        self.assertEqual(controller.active_slots(), 0)
        async with controller.slot():
            self.assertEqual(controller.active_slots(), 1)
        self.assertEqual(controller.active_slots(), 0)

    async def test_reentrant_issue_lock_is_rejected(self) -> None:
        controller = ConcurrencyController(2)
        lock = await controller._lock_for(controller._issue_locks, "ISS-9")
        await lock.acquire()
        try:
            with self.assertRaises(RuntimeError):
                async with controller.issue_lock("ISS-9"):
                    pass
        finally:
            lock.release()

    async def test_reentrant_file_lock_is_rejected(self) -> None:
        controller = ConcurrencyController(2)
        lock = await controller._lock_for(controller._file_locks, "repo:a.py")
        await lock.acquire()
        try:
            with self.assertRaises(RuntimeError):
                async with controller.file_lock("repo", "a.py"):
                    pass
        finally:
            lock.release()


if __name__ == "__main__":
    unittest.main()