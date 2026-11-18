from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.envelope import ApiError, ErrorCode
from app.domain.enums import StageTier
from app.metrics.consistency import CrossReportConsistencyChecker
from app.metrics.history_guard import HistoryDigestGuard
from app.metrics.publisher import ReportPublisher, ReportVersionLock
from app.metrics.report import MetricReportService
from backend.tests.test_metrics_recalc import NOW, RecalcFixture

ROOT = Path(__file__).resolve().parents[2]


def base_row(**overrides) -> dict:
    row = {
        "metric_id": "M1",
        "value": 0.5,
        "computable": True,
        "unverified": False,
        "reason_code": None,
        "numerator": 15.0,
        "denominator": 30.0,
        "covered_count": 30,
        "excluded_count": 0,
        "channel_excluded_count": 1,
        "not_applicable_count": 0,
        "source_ref": "eval / definition=v2",
        "recalc_id": "RC-1",
        "snapshot_digest": "a" * 64,
        "eval_run_id": "EVALRUN-1",
        "definition_version": "v2",
        "met": True,
    }
    row.update(overrides)
    return row


class ConsistencyCheckerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.checker = CrossReportConsistencyChecker()

    def test_identical_rows_are_consistent(self) -> None:
        report = self.checker.compare([base_row()], [base_row()])
        self.assertTrue(report.consistent)

    def test_source_ref_whitespace_only_is_ignored(self) -> None:
        report = self.checker.compare([base_row()], [base_row(source_ref="  eval / definition=v2  ")])
        self.assertTrue(report.consistent)

    def test_recalc_id_difference_is_located(self) -> None:
        report = self.checker.compare([base_row()], [base_row(recalc_id="RC-2")])
        self.assertFalse(report.consistent)
        self.assertEqual(report.differences[0].field, "recalc_id")
        self.assertEqual(report.differences[0].metric_id, "M1")

    def test_float_tolerance(self) -> None:
        report = self.checker.compare([base_row(value=0.5)], [base_row(value=0.5 + 1e-12)])
        self.assertTrue(report.consistent)

    def test_unverified_flag_difference_detected(self) -> None:
        report = self.checker.compare([base_row(unverified=True)], [base_row(unverified=False)])
        self.assertFalse(report.consistent)


class PublisherTest(RecalcFixture):
    def setUp(self) -> None:
        super().setUp()
        self.recalc = self.service.recalc("2026-12", StageTier.PRELIMINARY, __import__("app.metrics.types", fromlist=["RecalcTrigger"]).RecalcTrigger.MANUAL, "tester")
        self.publish_dir = self.root / "publish"
        self.service = MetricReportService(self.store, report_dir=None, clock=lambda: NOW)
        self.publisher = ReportPublisher(self.service, self.publish_dir)

    def test_publish_writes_three_files(self) -> None:
        outcome = self.publisher.publish("2026-12", StageTier.PRELIMINARY, "tester", now=NOW)
        self.assertTrue(outcome.consistency.consistent)
        names = {path.name for path in self.publish_dir.iterdir() if path.is_file()}
        self.assertIn(f"{outcome.report_id}.md", names)
        self.assertIn(f"{outcome.report_id}.json", names)
        self.assertIn(f"consistency-{outcome.report_id}.json", names)

    def test_cross_report_mismatch_rejects_publish(self) -> None:
        tampered = [base_row(metric_id="M2", value=1.0)]
        with self.assertRaises(ApiError) as raised:
            self.publisher.publish(
                "2026-12", StageTier.PRELIMINARY, "tester", now=NOW, special_rows=tampered
            )
        self.assertIs(raised.exception.code, ErrorCode.REPORT_INCONSISTENT)
        self.assertFalse(self.publish_dir.exists() and any(self.publish_dir.iterdir()))

    def test_tampered_history_blocks_publish(self) -> None:
        target = self.root / "m5-eval-report.md"
        target.write_text("baseline", encoding="utf-8")
        guard = HistoryDigestGuard(
            target,
            baseline=f"{target}={'0' * 64}",
            evidence_dir=self.root / "history-evidence",
        )
        publisher = ReportPublisher(self.service, self.publish_dir, history_guard=guard)
        with self.assertRaises(ApiError) as raised:
            publisher.publish("2026-12", StageTier.PRELIMINARY, "tester", now=NOW)
        self.assertIs(raised.exception.code, ErrorCode.HISTORY_TAMPERED)

    def test_version_conflict_is_reported(self) -> None:
        lock = ReportVersionLock()
        lock.acquire("2026-12", StageTier.PRELIMINARY.value)
        publisher = ReportPublisher(self.service, self.publish_dir, lock=lock)
        with self.assertRaises(ApiError) as raised:
            publisher.publish("2026-12", StageTier.PRELIMINARY, "tester", now=NOW)
        self.assertIs(raised.exception.code, ErrorCode.REPORT_VERSION_CONFLICT)
        lock.release("2026-12", StageTier.PRELIMINARY.value)


class HistoryGuardIntegrationTest(unittest.TestCase):
    def test_guard_verifies_real_legacy_report(self) -> None:
        guard = HistoryDigestGuard(ROOT / "docs" / "devlog" / "m5-eval-report.md")
        self.assertEqual(guard.verify()[:12], "931d20442673")


if __name__ == "__main__":
    unittest.main()