from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.api.envelope import ErrorCode
from app.config import load_config
from app.main import create_app


def payload(**overrides) -> dict:
    base = {
        "repo": "verifix-target",
        "code_version": "abc123",
        "rule_id": "py/sql-injection",
        "severity": "HIGH",
        "file": "app/main.py",
        "line": 31,
        "defect_class": "C02",
        "snippet": "SELECT * FROM users WHERE id = '%s' % uid",
    }
    base.update(overrides)
    return base


class IssueApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config()
        self.app = create_app(self.config)
        self.client = TestClient(self.app)

    def test_submit_issue_returns_202_and_run(self) -> None:
        response = self.client.post("/api/v1/issues", json=payload(), headers={"x-actor": "tester"})
        self.assertEqual(response.status_code, 202)
        body = response.json()
        self.assertEqual(body["code"], 0)
        self.assertTrue(body["data"]["issue_id"].startswith("ISS-"))
        self.assertTrue(body["data"]["run_id"].startswith("RUN-"))
        self.assertEqual(body["data"]["status"], "RECEIVED")
        self.assertFalse(body["data"]["idempotent"])

    def test_duplicate_submit_returns_idempotent_code(self) -> None:
        first = self.client.post("/api/v1/issues", json=payload()).json()
        second = self.client.post("/api/v1/issues", json=payload()).json()
        self.assertEqual(second["code"], ErrorCode.IDEMPOTENT_HIT.value)
        self.assertEqual(first["data"]["issue_id"], second["data"]["issue_id"])
        self.assertTrue(second["data"]["idempotent"])

    def test_out_of_scope_issue_marked(self) -> None:
        body = self.client.post("/api/v1/issues", json=payload(defect_class=None, rule_id="py/path-traversal")).json()
        self.assertEqual(body["code"], ErrorCode.OUT_OF_SCOPE.value)
        self.assertFalse(body["data"]["in_scope"])

    def test_invalid_payload_uses_unified_envelope(self) -> None:
        response = self.client.post("/api/v1/issues", json={"repo": ""})
        self.assertEqual(response.status_code, 422)
        body = response.json()
        self.assertEqual(body["code"], ErrorCode.NOT_NORMALIZED.value)
        self.assertIn("trace_id", body)

    def test_replay_returns_seven_steps(self) -> None:
        accepted = self.client.post("/api/v1/issues", json=payload()).json()["data"]
        replay = self.client.get(f"/api/v1/runs/{accepted['run_id']}/replay")
        self.assertEqual(replay.status_code, 200)
        data = replay.json()["data"]
        self.assertEqual(len(data["steps"]), 7)
        self.assertEqual(len(data["missing_steps"]), 7)
        self.assertTrue(data["chain_valid"])
        self.assertEqual(len(data["events"]), 1)

    def test_replay_unknown_run_uses_evidence_missing(self) -> None:
        response = self.client.get("/api/v1/runs/RUN-missing/replay")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["code"], ErrorCode.EVIDENCE_MISSING.value)


if __name__ == "__main__":
    unittest.main()