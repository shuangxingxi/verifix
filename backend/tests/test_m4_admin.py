from __future__ import annotations

import os
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.api.envelope import ErrorCode
from app.config import load_config
from app.container import AppContainer
from app.domain.enums import DispositionLevel, IssueStatus, MetricId, RunTerminalState, Severity, StageTier
from app.domain.models import Disposition, Issue, Metric, Run, utc_now
from app.main import create_app


class ApiM4AdminTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        os.environ["VERIFIX_EVIDENCE_ROOT"] = self.tmp.name
        self.config = load_config()
        self.box = AppContainer(self.config)
        self.client = TestClient(create_app(self.config, self.box))
        self.evidence = self.client.app.state.evidence

    def tearDown(self) -> None:
        os.environ.pop("VERIFIX_EVIDENCE_ROOT", None)
        self.tmp.cleanup()

    def submit(self) -> str:
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
        return response.json()["data"]["issue_id"]

    def test_list_and_detail_and_retry(self) -> None:
        issue_id = self.submit()
        listing = self.client.get("/api/v1/issues").json()["data"]
        self.assertEqual(len(listing), 1)
        detail = self.client.get(f"/api/v1/issues/{issue_id}").json()["data"]
        self.assertEqual(detail["issue"]["issue_id"], issue_id)
        self.assertEqual(len(detail["alerts"]), 1)
        retry = self.client.post(f"/api/v1/issues/{issue_id}/retry")
        self.assertEqual(retry.status_code, 202)
        self.assertTrue(retry.json()["data"]["queued"])

    def test_handoff_writes_control_event(self) -> None:
        issue_id = self.submit()
        response = self.client.post(
            f"/api/v1/issues/{issue_id}/handoff",
            json={"actor": "security-lead", "reason": "needs manual review"},
        )
        self.assertEqual(response.status_code, 202)
        events = self.client.get("/api/v1/control/events").json()["data"]
        self.assertTrue(any(item["action"] == "handoff" for item in events))
        self.assertTrue(any(item["actor"] == "security-lead" for item in events))

    def test_pause_and_reset_write_control_events(self) -> None:
        self.client.post("/api/v1/control/pause", json={"actor": "lead", "reason": "maintenance"})
        self.client.post("/api/v1/circuits/C02/reset", json={"actor": "lead", "reason": "clear"})
        self.client.post("/api/v1/control/resume")
        events = self.client.get("/api/v1/control/events").json()["data"]
        actions = {item["action"] for item in events}
        self.assertTrue({"pause", "reset_circuit", "resume"} <= actions)

    def test_disposition_evidence_ok_then_missing(self) -> None:
        issue_id = self.submit()
        ref = self.evidence.put_locked(f"runs/RUN-1/{issue_id}/proof/log.txt", b"ok")
        self.box.store.add_disposition(
            Disposition(
                disposition_id=f"D-{issue_id}",
                issue_id=issue_id,
                level=DispositionLevel.L2,
                action="report_only",
                evidence_ref=f"{ref.key}#sha256={ref.sha256}",
                reason_code="AUDIT_REJECTED",
            )
        )
        ok = self.client.get(f"/api/v1/issues/{issue_id}/disposition")
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(ok.json()["data"]["conclusion_trusted"])

        self.evidence.release(ref.key)
        (Path(self.tmp.name) / ref.key).write_bytes(b"tampered")
        missing = self.client.get(f"/api/v1/issues/{issue_id}/disposition")
        self.assertEqual(missing.status_code, 500)
        self.assertEqual(missing.json()["code"], ErrorCode.EVIDENCE_MISSING.value)

    def test_missing_disposition_returns_error(self) -> None:
        issue_id = self.submit()
        response = self.client.get(f"/api/v1/issues/{issue_id}/disposition")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["code"], ErrorCode.EVIDENCE_MISSING.value)

    def test_metrics_list(self) -> None:
        self.box.store.add_metric(
            Metric(
                metric_id=MetricId.M5,
                stage_tier=StageTier.PRELIMINARY,
                window="2026-12",
                definition_version="v1",
                value=0.62,
                source_ref="verdict",
            )
        )
        data = self.client.get("/api/v1/metrics").json()["data"]
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["metric_id"], "M5")

    def test_run_deadline_expires_and_keeps_evidence(self) -> None:
        issue = self.box.store.add(
            Issue(
                issue_id="ISS-OLD",
                repo="r",
                code_version="v1",
                defect_class=None,
                severity=Severity.LOW,
                status=IssueStatus.ARCHIVED,
                fingerprint="a" * 64,
                in_scope=False,
            )
        )
        run = Run(
            run_id="RUN-OLD",
            issue_id=issue.issue_id,
            started_at=utc_now() - timedelta(seconds=1000),
            deadline_at=utc_now() - timedelta(seconds=100),
        )
        self.box.store.add_run(run)
        from app.domain.enums import EventType

        from app.domain.models import Event

        self.box.store.append(Event(event_id="e-old", run_id="RUN-OLD", seq=1, event_type=EventType.INGEST, actor="repo", payload_ref="issue/ISS-OLD"))
        data = self.client.get("/api/v1/runs/RUN-OLD/deadline").json()["data"]
        self.assertTrue(data["expired"])
        self.assertEqual(data["terminal_state"], RunTerminalState.TIMEOUT.value)
        self.assertTrue(data["evidence_refs"])


if __name__ == "__main__":
    unittest.main()