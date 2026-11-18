from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.types import RawAlert
from app.config import load_config
from app.domain.enums import DefectClass, MetricChannel, MetricId, Severity, SourceKind
from app.domain.models import Issue
from app.intake.dedup import DedupService, InMemorySetNx
from app.intake.normalizer import IssueNormalizer
from app.metrics.calculator import MetricCalculator
from app.metrics.isolation import ChannelResolver
from app.repo.memory import MemoryStore


def make_issue(issue_id: str, code_version: str = "abc123", channel: MetricChannel | None = None) -> Issue:
    payload = {
        "issue_id": issue_id,
        "repo": "verifix-target",
        "code_version": code_version,
        "defect_class": DefectClass.SQL_INJECTION,
        "severity": Severity.HIGH,
        "fingerprint": ("f" * 63) + issue_id[-1],
    }
    if channel is not None:
        payload["channel"] = channel
    return Issue(**payload)


class ChannelResolverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = ChannelResolver()

    def test_explicit_channel_wins(self) -> None:
        resolution = self.resolver.resolve(make_issue("ISS-1", channel=MetricChannel.EVAL))
        self.assertIs(resolution.channel, MetricChannel.EVAL)
        self.assertEqual(resolution.basis, "explicit")
        self.assertFalse(resolution.legacy)

    def test_rk12_explicit_main_with_eval_prefix_is_kept(self) -> None:
        resolution = self.resolver.resolve(make_issue("ISS-2", code_version="eval-main-version", channel=MetricChannel.MAIN))
        self.assertIs(resolution.channel, MetricChannel.MAIN)
        self.assertEqual(resolution.basis, "explicit")

    def test_legacy_prefix_fallback_marked_legacy(self) -> None:
        resolution = self.resolver.resolve(make_issue("ISS-3", code_version="eval-0001"))
        self.assertIs(resolution.channel, MetricChannel.EVAL)
        self.assertEqual(resolution.basis, "legacy_prefix")
        self.assertTrue(resolution.legacy)

    def test_default_is_main(self) -> None:
        resolution = self.resolver.resolve(make_issue("ISS-4"))
        self.assertIs(resolution.channel, MetricChannel.MAIN)
        self.assertEqual(resolution.basis, "default")

    def test_p09_three_eval_records_excluded(self) -> None:
        issues = [
            make_issue("ISS-1", channel=MetricChannel.MAIN),
            make_issue("ISS-2", channel=MetricChannel.EVAL),
            make_issue("ISS-3", channel=MetricChannel.EVAL),
            make_issue("ISS-4", channel=MetricChannel.EVAL),
        ]
        summary = self.resolver.summarize(issues)
        self.assertEqual(summary.kept, ["ISS-1"])
        self.assertEqual(summary.channel_excluded_count, 3)

    def test_n03_unknown_counted_as_exclusion_entry(self) -> None:
        issues = [make_issue("ISS-5", channel=MetricChannel.UNKNOWN)]
        summary = self.resolver.summarize(issues)
        self.assertEqual(summary.channel_excluded_count, 0)
        self.assertEqual(len(summary.exclusion_entries()), 1)
        self.assertEqual(summary.exclusion_entries()[0].detail, "通道不可判")


class CalculatorChannelCompatibilityTest(unittest.TestCase):
    def test_legacy_prefix_issue_excluded_as_before(self) -> None:
        store = MemoryStore()
        store.add(make_issue("ISS-1", code_version="eval-0001"))
        store.add(make_issue("ISS-2", code_version="abc123"))
        metrics = MetricCalculator(store).calculate()
        m8 = [item for item in metrics if item.metric_id is MetricId.M8][0]
        self.assertEqual(m8.source_ref, "disposition ÷ issue")
        self.assertEqual(len(MetricCalculator(store)._in_scope_issues()), 1)

    def test_explicit_main_with_eval_prefix_included(self) -> None:
        store = MemoryStore()
        store.add(make_issue("ISS-3", code_version="eval-0003", channel=MetricChannel.MAIN))
        self.assertEqual(len(MetricCalculator(store)._in_scope_issues()), 1)


class IntakeChannelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config()
        self.store = MemoryStore()
        self.normalizer = IssueNormalizer(self.store, DedupService(self.store, InMemorySetNx()), self.config)

    def _alert(self) -> RawAlert:
        return RawAlert(
            alert_ref="check:ISS-1",
            source_kind=SourceKind.CHECK,
            rule_id="py/sql-injection",
            file_path="app/main.py",
            line=31,
            severity=Severity.HIGH,
            snippet="c.execute(query)",
        )

    def test_main_channel_is_explicit(self) -> None:
        result = self.normalizer.ingest_alert(self._alert(), "verifix-target", "abc123")
        issue = self.store.get(result.issue_id)
        self.assertIs(issue.channel, MetricChannel.MAIN)
        self.assertIn("channel", issue.model_fields_set)

    def test_eval_channel_marked_and_excluded(self) -> None:
        result = self.normalizer.ingest_alert(
            self._alert(), "verifix-target", "eval-EVAL-0001", channel=MetricChannel.EVAL
        )
        issue = self.store.get(result.issue_id)
        resolution = ChannelResolver().resolve(issue)
        self.assertIs(resolution.channel, MetricChannel.EVAL)
        self.assertFalse(resolution.legacy)


if __name__ == "__main__":
    unittest.main()