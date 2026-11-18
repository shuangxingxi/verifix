from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.api.envelope import ErrorCode
from app.config import load_config
from app.container import AppContainer
from app.intake.auth import AuthGuard
from app.main import create_app


class ApiM4Test(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config()
        self.box = AppContainer(self.config)
        self.app = create_app(self.config, self.box)
        self.client = TestClient(self.app)
        self.guard = AuthGuard(secret="dev-secret")

    def _webhook(self, body: bytes, signature: str | None = None):
        headers = {"content-type": "application/json"}
        if signature is not None:
            headers["x-codearts-signature"] = signature
        return self.client.post("/api/v1/webhooks/codearts-repo", content=body, headers=headers)

    def test_webhook_signed_is_accepted(self) -> None:
        payload = {"repo": "verifix-target", "branch": "verifix/ISS-1", "base_sha": "abc", "action": "merged", "actor": "repo"}
        body = json.dumps(payload).encode("utf-8")
        response = self._webhook(body, self.guard.sign(body))
        self.assertEqual(response.status_code, 202)
        self.assertFalse(response.json()["data"]["skipped"])

    def test_webhook_main_branch_is_detect_only(self) -> None:
        payload = {"repo": "verifix-target", "branch": "main", "base_sha": "abc"}
        body = json.dumps(payload).encode("utf-8")
        response = self._webhook(body, self.guard.sign(body))
        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.json()["data"]["skipped"])
        self.assertIn("main", response.json()["data"]["reason"])

    def test_webhook_bad_signature_is_401(self) -> None:
        payload = {"repo": "verifix-target", "branch": "verifix/ISS-1", "base_sha": "abc"}
        body = json.dumps(payload).encode("utf-8")
        response = self._webhook(body, "not-a-signature")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], ErrorCode.UNAUTHORIZED.value)

    def test_webhook_missing_signature_is_401(self) -> None:
        body = json.dumps({"repo": "r", "branch": "verifix/x", "base_sha": "abc"}).encode("utf-8")
        response = self._webhook(body)
        self.assertEqual(response.status_code, 401)

    def test_cve_trigger_creates_issue(self) -> None:
        response = self.client.post(
            "/api/v1/triggers/cve",
            json={
                "repo": "verifix-target",
                "code_version": "v1",
                "package": "requests",
                "current_version": "2.19.1",
                "fixed_version": "2.32.3",
                "severity": "high",
            },
        )
        self.assertEqual(response.status_code, 202)
        body = response.json()
        self.assertTrue(body["data"]["issue_id"].startswith("ISS-"))
        self.assertEqual(body["data"]["outcome"], "CREATED")

    def test_runtime_alert_trigger(self) -> None:
        response = self.client.post(
            "/api/v1/runtime/alerts",
            json={
                "repo": "verifix-target",
                "code_version": "v1",
                "rule_id": "py/sql-injection",
                "file": "app/main.py",
                "line": 31,
                "severity": "high",
                "evidence_ref": "runtime/1",
            },
        )
        self.assertEqual(response.status_code, 202)
        self.assertIn("强证据", response.json()["message"])

    def test_heartbeat_and_dashboard(self) -> None:
        beat = self.client.post("/api/v1/heartbeat")
        self.assertEqual(beat.status_code, 200)
        self.assertTrue(beat.json()["data"]["healthy"])
        summary = self.client.get("/api/v1/dashboard/summary")
        self.assertEqual(summary.status_code, 200)
        data = summary.json()["data"]
        self.assertIn("in_progress", data)
        self.assertIn("level_distribution", data)
        self.assertIn("metrics", data)

    def test_pause_resume_and_circuit_reset(self) -> None:
        paused = self.client.post("/api/v1/control/pause", json={"actor": "lead", "reason": "maintenance"})
        self.assertTrue(paused.json()["data"]["paused"])
        summary = self.client.get("/api/v1/dashboard/summary").json()["data"]
        self.assertTrue(summary["paused"])
        resumed = self.client.post("/api/v1/control/resume")
        self.assertFalse(resumed.json()["data"]["paused"])
        reset = self.client.post("/api/v1/circuits/C02/reset", json={"actor": "lead", "reason": "clear"})
        self.assertEqual(reset.status_code, 200)
        self.assertEqual(reset.json()["data"]["state"], "CLOSED")

    def test_invalid_defect_class_reset_rejected(self) -> None:
        response = self.client.post("/api/v1/circuits/C99/reset", json={"actor": "lead", "reason": "x"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], ErrorCode.NOT_NORMALIZED.value)

    def test_pause_queues_new_issue_without_dropping(self) -> None:
        self.client.post("/api/v1/control/pause", json={"actor": "lead", "reason": "maintenance"})
        response = self.client.post(
            "/api/v1/issues",
            json={
                "repo": "verifix-target",
                "code_version": "v1",
                "rule_id": "py/sql-injection",
                "severity": "HIGH",
                "file": "app/main.py",
                "line": 31,
                "defect_class": "C02",
                "snippet": "x",
            },
        )
        self.assertEqual(response.status_code, 202)
        self.assertIn("QUEUED_BY_PAUSE", response.json()["message"])
        pending = self.box.store.pending()
        self.assertTrue(any(key.startswith("triage:") for key in pending))
        self.client.post("/api/v1/control/resume")

    def test_sse_stream_emits_heartbeat(self) -> None:
        submitted = self.client.post("/api/v1/issues", json={
            "repo": "verifix-target",
            "code_version": "v1",
            "rule_id": "py/sql-injection",
            "severity": "HIGH",
            "file": "app/main.py",
            "line": 31,
            "defect_class": "C02",
            "snippet": "x",
        })
        response = self.client.get("/api/v1/events/stream?since=0&iterations=1&interval=0")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        self.assertIn(": heartbeat", response.text)


if __name__ == "__main__":
    unittest.main()