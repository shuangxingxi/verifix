from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from app.adapters.types import RangeResult, RawAlert, RawDependencyAlert
from app.api.envelope import ErrorCode
from app.config import AppConfig
from app.domain.defects.plugins import DefectPlugin, DefectRegistry, default_registry
from app.domain.enums import DefectClass, EventType, IssueStatus, MetricChannel
from app.domain.models import Alert, Event, Issue, Location
from app.ops.prompt_guard import sanitize_untrusted_text
from app.intake.dedup import DedupService
from app.intake.service import compute_fingerprint


class IntakeOutcome(str, Enum):
    CREATED = "CREATED"
    MERGED = "MERGED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class NormalizationResult:
    outcome: IntakeOutcome
    issue_id: str | None
    issue: Issue | None
    reason: str
    error_code: ErrorCode | None
    source_count: int
    plugin: DefectPlugin | None = None
    untrusted_hits: tuple[str, ...] = ()


def _to_alert(alert: RawAlert, issue_id: str, snippet_text: str | None = None) -> Alert:
    sanitized = sanitize_untrusted_text(alert.snippet) if snippet_text is None else None
    stored_snippet = sanitized.text if sanitized is not None else (snippet_text or "")
    location = Location(
        file=alert.file_path,
        line=alert.line,
        component=alert.component,
        component_version=alert.component_version,
    )
    return Alert(
        alert_ref=alert.alert_ref,
        source_kind=alert.source_kind,
        rule_id=alert.rule_id,
        location=location,
        raw_severity=alert.severity,
        snippet_fingerprint=compute_fingerprint(
            issue_id, alert.file_path, location, alert.rule_id, alert.snippet
        ),
        defect_class=None,
        snippet=stored_snippet,
        observed_at=alert.observed_at or datetime.now(timezone.utc),
    )


