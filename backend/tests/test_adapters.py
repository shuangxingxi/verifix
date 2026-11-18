from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.check import FIELD_MAP as CHECK_FIELD_MAP
from app.adapters.check import CheckAdapter, RecordedCheckClient
from app.adapters.governance import RecordedGovernanceClient
from app.adapters.governance import GovernanceAdapter
from app.adapters.types import RepoRef, ScanTaskRef
from app.domain.enums import Severity


CHECK_RECORD = {
    "alertId": "check:task-1:1",
    "ruleId": "py/sql-injection",
    "filePath": "app/user.py",
    "startLine": 42,
    "severity": "high",
    "codeSnippet": "SELECT * FROM users WHERE id = '%s' % uid",
}

GOV_RECORD = {
    "findingId": "gov:1",
    "packageName": "requests",
    "currentVersion": "2.19.1",
    "introducedVersion": "2.0.0",
    "fixedVersion": "2.20.0",
    "severity": "medium",
}


class CheckAdapterTest(unittest.TestCase):
    def test_maps_contract_fields(self) -> None:
        client = RecordedCheckClient(alerts=[CHECK_RECORD])
        adapter = CheckAdapter(client, sleeper=lambda _: None)
        result = adapter.fetch_alerts(ScanTaskRef("task-1"))
        self.assertFalse(result.degraded)
        self.assertEqual(len(result.alerts), 1)
        alert = result.alerts[0]
        self.assertEqual(alert.rule_id, "py/sql-injection")
        self.assertEqual(alert.file_path, "app/user.py")
        self.assertEqual(alert.line, 42)
        self.assertIs(alert.severity, Severity.HIGH)

    def test_field_rename_only_touches_mapping_table(self) -> None:
        renamed = dict(CHECK_FIELD_MAP)
        renamed["rule_id"] = "rule_id_v2"
        renamed["file_path"] = "file_path_v2"
        record = {
            "alertId": "check:2",
            "rule_id_v2": "py/command-injection",
            "file_path_v2": "app/main.py",
            "startLine": 81,
            "severity": "critical",
        }
        adapter = CheckAdapter(RecordedCheckClient(alerts=[record]), field_map=renamed, sleeper=lambda _: None)
        result = adapter.fetch_alerts(ScanTaskRef("task-2"))
        self.assertEqual(result.alerts[0].rule_id, "py/command-injection")
        self.assertEqual(result.alerts[0].file_path, "app/main.py")
        self.assertIs(result.alerts[0].severity, Severity.CRITICAL)

    def test_failure_keeps_last_known_good_and_marks_degraded(self) -> None:
        client = RecordedCheckClient(alerts=[CHECK_RECORD])
        adapter = CheckAdapter(client, sleeper=lambda _: None)
        first = adapter.fetch_alerts(ScanTaskRef("task-1"))
        self.assertEqual(len(first.alerts), 1)
        client.fail = True
        second = adapter.fetch_alerts(ScanTaskRef("task-1"))
        self.assertTrue(second.degraded)
        self.assertIn("数据源不可用（Check）", second.message)
        self.assertEqual(len(second.alerts), 1)
        self.assertIsNotNone(second.alerts[0])

    def test_retry_attempts_are_bounded(self) -> None:
        client = RecordedCheckClient(fail=True)
        adapter = CheckAdapter(client, max_attempts=3, sleeper=lambda _: None)
        result = adapter.fetch_alerts(ScanTaskRef("task-3"))
        self.assertTrue(result.degraded)
        self.assertEqual(client.calls, 3)


class GovernanceAdapterTest(unittest.TestCase):
    def test_empty_result_is_distinguishable_from_failure(self) -> None:
        adapter = GovernanceAdapter(RecordedGovernanceClient(findings=[]), sleeper=lambda _: None)
        empty = adapter.fetch_dependency_findings(RepoRef("verifix-target", "abc"))
        self.assertTrue(empty.available)
        self.assertTrue(empty.empty)
        self.assertEqual(empty.findings, [])

        failing = GovernanceAdapter(RecordedGovernanceClient(fail=True), max_attempts=2, sleeper=lambda _: None)
        failed = failing.fetch_dependency_findings(RepoRef("verifix-target", "abc"))
        self.assertFalse(failed.available)
        self.assertFalse(failed.empty)
        self.assertIn("数据源不可用（Governance）", failed.message)

    def test_maps_dependency_fields(self) -> None:
        adapter = GovernanceAdapter(RecordedGovernanceClient(findings=[GOV_RECORD]), sleeper=lambda _: None)
        result = adapter.fetch_dependency_findings(RepoRef("verifix-target", "abc"))
        finding = result.findings[0]
        self.assertEqual(finding.package, "requests")
        self.assertEqual(finding.current_version, "2.19.1")
        self.assertEqual(finding.fixed_version, "2.20.0")
        self.assertIs(finding.severity, Severity.MEDIUM)


if __name__ == "__main__":
    unittest.main()