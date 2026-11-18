from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.api.envelope import ErrorCode
from app.config import load_config
from app.container import AppContainer
from app.domain.enums import StageTier
from app.main import create_app
from app.metrics.collectors.runtime_sampler import SelfRunSampleReader
from app.metrics.definitions import DefinitionRegistry, default_definitions
from app.metrics.types import RecalcTrigger
from backend.tests.test_metrics_recalc import NOW, seed_full_chain


class MetricsApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.tmp.name)
        base = load_config()
        metrics = base.metrics.model_copy(
            update={
                "snapshot_dir": str(root / "evidence"),
                "self_run_sample_path": str(root / "samples.jsonl"),
                "scheduler_enabled": False,
            }
        )
        self.config = base.model_copy(update={"metrics": metrics})
        reader = SelfRunSampleReader(root / "samples.jsonl")
        reader.append(
            {
                "sampled_at": (NOW - timedelta(seconds=10)).isoformat(),
                "continuous_seconds": 86400.0,
                "interruptions": 0,
                "heartbeat_ok": True,
            }
        )
        self.box = AppContainer(self.config)
        seed_full_chain(self.box.store)
        self.app = create_app(self.config, self.box)
        self.box.recalc_service.clock = lambda: NOW
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _post(self, *, trigger: str = "MANUAL", actor: str = "tester", window: str = "2026-12", headers: dict | None = None):
        payload = {"window": window, "tier": "PRELIMINARY", "trigger": trigger}
        merged = {"x-actor": actor} if actor else {}
        if headers:
            merged.update(headers)
        return self.client.post("/api/v1/metrics/recalc", json=payload, headers=merged)

    def test_manual_trigger_returns_recalc_id_and_metrics(self) -> None:
        response = self._post()
        self.assertEqual(response.status_code, 202, response.text)
        data = response.json()["data"]
        self.assertTrue(data["recalc_id"].startswith("RC-"))
        self.assertEqual(data["status"], "SUCCESS")
        self.assertEqual(data["trigger"], "MANUAL")
        self.assertEqual(data["actor"], "tester")
        self.assertEqual(len(data["metrics"]), 9)
        m4 = next(item for item in data["metrics"] if item["metric_id"] == "M4")
        self.assertEqual(m4["value"], 1.0)
        self.assertIsNotNone(m4["recalc_id"])

    def test_dashboard_trigger_uses_same_service(self) -> None:
        response = self._post(trigger="DASHBOARD")
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()["data"]["trigger"], "DASHBOARD")

    def test_get_recalc_status(self) -> None:
        created = self._post().json()["data"]
        response = self.client.get(f"/api/v1/metrics/recalc/{created['recalc_id']}")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["status"], "SUCCESS")
        self.assertEqual(len(data["metrics"]), 9)
        self.assertEqual(data["issue_total"], 1)

    def test_conflict_returns_409_vf7002(self) -> None:
        with self.box.recalc_guard.acquire("2026-12", StageTier.PRELIMINARY, "RC-ACTIVE"):
            response = self._post()
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()["code"], ErrorCode.RECALC_CONFLICT.value)
        self.assertIn("RC-ACTIVE", response.json()["message"])

    def test_missing_definition_returns_422_vf7004(self) -> None:
        partial = DefinitionRegistry([])
        for definition in default_definitions():
            partial.register(definition)
        self.box.recalc_service.definitions = DefinitionRegistry([])
        response = self._post()
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["code"], ErrorCode.DEFINITION_MISSING.value)

    def test_operator_token_required_when_configured(self) -> None:
        metrics = self.config.metrics.model_copy(update={"operator_token": "secret-token"})
        config = self.config.model_copy(update={"metrics": metrics})
        box = AppContainer(config)
        seed_full_chain(box.store)
        app = create_app(config, box)
        client = TestClient(app)
        missing = client.post(
            "/api/v1/metrics/recalc",
            json={"window": "2026-12", "tier": "PRELIMINARY", "trigger": "MANUAL"},
            headers={"x-actor": "tester"},
        )
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(missing.json()["code"], ErrorCode.UNAUTHORIZED.value)
        ok = client.post(
            "/api/v1/metrics/recalc",
            json={"window": "2026-12", "tier": "PRELIMINARY", "trigger": "MANUAL"},
            headers={"x-actor": "tester", "x-operator-token": "secret-token"},
        )
        self.assertEqual(ok.status_code, 202, ok.text)

    def test_actor_required(self) -> None:
        response = self._post(actor="")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], ErrorCode.UNAUTHORIZED.value)

    def test_service_failure_returns_500_vf7003(self) -> None:
        def boom(*args, **kwargs):
            raise RuntimeError("snapshot capture failed")

        self.box.recalc_service.builder.capture = boom  # type: ignore[assignment]
        response = self._post()
        self.assertEqual(response.status_code, 500, response.text)
        self.assertEqual(response.json()["code"], ErrorCode.RECALC_FAILED.value)

    def test_unknown_recalc_returns_evidence_missing(self) -> None:
        response = self.client.get("/api/v1/metrics/recalc/RC-MISSING")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["code"], ErrorCode.EVIDENCE_MISSING.value)

    def test_metrics_list_keeps_legacy_fields(self) -> None:
        legacy = self.box.store.metrics
        from app.domain.models import Metric
        from app.domain.enums import MetricId

        legacy[("M4", "PRELIMINARY", "2026-11")] = Metric(
            metric_id=MetricId.M4,
            stage_tier=StageTier.PRELIMINARY,
            window="2026-11",
            definition_version="v1",
            value=0.5,
            source_ref="legacy",
        )
        self._post()
        response = self.client.get("/api/v1/metrics")
        self.assertEqual(response.status_code, 200)
        rows = response.json()["data"]
        self.assertGreaterEqual(len(rows), 10)
        legacy_row = next(item for item in rows if item["window"] == "2026-11")
        self.assertEqual(legacy_row["value"], 0.5)
        self.assertEqual(legacy_row["definition_version"], "v1")
        new_row = next(item for item in rows if item["window"] == "2026-12")
        for field in ("metric_id", "stage_tier", "window", "value", "computable", "source_ref", "definition_version"):
            self.assertIn(field, new_row)


if __name__ == "__main__":
    unittest.main()