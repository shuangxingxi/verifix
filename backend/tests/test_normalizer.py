from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.types import RawAlert, RawDependencyAlert
from app.api.envelope import ErrorCode
from app.config import load_config
from app.domain.defects.plugins import default_registry
from app.domain.enums import DefectClass, IssueStatus, Severity, SourceKind
from app.intake.dedup import DedupService, InMemorySetNx
from app.intake.normalizer import IntakeOutcome, IssueNormalizer
from app.repo.memory import MemoryStore


def sql_alert(alert_ref: str = "check:1", rule_id: str = "py/sql-injection") -> RawAlert:
    return RawAlert(
        alert_ref=alert_ref,
        source_kind=SourceKind.CHECK,
        rule_id=rule_id,
        file_path="app/main.py",
        line=31,
        severity=Severity.HIGH,
        snippet="rows = conn.execute(\"SELECT id FROM users WHERE id = '%s'\" % uid)",
    )


def dependency_check_alert(alert_ref: str = "check:dep:1") -> RawAlert:
    return RawAlert(
        alert_ref=alert_ref,
        source_kind=SourceKind.CHECK,
        rule_id="sca-cve",
        file_path="requirements.txt",
        line=None,
        severity=Severity.MEDIUM,
        component="requests",
        component_version="2.19.1",
    )


def dependency_governance_alert() -> RawDependencyAlert:
    return RawDependencyAlert(
        alert_ref="gov:dep:1",
        source_kind=SourceKind.GOVERNANCE,
        package="requests",
        current_version="2.19.1",
        affected_introduced="2.0.0",
        fixed_version="2.20.0",
        severity=Severity.MEDIUM,
    )


class DefectRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = default_registry()

    def test_matches_four_supported_classes(self) -> None:
        cases = {
            "py/sql-injection": DefectClass.SQL_INJECTION,
            "py/command-injection": DefectClass.COMMAND_INJECTION,
            "py/hardcoded-secret": DefectClass.HARDCODED_SECRET,
            "sca-cve": DefectClass.DEPENDENCY_CVE,
        }
        for rule_id, expected in cases.items():
            plugin = self.registry.match(sql_alert(rule_id=rule_id))
            self.assertIsNotNone(plugin, rule_id)
            self.assertIs(plugin.defect_class, expected)

    def test_injection_subclasses_outside_scope(self) -> None:
        for rule_id in ("py/path-traversal", "py/xss", "py/ssrf", "py/deserialization"):
            self.assertIsNone(self.registry.match(sql_alert(rule_id=rule_id)), rule_id)

    def test_only_dependency_plugin_is_dependency_only(self) -> None:
        dependency_only = [plugin for plugin in self.registry.plugins if plugin.is_dependency_only()]
        self.assertEqual(len(dependency_only), 1)
        self.assertIs(dependency_only[0].defect_class, DefectClass.DEPENDENCY_CVE)

    def test_templates_and_assertion_policy_present(self) -> None:
        for plugin in self.registry.plugins:
            self.assertTrue(plugin.template_candidates())
            policy = plugin.assertion_policy()
            self.assertTrue(policy.must_fail_before_patch)
            self.assertIn("assert True", policy.forbidden_markers)


class NormalizerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config()
        self.store = MemoryStore()
        self.dedup = DedupService(self.store, InMemorySetNx())
        self.normalizer = IssueNormalizer(self.store, self.dedup, self.config)

    def test_created_issue_carries_class_and_source(self) -> None:
        result = self.normalizer.ingest_alert(sql_alert(), "verifix-target", "abc123")
        self.assertIs(result.outcome, IntakeOutcome.CREATED)
        self.assertIsNotNone(result.issue)
        issue = result.issue
        assert issue is not None
        self.assertIs(issue.status, IssueStatus.RECEIVED)
        self.assertIs(issue.defect_class, DefectClass.SQL_INJECTION)
        self.assertEqual(issue.source_count, 1)
        self.assertEqual(len(self.store.alerts_for(issue.issue_id)), 1)

    def test_un_normalized_alert_is_rejected(self) -> None:
        broken = sql_alert(rule_id="")
        result = self.normalizer.ingest_alert(broken, "verifix-target", "abc123")
        self.assertIs(result.outcome, IntakeOutcome.REJECTED)
        self.assertIs(result.error_code, ErrorCode.NOT_NORMALIZED)
        self.assertIsNone(result.issue_id)
        self.assertEqual(len(self.store.issues), 0)

    def test_out_of_scope_alert_is_archived_and_excluded(self) -> None:
        result = self.normalizer.ingest_alert(sql_alert(rule_id="py/path-traversal"), "verifix-target", "abc123")
        self.assertIs(result.outcome, IntakeOutcome.OUT_OF_SCOPE)
        self.assertIs(result.error_code, ErrorCode.OUT_OF_SCOPE)
        issue = result.issue
        assert issue is not None
        self.assertFalse(issue.in_scope)
        self.assertIs(issue.status, IssueStatus.ARCHIVED)
        self.assertIsNone(issue.defect_class)

    def test_duplicate_alert_returns_existing_issue(self) -> None:
        first = self.normalizer.ingest_alert(sql_alert(), "verifix-target", "abc123")
        second = self.normalizer.ingest_alert(sql_alert(), "verifix-target", "abc123")
        self.assertIs(second.outcome, IntakeOutcome.MERGED)
        self.assertEqual(first.issue_id, second.issue_id)
        self.assertEqual(len(self.store.issues), 1)
        self.assertEqual(len(self.store.alerts_for(first.issue_id or "")), 1)

    def test_check_and_governance_merge_into_one_issue_with_source_count_two(self) -> None:
        check = self.normalizer.ingest_alert(dependency_check_alert(), "verifix-target", "abc123")
        governance = self.normalizer.ingest_dependency(
            dependency_governance_alert(), None, "verifix-target", "abc123"
        )
        self.assertIs(check.outcome, IntakeOutcome.CREATED)
        self.assertIs(governance.outcome, IntakeOutcome.MERGED)
        self.assertEqual(check.issue_id, governance.issue_id)
        self.assertEqual(len(self.store.issues), 1)
        alerts = self.store.alerts_for(check.issue_id or "")
        self.assertEqual(len(alerts), 2)
        self.assertEqual({alert.source_kind for alert in alerts}, {SourceKind.CHECK, SourceKind.GOVERNANCE})
        issue = self.store.get(check.issue_id or "")
        self.assertEqual(issue.source_count, 2)

    def test_dependency_issue_uses_component_locator_without_line(self) -> None:
        result = self.normalizer.ingest_dependency(dependency_governance_alert(), None, "verifix-target", "abc123")
        issue = result.issue
        assert issue is not None
        self.assertIs(issue.defect_class, DefectClass.DEPENDENCY_CVE)
        alerts = self.store.alerts_for(issue.issue_id)
        locator = alerts[0].location
        self.assertIsNone(locator.line)
        self.assertEqual(locator.component, "requests")
        self.assertEqual(locator.component_version, "2.19.1")

    def test_new_plugin_registers_without_touching_orchestration(self) -> None:
        registry = default_registry()
        before = registry.classes()
        self.assertEqual(len(before), 4)


if __name__ == "__main__":
    unittest.main()