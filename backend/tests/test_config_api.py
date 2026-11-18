from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.config import load_config
from app.container import AppContainer
from app.main import create_app


class ConfigChangeApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config()
        self.box = AppContainer(self.config)
        self.client = TestClient(create_app(self.config, self.box))

    def _post(self, payload: dict):
        return self.client.post("/api/v1/control/config", json=payload)

    def test_tunable_change_is_recorded_and_visible(self) -> None:
        response = self._post(
            {"changes": {"suspicion.threshold": 0.7}, "actor": "ops-lead", "reason": "降低误判"}
        )
        self.assertEqual(response.status_code, 202, response.text)
        body = response.json()
        self.assertEqual(body["code"], 0)
        record = body["data"]["records"][0]
        self.assertEqual(record["path"], "suspicion.threshold")
        self.assertEqual(record["old_value"], 0.6)
        self.assertEqual(record["new_value"], 0.7)
        self.assertEqual(record["actor"], "ops-lead")
        self.assertFalse(record["frozen"])
        self.assertFalse(body["data"]["applied"])
        self.assertEqual(body["data"]["effective_after"], "restart")

        events = self.client.get("/api/v1/control/events").json()["data"]
        self.assertTrue(
            any(item["action"] == "config_change" and item["scope"] == "suspicion.threshold" for item in events),
            events,
        )

    def test_frozen_change_without_exemption_is_rejected(self) -> None:
        response = self._post({"changes": {"patch.max_lines": 60}, "actor": "ops", "reason": "紧急"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "VF-1005")
        self.assertEqual(self.box.config.patch.max_lines, 30)

    def test_frozen_change_with_exemption_is_recorded(self) -> None:
        response = self._post(
            {
                "changes": {"release.auto_branch": "release/hotfix"},
                "actor": "release-lead",
                "reason": "热修窗口",
                "exemption": "EXC-2026-11-14-09",
            }
        )
        self.assertEqual(response.status_code, 202, response.text)
        record = response.json()["data"]["records"][0]
        self.assertTrue(record["frozen"])
        self.assertEqual(record["exemption"], "EXC-2026-11-14-09")
        events = self.client.get("/api/v1/control/events").json()["data"]
        self.assertTrue(
            any("EXC-2026-11-14-09" in item["reason"] for item in events),
            events,
        )

    def test_unknown_path_is_rejected(self) -> None:
        response = self._post({"changes": {"model.unknown": 1}, "actor": "ops", "reason": "x"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "VF-1006")

    def test_empty_changes_are_rejected(self) -> None:
        response = self._post({"changes": {}, "actor": "ops", "reason": "x"})
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()