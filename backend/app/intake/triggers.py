from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from app.adapters.types import RawAlert, RawDependencyAlert
from app.api.envelope import ApiError, ErrorCode
from app.config import AppConfig
from app.domain.enums import DefectClass, Severity, SourceKind
from app.intake.auth import AuthGuard, AuthError, RateLimiter
from app.intake.normalizer import IntakeOutcome, IssueNormalizer, NormalizationResult


class TriggerKind(str, Enum):
    REPO_WEBHOOK = "REPO_WEBHOOK"
    SCHEDULE = "SCHEDULE"
    CVE = "CVE"
    RUNTIME_ALERT = "RUNTIME_ALERT"
    MANUAL = "MANUAL"


class RepoWebhookPayload(BaseModel):
    repo: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    base_sha: str = Field(min_length=1)
    action: str = "merged"
    actor: str = "codearts-repo"


class CvePayload(BaseModel):
    repo: str
    code_version: str
    package: str = Field(min_length=1)
    current_version: str = Field(min_length=1)
    affected_introduced: str = "0.0.0"
    fixed_version: str | None = None
    severity: Severity = Severity.HIGH
    actor: str = "cve-subscription"

    @field_validator("severity", mode="before")
    @classmethod
    def _normalize_severity(cls, value: object) -> str:
        return str(value).upper()


class RuntimeAlertPayload(BaseModel):
    repo: str
    code_version: str
    rule_id: str = Field(min_length=1)
    file: str = Field(min_length=1)
    line: int | None = Field(default=None, ge=1)
    severity: Severity = Severity.HIGH
    snippet: str = ""
    evidence_ref: str = ""
    actor: str = "runtime-agent"

    @field_validator("severity", mode="before")
    @classmethod
    def _normalize_severity(cls, value: object) -> str:
        return str(value).upper()


@dataclass(frozen=True)
class TriggerOutcome:
    kind: TriggerKind
    accepted: bool
    skipped: bool
    issue_id: str | None
    outcome: IntakeOutcome | None
    reason: str
    source_count: int = 0


class TriggerService:
    def __init__(
        self,
        normalizer: IssueNormalizer,
        config: AppConfig,
        auth: AuthGuard,
        limiter: RateLimiter,
    ):
        self.normalizer = normalizer
        self.config = config
        self.auth = auth
        self.limiter = limiter

    def _guard(self, key: str, token: str | None) -> None:
        try:
            self.auth.verify_token(token)
        except AuthError as exc:
            raise ApiError(ErrorCode.UNAUTHORIZED, exc.reason) from exc
        if not self.limiter.allow(key):
            raise ApiError(ErrorCode.CIRCUIT_OPEN, f"rate limit exceeded for {key}")

    def handle_repo_webhook(self, payload: RepoWebhookPayload, signature: str | None, body: bytes, token: str | None = None) -> TriggerOutcome:
        try:
            self.auth.verify_signature(body, signature)
        except AuthError as exc:
            raise ApiError(ErrorCode.UNAUTHORIZED, exc.reason) from exc
        self._guard(f"webhook:{payload.repo}", token)
        if payload.branch in {"main", "master"}:
            return TriggerOutcome(
                TriggerKind.REPO_WEBHOOK,
                accepted=True,
                skipped=True,
                issue_id=None,
                outcome=None,
                reason="main 推送不触发自动修复，仅记录检测提示",
            )
        return TriggerOutcome(
            TriggerKind.REPO_WEBHOOK,
            accepted=True,
            skipped=False,
            issue_id=None,
            outcome=None,
            reason=f"repo 合并事件已受理（{payload.repo}@{payload.base_sha}），等待扫描任务产出告警",
        )

    def handle_cve(self, payload: CvePayload, token: str | None = None) -> TriggerOutcome:
        self._guard(f"cve:{payload.package}", token)
        alert = RawDependencyAlert(
            alert_ref=f"cve:{payload.package}:{payload.current_version}",
            source_kind=SourceKind.OSV,
            package=payload.package,
            current_version=payload.current_version,
            affected_introduced=payload.affected_introduced,
            fixed_version=payload.fixed_version,
            severity=payload.severity,
        )
        result: NormalizationResult = self.normalizer.ingest_dependency(
            alert, None, payload.repo, payload.code_version
        )
        return TriggerOutcome(
            TriggerKind.CVE,
            accepted=True,
            skipped=False,
            issue_id=result.issue_id,
            outcome=result.outcome,
            reason=result.reason or "CVE 订阅事件已归一化",
            source_count=result.source_count,
        )

    def handle_runtime_alert(self, payload: RuntimeAlertPayload, token: str | None = None) -> TriggerOutcome:
        self._guard(f"runtime:{payload.repo}", token)
        alert = RawAlert(
            alert_ref=f"runtime:{payload.repo}:{payload.rule_id}:{payload.line or 0}:{payload.evidence_ref}",
            source_kind=SourceKind.RUNTIME_ALERT,
            rule_id=payload.rule_id,
            file_path=payload.file,
            line=payload.line,
            severity=payload.severity,
            snippet=payload.snippet,
            component=None,
            component_version=None,
        )
        result = self.normalizer.ingest_alert(alert, payload.repo, payload.code_version)
        if result.outcome is IntakeOutcome.REJECTED:
            raise ApiError(ErrorCode.NOT_NORMALIZED, result.reason)
        return TriggerOutcome(
            TriggerKind.RUNTIME_ALERT,
            accepted=True,
            skipped=False,
            issue_id=result.issue_id,
            outcome=result.outcome,
            reason="运行时告警视为可达性强证据，仍需静态路径补齐" if payload.evidence_ref else "运行时告警已归一化",
            source_count=result.source_count,
        )

    def handle_manual(self, result: NormalizationResult | None, actor: str) -> TriggerOutcome:
        del actor
        return TriggerOutcome(
            TriggerKind.MANUAL,
            accepted=True,
            skipped=False,
            issue_id=result.issue_id if result else None,
            outcome=result.outcome if result else None,
            reason="人工提交已受理",
            source_count=result.source_count if result else 0,
        )

    def defect_class_of(self, rule_id: str) -> DefectClass | None:
        for plugin in self.normalizer.registry.plugins:
            for keyword in plugin.rule_keywords:
                if keyword in rule_id.lower():
                    return plugin.defect_class
        return None