from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.api.envelope import ErrorCode
from app.config import load_config
from app.container import AppContainer
from app.domain.enums import VerdictConclusion
from app.domain.models import Verdict
from app.main import create_app


class ApiM1Test(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config()
        self.box = AppContainer(self.config)
        self.client = TestClient(create_app(self.config, self.box))

    def test_scheduled_trigger_is_idempotent(self) -> None:
        payload = {"repo": "verifix-target", "window": "2026-11-11T17", "idempotency_key": "k1"}
        first = self.client.post("/api/v1/triggers/scheduled", json=payload)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.json()["code"], 0)
        self.assertFalse(first.json()["data"]["duplicate"])

        second = self.client.post("/api/v1/triggers/scheduled", json=payload)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(second.json()["code"], ErrorCode.IDEMPOTENT_HIT.value)
        self.assertTrue(second.json()["data"]["duplicate"])
        self.assertEqual(first.json()["data"]["run_id"], second.json()["data"]["run_id"])

    def test_scheduled_trigger_rejects_bad_window(self) -> None:
        response = self.client.post(
            "/api/v1/triggers/scheduled",
            json={"repo": "verifix-target", "window": "not-a-window", "idempotency_key": "k1"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], ErrorCode.NOT_NORMALIZED.value)

    def test_review_endpoint_creates_new_verdict(self) -> None:
        original = Verdict(
            verdict_id="V-api-1",
            issue_id="ISS-api-1",
            conclusion=VerdictConclusion.UNREACHABLE,
            confidence=0.8,
            basis="no propagation path",
            decided_by="tracer",
        )
        self.box.store.add_verdict(original)
        response = self.client.post(
            "/api/v1/verdicts/V-api-1/review",
            json={"actor": "security-lead", "reason": "dynamic entries not indexed", "conclusion": "SUSPECTED", "confidence": 0.5},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertNotEqual(data["verdict_id"], "V-api-1")
        self.assertEqual(data["conclusion"], "SUSPECTED")
        self.assertTrue(data["is_effective"])
        history = self.box.store.history("ISS-api-1")
        self.assertEqual(len(history), 2)
        self.assertFalse(history[0].is_effective)

    def test_review_missing_verdict_returns_evidence_missing(self) -> None:
        response = self.client.post(
            "/api/v1/verdicts/V-missing/review",
            json={"actor": "lead", "reason": "review"},
        )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["code"], ErrorCode.EVIDENCE_MISSING.value)


if __name__ == "__main__":
    unittest.main()