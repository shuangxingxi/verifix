from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.intake.schedule import ScheduleTriggerInput, ScheduledTriggerService
from app.repo.memory import MemoryStore


class ScheduledTriggerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = MemoryStore()
        self.service = ScheduledTriggerService(self.store)

    def test_first_trigger_is_registered(self) -> None:
        outcome = self.service.register(ScheduleTriggerInput(repo="verifix-target", window="2026-11-11T17", idempotency_key="k1"))
        self.assertTrue(outcome.accepted)
        self.assertFalse(outcome.duplicate)
        self.assertTrue(outcome.run_id.startswith("RUN-TRIG-"))
        self.assertEqual(self.store.pending(), ["scan:verifix-target:2026-11-11T17"])

    def test_same_window_duplicate_is_ignored(self) -> None:
        payload = ScheduleTriggerInput(repo="verifix-target", window="2026-11-11T17", idempotency_key="k1")
        first = self.service.register(payload)
        second = self.service.register(payload)
        self.assertTrue(second.duplicate)
        self.assertEqual(first.run_id, second.run_id)
        self.assertEqual(len(self.store.pending()), 1)

    def test_new_window_registers_again(self) -> None:
        self.service.register(ScheduleTriggerInput(repo="verifix-target", window="2026-11-11T17", idempotency_key="k1"))
        second = self.service.register(ScheduleTriggerInput(repo="verifix-target", window="2026-11-11T18", idempotency_key="k2"))
        self.assertTrue(second.accepted)
        self.assertEqual(len(self.store.pending()), 2)

    def test_trigger_writes_ingest_event(self) -> None:
        outcome = self.service.register(ScheduleTriggerInput(repo="verifix-target", window="2026-11-11T17", idempotency_key="k1"))
        events = self.store.list_for_run(outcome.run_id)
        self.assertEqual(len(events), 1)
        self.assertTrue(self.store.verify_chain(outcome.run_id))


if __name__ == "__main__":
    unittest.main()