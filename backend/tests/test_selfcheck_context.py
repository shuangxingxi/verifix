from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.selfcheck.context import RunLock, SelfcheckContext
from app.selfcheck.models import (
    CheckSpec,
    Dimension,
    JudgmentMode,
    Status,
    ThreeQuestion,
    build_result,
)
from app.selfcheck.registry import CheckRegistry
from app.selfcheck.runner import SelfcheckRunner


class ContextFingerprintTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "README.md").write_text("# fixture\n", encoding="utf-8")
        self.ctx = SelfcheckContext(self.root)

    def test_fingerprint_is_stable_and_sensitive(self) -> None:
        first = self.ctx.fingerprint(["D1"], None)
        second = self.ctx.fingerprint(["D1"], None)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)
        (self.root / "README.md").write_text("# changed\n", encoding="utf-8")
        self.assertNotEqual(first, self.ctx.fingerprint(["D1"], None))

    def test_same_fingerprint_same_result(self) -> None:
        registry = CheckRegistry()
        for index in range(1, 4):
            spec = CheckSpec(
                check_id=f"D1-{index}",
                title="示例",
                dimension=Dimension.REPRODUCIBLE,
                mode=JudgmentMode.AUTO,
                question=ThreeQuestion.REPRODUCE,
                criterion="示例标准",
                handler=lambda ctx: build_result(
                    spec, Status.PASS, output_summary="通过"
                ),
            )
            registry.register(spec)
        first = SelfcheckRunner(self.ctx, registry).run(None)
        second = SelfcheckRunner(self.ctx, registry).run(None)
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual([item.status for item in first.checks], [item.status for item in second.checks])
        self.assertEqual(first.exit_code, second.exit_code)


class RunLockTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / ".lock"

    def test_acquire_and_release(self) -> None:
        first = RunLock(self.path)
        state = first.acquire({"pid": os.getpid(), "started_at": datetime.now(timezone.utc).isoformat()})
        self.assertTrue(state.acquired)
        self.assertTrue(self.path.is_file())
        second = RunLock(self.path)
        held = second.acquire({"pid": 2, "started_at": datetime.now(timezone.utc).isoformat()})
        self.assertFalse(held.acquired)
        self.assertEqual(held.reason, "HELD")
        first.release()
        self.assertFalse(self.path.exists())

    def test_stale_lock_is_taken_over(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stale = {
            "pid": 999999,
            "started_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        }
        self.path.write_text(json.dumps(stale), encoding="utf-8")
        lock = RunLock(self.path)
        state = lock.acquire({"pid": 12345})
        self.assertTrue(state.acquired)
        self.assertEqual(state.reason, "STALE_LOCK_TAKEN")
        lock.release()

    def test_old_timestamp_with_live_pid_is_taken_over(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stale = {
            "pid": 1,
            "started_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
        }
        self.path.write_text(json.dumps(stale), encoding="utf-8")
        lock = RunLock(self.path)
        state = lock.acquire({"pid": 2}, stale_seconds=60)
        self.assertTrue(state.acquired)
        lock.release()

    def test_no_infinite_retry(self) -> None:
        first = RunLock(self.path)
        first.acquire({"pid": os.getpid(), "started_at": datetime.now(timezone.utc).isoformat()})
        second = RunLock(self.path)
        state = second.acquire({"pid": 2, "started_at": datetime.now(timezone.utc).isoformat()})
        self.assertFalse(state.acquired)
        first.release()


if __name__ == "__main__":
    unittest.main()