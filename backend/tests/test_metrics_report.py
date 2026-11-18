from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.enums import MetricId, StageTier
from app.metrics.report import MetricReportService, ReportInconsistent
from app.metrics.types import RecalcTrigger
from backend.tests.test_metrics_recalc import NOW, RecalcFixture


class ReportFixture(RecalcFixture):
    def setUp(self) -> None:
        super().setUp()
        self.report_dir = self.root / "reports"
        self.report_service = MetricReportService(self.store, report_dir=self.report_dir, clock=lambda: NOW)
        self.recalc = self.service.recalc("2026-12", StageTier.PRELIMINARY, RecalcTrigger.MANUAL, "tester")

    def record(self, metric_id: MetricId):
        return self.store.metrics[(metric_id.value, "PRELIMINARY", "2026-12")]

    def tamper(self, metric_id: MetricId, **changes):
        record = self.record(metric_id)
        self.store.metrics[(metric_id.value, "PRELIMINARY", "2026-12")] = record.model_copy(update=changes)


class ReportServiceTest(ReportFixture):
    def test_p13_generate_and_versions(self) -> None:
        first = self.report_service.generate("2026-12", StageTier.PRELIMINARY, "tester")
        self.assertEqual(first.record.version, 1)
        self.assertEqual(first.record.report_id, "RPT-2026-12-PRELIMINARY-0001")
        self.assertEqual(first.record.conclusion, "PASS", first.markdown)
        self.assertTrue((self.report_dir / f"{first.record.report_id}.md").is_file())
        second = self.report_service.generate("2026-12", StageTier.PRELIMINARY, "tester")
        self.assertEqual(second.record.version, 2)
        self.assertTrue((self.report_dir / f"{first.record.report_id}.md").is_file())
        self.assertIsNotNone(self.store.get_report(first.record.report_id))
        self.assertIsNotNone(self.store.get_report(second.record.report_id))

    def test_report_rows_cover_nine_metrics(self) -> None:
        outcome = self.report_service.generate("2026-12", StageTier.PRELIMINARY, "tester")
        self.assertEqual(len(outcome.rows), 9)
        for row in outcome.rows:
            self.assertIn("source_ref", row)
            self.assertIn("recalc_id", row)
            self.assertIn("snapshot_digest", row)
            self.assertIn("computed_at", row)
        m2 = next(row for row in outcome.rows if row["metric_id"] == "M2")
        self.assertFalse(m2["computable"])
        self.assertEqual(m2["reason_code"], "SOURCE_MISSING")
        self.assertNotIn("缺 Pipeline 日志", outcome.markdown)
        self.assertIn("| M2 漏洞检出率 | v2 | - |", outcome.markdown)
        self.assertNotIn("| M2 漏洞检出率 | v2 | 0", outcome.markdown)

    def test_n23_tampered_value_rejected(self) -> None:
        self.tamper(MetricId.M4, value=0.123)
        with self.assertRaises(ReportInconsistent) as ctx:
            self.report_service.generate("2026-12", StageTier.PRELIMINARY, "tester")
        self.assertTrue(any("不一致" in item for item in ctx.exception.issues))

    def test_n24_mixed_definition_versions_rejected(self) -> None:
        self.tamper(MetricId.M4, definition_version="v1")
        with self.assertRaises(ReportInconsistent) as ctx:
            self.report_service.generate("2026-12", StageTier.PRELIMINARY, "tester")
        self.assertTrue(any("混合定义版本" in item for item in ctx.exception.issues))

    def test_n25_missing_eval_identifier_removes_row(self) -> None:
        self.tamper(MetricId.M1, source_ref="未登记采集源")
        outcome = self.report_service.generate("2026-12", StageTier.PRELIMINARY, "tester")
        self.assertEqual(outcome.record.conclusion, "UNDETERMINED")
        self.assertNotIn("M1 有效告警率", outcome.markdown)
        m1 = next(row for row in outcome.rows if row["metric_id"] == "M1")
        self.assertFalse(m1["publishable"])

    def test_required_metric_uncomputable_is_undetermined(self) -> None:
        self.tamper(MetricId.M9, computable=False, value=None, reason_code="SOURCE_MISSING")
        outcome = self.report_service.generate("2026-12", StageTier.PRELIMINARY, "tester")
        self.assertEqual(outcome.record.conclusion, "UNDETERMINED")
        self.assertNotEqual(outcome.record.conclusion, "PASS")

    def test_report_is_read_only_on_metrics(self) -> None:
        before = self.store.metrics[(MetricId.M4.value, "PRELIMINARY", "2026-12")].model_dump()
        self.report_service.generate("2026-12", StageTier.PRELIMINARY, "tester")
        after = self.store.metrics[(MetricId.M4.value, "PRELIMINARY", "2026-12")].model_dump()
        self.assertEqual(before, after)

    def test_below_target_is_fail(self) -> None:
        self.tamper(MetricId.M4, value=0.2, numerator=2.0, covered_count=10)
        outcome = self.report_service.generate("2026-12", StageTier.PRELIMINARY, "tester")
        self.assertEqual(outcome.record.conclusion, "FAIL")

    def test_missing_record_rejected(self) -> None:
        del self.store.metrics[(MetricId.M6.value, "PRELIMINARY", "2026-12")]
        with self.assertRaises(ReportInconsistent):
            self.report_service.generate("2026-12", StageTier.PRELIMINARY, "tester")


class ExclusionRepositoryTest(ReportFixture):
    def test_exclusions_are_independent_and_readable(self) -> None:
        self.store.put_exclusions(
            self.recalc.recalc_id,
            MetricId.M4,
            [],
        )
        self.assertEqual(self.store.exclusions(self.recalc.recalc_id, MetricId.M4), [])
        runs = [run for run in self.store.recalc_runs.values() if run.status == "SUCCESS"]
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].issue_total, 1)


if __name__ == "__main__":
    unittest.main()