from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.adapters.types import RawAlert, RawDependencyAlert
from app.domain.enums import DefectClass, FixParadigm, SourceKind

FORBIDDEN_TEST_MARKERS: tuple[str, ...] = (
    "assert True",
    "@pytest.mark.skip",
    "@unittest.skip",
    "pytest.skip(",
    "requests.get(",
    "requests.post(",
    "urllib.request",
    "socket.connect",
)


@dataclass(frozen=True)
class AssertionPolicy:
    expected_signal: str
    forbidden_markers: tuple[str, ...] = FORBIDDEN_TEST_MARKERS
    must_fail_before_patch: bool = True
    must_pass_after_patch: bool = True


@dataclass(frozen=True)
class NormalizedClassification:
    defect_class: DefectClass
    fix_paradigm: FixParadigm
    dependency_only: bool
    source_count: int = 1


class DefectPlugin(ABC):
    defect_class: DefectClass
    display_name: str
    rule_keywords: tuple[str, ...] = ()
    dependency_sources: frozenset[SourceKind] = frozenset()
    fix_paradigm: FixParadigm = FixParadigm.PARAMETERIZED_QUERY

    def matches(self, alert: RawAlert) -> bool:
        if self.dependency_sources and alert.source_kind in self.dependency_sources:
            return True
        rule = alert.rule_id.strip().lower()
        return any(keyword in rule for keyword in self.rule_keywords)

    @abstractmethod
    def assertion_policy(self) -> AssertionPolicy: ...

    @abstractmethod
    def template_candidates(self) -> tuple[str, ...]: ...

    def is_dependency_only(self) -> bool:
        return False

    def normalize(self, alert: RawAlert) -> NormalizedClassification:
        return NormalizedClassification(
            defect_class=self.defect_class,
            fix_paradigm=self.fix_paradigm,
            dependency_only=self.is_dependency_only(),
        )


class C01DependencyCve(DefectPlugin):
    defect_class = DefectClass.DEPENDENCY_CVE
    display_name = "依赖 CVE"
    rule_keywords = ("dependency", "dependency-cve", "sca", "cve-", "osv")
    dependency_sources = frozenset({SourceKind.GOVERNANCE, SourceKind.OSV, SourceKind.CNVD})
    fix_paradigm = FixParadigm.VERSION_UPGRADE

    def assertion_policy(self) -> AssertionPolicy:
        return AssertionPolicy(expected_signal="installed_version_outside_affected_range")

    def template_candidates(self) -> tuple[str, ...]:
        return ("dependency_version_bump",)

    def is_dependency_only(self) -> bool:
        return True


class C02SqlInjection(DefectPlugin):
    defect_class = DefectClass.SQL_INJECTION
    display_name = "SQL 注入"
    rule_keywords = ("sql-injection", "sql_injection", "sqli", "cwe-89", "sql 注入")
    fix_paradigm = FixParadigm.PARAMETERIZED_QUERY

    def assertion_policy(self) -> AssertionPolicy:
        return AssertionPolicy(expected_signal="injected_payload_returns_no_extra_rows")

    def template_candidates(self) -> tuple[str, ...]:
        return ("sql_injection_parameterized_query",)


class C03CommandInjection(DefectPlugin):
    defect_class = DefectClass.COMMAND_INJECTION
    display_name = "命令注入"
    rule_keywords = ("command-injection", "command_injection", "os-command", "shell-injection", "cwe-78")
    fix_paradigm = FixParadigm.PARAMETERIZED_COMMAND

    def assertion_policy(self) -> AssertionPolicy:
        return AssertionPolicy(expected_signal="injected_command_not_executed")

    def template_candidates(self) -> tuple[str, ...]:
        return ("command_injection_argument_list",)


class C05HardcodedSecret(DefectPlugin):
    defect_class = DefectClass.HARDCODED_SECRET
    display_name = "硬编码凭据"
    rule_keywords = ("hardcoded-secret", "hardcoded_secret", "hardcoded", "credential", "cwe-798", "secret-scan")
    fix_paradigm = FixParadigm.CREDENTIAL_EXTERNALIZATION

    def assertion_policy(self) -> AssertionPolicy:
        return AssertionPolicy(expected_signal="secret_literal_absent_from_config")

    def template_candidates(self) -> tuple[str, ...]:
        return ("secret_externalized_to_env",)


@dataclass
class DefectRegistry:
    plugins: list[DefectPlugin] = field(default_factory=list)

    def register(self, plugin: DefectPlugin) -> None:
        self.plugins.append(plugin)

    def match(self, alert: RawAlert) -> DefectPlugin | None:
        for plugin in self.plugins:
            if plugin.matches(alert):
                return plugin
        return None

    def by_class(self, defect_class: DefectClass) -> DefectPlugin | None:
        for plugin in self.plugins:
            if plugin.defect_class is defect_class:
                return plugin
        return None

    def classes(self) -> tuple[DefectClass, ...]:
        return tuple(plugin.defect_class for plugin in self.plugins)

    def match_dependency(self, alert: RawDependencyAlert) -> DefectPlugin | None:
        rule = alert.package.strip().lower()
        for plugin in self.plugins:
            if plugin.is_dependency_only():
                return plugin
        del rule
        return None


def default_registry() -> DefectRegistry:
    return DefectRegistry(
        plugins=[
            C01DependencyCve(),
            C02SqlInjection(),
            C03CommandInjection(),
            C05HardcodedSecret(),
        ]
    )