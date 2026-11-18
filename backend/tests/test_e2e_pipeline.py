from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.config import load_config
from app.container import AppContainer
from app.domain.enums import DefectClass, IssueStatus, Severity
from app.intake.auth import AuthGuard
from app.intake.service import IntakeService, ManualIssueInput
from app.main import create_app


def _manual_payload() -> dict:
    return {
        "repo": "verifix-target",
        "code_version": "abc123",
        "rule_id": "py/sql-injection",
        "severity": "HIGH",
        "file": "app/main.py",
        "line": 31,
        "defect_class": "C02",
        "snippet": "SELECT * FROM users WHERE id = '%s' % uid",
    }


def _intake_payload() -> ManualIssueInput:
    return ManualIssueInput(
        repo="verifix-target",
        code_version="abc123",
        rule_id="py/sql-injection",
        severity=Severity.HIGH,
        file="app/main.py",
        line=31,
        defect_class=DefectClass.SQL_INJECTION,
        snippet="SELECT * FROM users WHERE id = '%s' % uid",
    )


class FiveEntryPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config()
        self.box = AppContainer(self.config)
        self.client = TestClient(create_app(self.config, self.box))
        self.guard = AuthGuard(secret="dev-secret")
        self.store = self.box.store

    def _webhook(self, body: bytes, signature: str | None = None):
        headers = {"content-type": "application/json"}
        if signature is not None:
            headers["x-codearts-signature"] = signature
        return self.client.post("/api/v1/webhooks/codearts-repo", content=body, headers=headers)

    def test_five_entries_are_accepted(self) -> None:
        manual = self.client.post("/api/v1/issues", json=_manual_payload())
        self.assertLess(manual.status_code, 300, manual.text)

        body = json.dumps({"repo": "verifix-target", "branch": "verifix/ISS-1", "base_sha": "abc", "action": "merged"}).encode("utf-8")
        webhook = self._webhook(body, self.guard.sign(body))
        self.assertEqual(webhook.status_code, 202)

        cve = self.client.post(
            "/api/v1/triggers/cve",
            json={
                "repo": "verifix-target",
                "code_version": "v1",
                "package": "requests",
                "current_version": "2.19.1",
                "fixed_version": "2.20.0",
                "severity": "high",
            },
        )
        self.assertEqual(cve.status_code, 202)
        self.assertTrue(cve.json()["data"]["issue_id"].startswith("ISS-"))

        runtime = self.client.post(
            "/api/v1/runtime/alerts",
            json={
                "repo": "verifix-target",
                "code_version": "v1",
                "rule_id": "py/command-injection",
                "file": "app/main.py",
                "line": 81,
                "severity": "high",
                "snippet": "os.popen('ping ' + host)",
                "evidence_ref": "runtime:ev-1",
            },
        )
        self.assertEqual(runtime.status_code, 202)

        scheduled = self.client.post(
            "/api/v1/triggers/scheduled",
            json={"repo": "verifix-target", "window": "2026-11-14T16", "idempotency_key": "sched-1"},
        )
        self.assertEqual(scheduled.status_code, 202)
        self.assertFalse(scheduled.json()["data"]["duplicate"])

    def test_duplicate_webhook_replay_has_no_side_effects(self) -> None:
        body = json.dumps({"repo": "verifix-target", "branch": "verifix/ISS-1", "base_sha": "abc", "action": "merged"}).encode("utf-8")
        signature = self.guard.sign(body)
        issues_before = len(self.store.issues)
        pending_before = list(self.store.pending())
        first = self._webhook(body, signature)
        second = self._webhook(body, signature)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(first.json()["data"], second.json()["data"])
        self.assertEqual(len(self.store.issues), issues_before)
        self.assertEqual(list(self.store.pending()), pending_before)

    def test_scheduled_same_window_is_idempotent(self) -> None:
        payload = {"repo": "verifix-target", "window": "2026-11-14T16", "idempotency_key": "sched-2"}
        first = self.client.post("/api/v1/triggers/scheduled", json=payload)
        second = self.client.post("/api/v1/triggers/scheduled", json=payload)
        self.assertEqual(first.status_code, 202)
        self.assertFalse(first.json()["data"]["duplicate"])
        self.assertTrue(second.json()["data"]["duplicate"])
        self.assertEqual(first.json()["data"]["run_id"], second.json()["data"]["run_id"])

    def test_manual_retry_enqueues_without_state_regression(self) -> None:
        intake = IntakeService(self.store, self.config)
        submitted = intake.submit_manual(_intake_payload())
        status_before = self.store.get(submitted.issue_id).status
        response = self.client.post(f"/api/v1/issues/{submitted.issue_id}/retry", headers={"x-actor": "operator"})
        self.assertLess(response.status_code, 300, response.text)
        pending = self.store.pending()
        self.assertTrue(any(key.startswith(f"retry:{submitted.issue_id}") for key in pending), pending)
        self.assertIs(self.store.get(submitted.issue_id).status, status_before)
        self.assertIs(status_before, IssueStatus.RECEIVED)

    def test_outbox_resume_is_idempotent_and_keeps_evidence(self) -> None:
        intake = IntakeService(self.store, self.config)
        submitted = intake.submit_manual(_intake_payload())
        pending = self.store.pending()
        self.assertEqual(pending, [f"triage:{submitted.issue_id}"])
        self.store.mark_done(pending[0])
        self.store.mark_done(pending[0])
        self.assertEqual(self.store.pending(), [])
        events = self.store.list_for_run(submitted.run_id)
        self.assertGreaterEqual(len(events), 1)
        self.assertEqual(len(self.store.get_run(submitted.run_id).steps), 7)
        self.assertTrue(self.store.verify_chain(submitted.run_id))


if __name__ == "__main__":
    unittest.main()