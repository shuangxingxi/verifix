from __future__ import annotations

import stat
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.dashboard.service import DashboardService
from app.domain.enums import (
    CircuitStatus,
    DefectClass,
    DispositionLevel,
    EventType,
    GateOutcome,
    IssueStatus,
    MetricId,
    Severity,
    StageTier,
    StepKind,
)
from app.domain.models import (
    CircuitState,
    Disposition,
    Event,
    Issue,
    Metric,
    Run,
    utc_now,
)
from app.evidence.store import EvidenceMissing, LocalEvidenceStore
from app.repo.memory import MemoryStore
from app.runtime.circuit import CircuitBreaker
from app.runtime.self_run import SelfRunTracker


def make_issue(store: MemoryStore, issue_id: str, status: IssueStatus) -> Issue:
    issue = Issue(
        issue_id=issue_id,
        repo="verifix-target",
        code_version="v1",
        defect_class=DefectClass.SQL_INJECTION,
        severity=Severity.HIGH,
        status=status,
        fingerprint=("f" * 63) + issue_id[-1],
    )
    return store.add(issue)


class EvidenceStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = LocalEvidenceStore(Path(self.tmp.name))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_put_read_verify(self) -> None:
        ref = self.store.put_locked("runs/RUN-1/ISS-1/proof/stdout.txt", b"hello", "text/plain")
        self.assertTrue(ref.locked)
        self.assertEqual(ref.size_bytes, 5)
        self.assertEqual(self.store.read(ref.key, ref.sha256), b"hello")
        self.assertTrue(self.store.verify(ref.key, ref.sha256).ok)

    def test_object_is_read_only(self) -> None:
        ref = self.store.put_locked("runs/RUN-2/ISS-2/proof/log.txt", b"locked")
        path = Path(self.tmp.name) / ref.key
        self.assertEqual(path.stat().st_mode & stat.S_IWRITE, 0)
        self.store.release(ref.key)

    def test_tamper_detected(self) -> None:
        ref = self.store.put_locked("runs/RUN-3/ISS-3/patch/diff.txt", b"original")
        path = Path(self.tmp.name) / ref.key
        self.store.release(ref.key)
        path.write_bytes(b"tampered")
        self.assertFalse(self.store.verify(ref.key, ref.sha256).ok)
        with self.assertRaises(EvidenceMissing):
            self.store.read(ref.key, ref.sha256)

    def test_missing_evidence(self) -> None:
        with self.assertRaises(EvidenceMissing):
            self.store.read("runs/RUN-X/ISS-X/proof/none.txt")

    def test_path_escape_rejected(self) -> None:
        with self.assertRaises(EvidenceMissing):
            self.store.put_locked("../outside.txt", b"x")


class DashboardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = MemoryStore()
        self.tracker = SelfRunTracker(clock=lambda: 10_000.0)
        self.tracker.heartbeat()
        self.breaker = CircuitBreaker(self.store)
        self.dashboard = DashboardService(self.store, self.tracker, self.breaker)

    def test_summary_counts(self) -> None:
        make_issue(self.store, "ISS-1", IssueStatus.TRIAGING)
        make_issue(self.store, "ISS-2", IssueStatus.ARCHIVED)
        make_issue(self.store, "ISS-3", IssueStatus.DISPOSED_L1)
        self.store.add_disposition(
            Disposition(
                disposition_id="D-3",
                issue_id="ISS-3",
                level=DispositionLevel.L1,
                action="open_pr",
                evidence_ref="obs://x",
                reason_code="GATE_PASSED",
                gate_outcome=GateOutcome.PASSED,
            )
        )
        summary = self.dashboard.summary()
        self.assertEqual(summary.in_progress, 1)
        self.assertEqual(summary.archived, 1)
        self.assertEqual(summary.level_distribution["L1"], 1)

    def test_circuit_and_pause_visible(self) -> None:
        for index in range(3):
            self.breaker.record_failure(DefectClass.SQL_INJECTION, f"fp-{index}")
        self.breaker.pause("lead", "maintenance")
        summary = self.dashboard.summary()
        self.assertIn("C02", summary.circuit_open_classes)
        self.assertTrue(summary.paused)
        self.assertEqual(summary.pause_reason, "maintenance")

    def test_metrics_and_events_increment(self) -> None:
        self.store.add_metric(
            Metric(
                metric_id=MetricId.M4,
                stage_tier=StageTier.PRELIMINARY,
                window="2026-12",
                definition_version="v1",
                value=0.7,
                source_ref="verdict",
            )
        )
        run = Run(run_id="RUN-1", issue_id="ISS-1", deadline_at=utc_now() + timedelta(minutes=15))
        self.store.add_run(run)
        self.store.append(Event(event_id="e1", run_id="RUN-1", seq=1, event_type=EventType.INGEST, actor="repo"))
        first = self.dashboard.all_events_since()
        self.assertEqual(len(first), 1)
        self.store.append(Event(event_id="e2", run_id="RUN-1", seq=2, event_type=EventType.VERDICT, actor="tracer"))
        second = self.dashboard.all_events_since()
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0].seq, 2)
        summary = self.dashboard.summary()
        self.assertEqual(summary.metrics[0]["metric_id"], "M4")

    def test_self_run_hours_reported(self) -> None:
        summary = self.dashboard.summary()
        self.assertGreaterEqual(summary.self_run_hours, 0.0)


if __name__ == "__main__":
    unittest.main()