class IssueNormalizer:
    def __init__(
        self,
        store,
        dedup: DedupService,
        config: AppConfig,
        registry: DefectRegistry | None = None,
    ):
        self.store = store
        self.dedup = dedup
        self.config = config
        self.registry = registry or default_registry()

    def ingest_alert(
        self,
        alert: RawAlert,
        repo: str,
        code_version: str,
        channel: MetricChannel = MetricChannel.MAIN,
    ) -> NormalizationResult:
        if not alert.rule_id or not alert.file_path or not alert.locator_ok():
            return NormalizationResult(
                outcome=IntakeOutcome.REJECTED,
                issue_id=None,
                issue=None,
                reason="告警缺规则/定位/类别",
                error_code=ErrorCode.NOT_NORMALIZED,
                source_count=0,
            )

        sanitized = sanitize_untrusted_text(alert.snippet)
        untrusted_hits = sanitized.hits
        plugin = self.registry.match(alert)
        if plugin is None:
            return self._archive_out_of_scope(alert, repo, code_version, channel, untrusted_hits)

        location = Location(
            file=alert.file_path,
            line=alert.line,
            component=alert.component,
            component_version=alert.component_version,
        )
        rule_key = "dependency-cve" if plugin.is_dependency_only() else alert.rule_id
        snippet_key = (
            f"{alert.component}=={alert.component_version}"
            if plugin.is_dependency_only() and alert.component and alert.component_version
            else alert.snippet
        )
        fingerprint = compute_fingerprint(repo, code_version, location, rule_key, snippet_key)
        dedup = self.dedup.claim(repo, fingerprint)
        if dedup.existing_issue_id is not None:
            return self._merge(dedup.existing_issue_id, alert, plugin, untrusted_hits)

        now = datetime.now(timezone.utc)
        issue = Issue(
            issue_id=f"ISS-{uuid.uuid4().hex[:12]}",
            repo=repo,
            code_version=code_version,
            defect_class=plugin.defect_class,
            severity=alert.severity,
            status=IssueStatus.RECEIVED,
            source_count=1,
            fingerprint=fingerprint,
            in_scope=True,
            occurred_at=now,
            updated_at=now,
            channel=channel,
        )
        with self.store.transaction():
            self.store.add(issue)
            self.store.link_alert(issue.issue_id, _to_alert(alert, issue.issue_id, sanitized.text))
            if untrusted_hits:
                self.store.append(
                    Event(
                        event_id="CTRL-" + issue.issue_id + "-" + uuid.uuid4().hex[:6],
                        run_id="intake:" + issue.issue_id,
                        seq=1,
                        event_type=EventType.CONTROL,
                        actor="prompt-guard",
                        payload_ref="prompt_injection:" + ",".join(untrusted_hits),
                    )
                )
        return NormalizationResult(
            outcome=IntakeOutcome.CREATED,
            issue_id=issue.issue_id,
            issue=issue,
            reason="",
            error_code=None,
            source_count=1,
            plugin=plugin,
            untrusted_hits=untrusted_hits,
        )

    def ingest_dependency(
        self,
        alert: RawDependencyAlert,
        range_result: RangeResult | None,
        repo: str,
        code_version: str,
    ) -> NormalizationResult:
        plugin = next((item for item in self.registry.plugins if item.is_dependency_only()), None)
        if plugin is None:
            return NormalizationResult(
                outcome=IntakeOutcome.REJECTED,
                issue_id=None,
                issue=None,
                reason="依赖插件未注册",
                error_code=ErrorCode.NOT_NORMALIZED,
                source_count=0,
            )
        location = Location(
            file="requirements.txt",
            component=alert.package,
            component_version=alert.current_version,
        )
        snippet = f"{alert.package}=={alert.current_version}"
        fingerprint = compute_fingerprint(repo, code_version, location, "dependency-cve", snippet)
        dedup = self.dedup.claim(repo, fingerprint)
        if dedup.existing_issue_id is not None:
            issue = self.store.get(dedup.existing_issue_id)
            with self.store.transaction():
                self.store.link_alert(
                    issue.issue_id,
                    Alert(
                        alert_ref=alert.alert_ref,
                        source_kind=alert.source_kind,
                        rule_id="dependency-cve",
                        location=location,
                        raw_severity=alert.severity,
                        snippet_fingerprint=fingerprint,
                        defect_class=DefectClass.DEPENDENCY_CVE,
                        snippet=snippet,
                    ),
                )
                merged = self._bump_source(issue)
            return NormalizationResult(
                outcome=IntakeOutcome.MERGED,
                issue_id=merged.issue_id,
                issue=merged,
                reason="多来源合并" + ("（区间冲突已取更严）" if range_result and range_result.conflict else ""),
                error_code=ErrorCode.IDEMPOTENT_HIT,
                source_count=merged.source_count,
                plugin=plugin,
            )
        now = datetime.now(timezone.utc)
        issue = Issue(
            issue_id=f"ISS-{uuid.uuid4().hex[:12]}",
            repo=repo,
            code_version=code_version,
            defect_class=DefectClass.DEPENDENCY_CVE,
            severity=alert.severity,
            status=IssueStatus.RECEIVED,
            source_count=1,
            fingerprint=fingerprint,
            in_scope=True,
            occurred_at=now,
            updated_at=now,
        )
        with self.store.transaction():
            self.store.add(issue)
            self.store.link_alert(
                issue.issue_id,
                Alert(
                    alert_ref=alert.alert_ref,
                    source_kind=alert.source_kind,
                    rule_id="dependency-cve",
                    location=location,
                    raw_severity=alert.severity,
                    snippet_fingerprint=fingerprint,
                    defect_class=DefectClass.DEPENDENCY_CVE,
                    snippet=snippet,
                ),
            )
        return NormalizationResult(
            outcome=IntakeOutcome.CREATED,
            issue_id=issue.issue_id,
            issue=issue,
            reason="依赖兜底来源已标记" if range_result and range_result.needs_human else "",
            error_code=None,
            source_count=1,
            plugin=plugin,
        )

    def _merge(
        self,
        issue_id: str,
        alert: RawAlert,
        plugin: DefectPlugin,
        untrusted_hits: tuple[str, ...] = (),
    ) -> NormalizationResult:
        existing = self.store.get(issue_id)
        sanitized = sanitize_untrusted_text(alert.snippet)
        with self.store.transaction():
            self.store.link_alert(issue_id, _to_alert(alert, issue_id, sanitized.text))
            merged = self._bump_source(existing)
        return NormalizationResult(
            outcome=IntakeOutcome.MERGED,
            issue_id=merged.issue_id,
            issue=merged,
            reason="多来源合并",
            error_code=ErrorCode.IDEMPOTENT_HIT,
            source_count=merged.source_count,
            plugin=plugin,
            untrusted_hits=untrusted_hits,
        )

    def _bump_source(self, issue: Issue) -> Issue:
        alerts = self.store.alerts_for(issue.issue_id)
        updated = issue.model_copy(
            update={
                "source_count": max(len(alerts), issue.source_count),
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self.store.update(updated)
        return updated

    def _archive_out_of_scope(
        self,
        alert: RawAlert,
        repo: str,
        code_version: str,
        channel: MetricChannel = MetricChannel.MAIN,
        untrusted_hits: tuple[str, ...] = (),
    ) -> NormalizationResult:
        sanitized = sanitize_untrusted_text(alert.snippet)
        location = Location(
            file=alert.file_path,
            line=alert.line,
            component=alert.component,
            component_version=alert.component_version,
        )
        fingerprint = compute_fingerprint(repo, code_version, location, alert.rule_id, alert.snippet)
        now = datetime.now(timezone.utc)
        issue = Issue(
            issue_id=f"ISS-{uuid.uuid4().hex[:12]}",
            repo=repo,
            code_version=code_version,
            defect_class=None,
            severity=alert.severity,
            status=IssueStatus.ARCHIVED,
            source_count=1,
            fingerprint=fingerprint,
            in_scope=False,
            occurred_at=now,
            updated_at=now,
            channel=channel,
        )
        with self.store.transaction():
            self.store.add(issue)
            self.store.link_alert(issue.issue_id, _to_alert(alert, issue.issue_id, sanitized.text))
        return NormalizationResult(
            outcome=IntakeOutcome.OUT_OF_SCOPE,
            issue_id=issue.issue_id,
            issue=issue,
            reason="范围外，已归档",
            error_code=ErrorCode.OUT_OF_SCOPE,
            source_count=1,
            untrusted_hits=untrusted_hits,
        )