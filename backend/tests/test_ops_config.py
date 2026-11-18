from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import AppConfig
from app.ops.config_change import (
    FROZEN_PATHS,
    TUNABLE_PATHS,
    FrozenConfigError,
    apply_changes,
)
from app.ops.structured_log import LOG_FIELDS, StructuredLogger
from app.repo.memory import MemoryStore
from app.runtime.control import ControlEventWriter


class StructuredLogTest(unittest.TestCase):
    def test_fixed_fields_and_duration(self) -> None:
        sink: list = []
        logger = StructuredLogger(sink=sink)
        record = logger.emit("RUN-1", "ISS-1", "TRIAGE", "DONE", 42)
        for field in LOG_FIELDS:
            self.assertIn(field, record)
        self.assertEqual(record["duration_ms"], 42)
        self.assertEqual(record["occurred_at"].count("+"), 1)
        self.assertEqual(len(sink), 1)

    def test_same_run_id_chains_stages(self) -> None:
        logger = StructuredLogger()
        logger.emit("RUN-2", "ISS-2", "TRIAGE", "DONE", 10)
        logger.emit("RUN-2", "ISS-2", "VERDICT", "DONE", 20)
        logger.emit("RUN-3", "ISS-3", "TRIAGE", "FAILED", 5)
        chain = logger.by_run("RUN-2")
        self.assertEqual([item["stage"] for item in chain], ["TRIAGE", "VERDICT"])
        self.assertEqual(len(logger.by_run("RUN-3")), 1)

    def test_sensitive_extra_is_redacted(self) -> None:
        logger = StructuredLogger()
        logger.emit("RUN-4", "ISS-4", "PATCH", "DONE", 7, password="supersecret123")
        record = logger.records()[0]
        self.assertEqual(record["password"], "***REDACTED***")
        self.assertTrue(record["redacted"])
        dumped = json.dumps(logger.text_lines(), ensure_ascii=False)
        self.assertNotIn("supersecret123", dumped)

    def test_invalid_fields_are_rejected(self) -> None:
        logger = StructuredLogger()
        with self.assertRaises(ValueError):
            logger.emit("", "ISS-1", "TRIAGE", "DONE", 1)
        with self.assertRaises(ValueError):
            logger.emit("RUN-1", "ISS-1", "TRIAGE", "UNKNOWN", 1)
        with self.assertRaises(ValueError):
            logger.emit("RUN-1", "ISS-1", "TRIAGE", "DONE", -1)


class ConfigChangeTest(unittest.TestCase):
    def test_frozen_change_without_exemption_is_rejected(self) -> None:
        config = AppConfig()
        with self.assertRaises(FrozenConfigError) as raised:
            apply_changes(config, {"patch.max_lines": 60}, "operator", "emergency")
        self.assertEqual(raised.exception.path, "patch.max_lines")
        self.assertEqual(config.patch.max_lines, 30)

    def test_frozen_change_with_exemption_is_recorded(self) -> None:
        config = AppConfig()
        store = MemoryStore()
        writer = ControlEventWriter(store)
        updated, records = apply_changes(
            config,
            {"release.auto_branch": "release/hotfix"},
            "release-lead",
            "热修窗口",
            writer=writer,
            exemption="EXC-2026-11-14-01",
        )
        self.assertEqual(updated.release.auto_branch, "release/hotfix")
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0].frozen)
        self.assertEqual(records[0].old_value, "release/auto")
        stored = writer.records()
        self.assertEqual(stored[0].action, "config_change")
        self.assertEqual(stored[0].scope, "release.auto_branch")
        self.assertIn("old=release/auto", stored[0].reason)
        self.assertIn("new=release/hotfix", stored[0].reason)
        self.assertIn("EXC-2026-11-14-01", stored[0].reason)

    def test_tunable_change_is_recorded(self) -> None:
        config = AppConfig()
        store = MemoryStore()
        writer = ControlEventWriter(store)
        updated, records = apply_changes(
            config, {"suspicion.threshold": 0.7}, "ops", "调参", writer=writer
        )
        self.assertEqual(updated.suspicion.threshold, 0.7)
        self.assertFalse(records[0].frozen)
        self.assertEqual(writer.records()[0].scope, "suspicion.threshold")

    def test_unknown_path_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            apply_changes(AppConfig(), {"model.unknown": 1}, "ops", "x")

    def test_frozen_paths_are_registered(self) -> None:
        self.assertEqual(len(FROZEN_PATHS), 5)
        self.assertEqual(len(TUNABLE_PATHS), 6)
        self.assertIn("branch.namespace", FROZEN_PATHS)
        self.assertIn("model.provider", TUNABLE_PATHS)


if __name__ == "__main__":
    unittest.main()