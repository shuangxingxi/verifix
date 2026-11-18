from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Protocol

import httpx

from app.adapters.types import RawDependencyAlert, RepoRef, UpstreamUnavailable
from app.domain.enums import Severity, SourceKind

GOVERNANCE_TIMEOUT_SECONDS = 15.0

FIELD_MAP: dict[str, str] = {
    "alert_ref": "findingId",
    "package": "packageName",
    "current_version": "currentVersion",
    "affected_introduced": "introducedVersion",
    "fixed_version": "fixedVersion",
    "severity": "severity",
}

SEVERITY_MAP: dict[str, Severity] = {
    "critical": Severity.CRITICAL,
    "high": Severity.HIGH,
    "medium": Severity.MEDIUM,
    "low": Severity.LOW,
    "info": Severity.INFO,
}


class GovernanceClient(Protocol):
    def fetch_dependency_findings(self, repo: RepoRef) -> list[dict]: ...


@dataclass
class RecordedGovernanceClient:
    findings: list[dict] = field(default_factory=list)
    fail: bool = False
    calls: int = 0

    def fetch_dependency_findings(self, repo: RepoRef) -> list[dict]:
        self.calls += 1
        if self.fail:
            raise UpstreamUnavailable("governance", "recorded failure")
        return list(self.findings)


class HttpGovernanceClient:
    def __init__(self, base_url: str, token: str, transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.transport = transport

    def fetch_dependency_findings(self, repo: RepoRef) -> list[dict]:
        url = f"{self.base_url}/v1/governance/repos/{repo.repo}/dependencies"
        headers = {"X-Auth-Token": self.token}
        params = {"base_sha": repo.base_sha}
        with httpx.Client(timeout=GOVERNANCE_TIMEOUT_SECONDS, transport=self.transport) as client:
            response = client.get(url, headers=headers, params=params)
        if response.status_code >= 400:
            raise UpstreamUnavailable("governance", f"http {response.status_code}")
        return list(response.json().get("findings", []))


@dataclass(frozen=True)
class GovernanceFetchResult:
    findings: list[RawDependencyAlert]
    available: bool
    empty: bool
    message: str


class GovernanceAdapter:
    def __init__(
        self,
        client: GovernanceClient,
        field_map: dict[str, str] | None = None,
        max_attempts: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.client = client
        self.field_map = dict(FIELD_MAP if field_map is None else field_map)
        self.max_attempts = max_attempts
        self.sleeper = sleeper

    def _pick(self, record: dict, key: str):
        return record.get(self.field_map[key])

    def map_finding(self, record: dict) -> RawDependencyAlert:
        severity = SEVERITY_MAP.get(str(self._pick(record, "severity") or "medium").lower(), Severity.MEDIUM)
        return RawDependencyAlert(
            alert_ref=str(self._pick(record, "alert_ref") or "governance:unknown"),
            source_kind=SourceKind.GOVERNANCE,
            package=str(self._pick(record, "package") or ""),
            current_version=str(self._pick(record, "current_version") or ""),
            affected_introduced=str(self._pick(record, "affected_introduced") or "0.0.0"),
            fixed_version=self._pick(record, "fixed_version"),
            severity=severity,
            reported_at=datetime.now(timezone.utc),
        )

    def fetch_dependency_findings(self, repo: RepoRef) -> GovernanceFetchResult:
        attempt = 0
        while attempt < self.max_attempts:
            attempt += 1
            try:
                records = self.client.fetch_dependency_findings(repo)
                findings = [self.map_finding(record) for record in records]
                return GovernanceFetchResult(
                    findings=findings,
                    available=True,
                    empty=not findings,
                    message="",
                )
            except UpstreamUnavailable:
                if attempt < self.max_attempts:
                    self.sleeper(2 ** (attempt - 1))
        return GovernanceFetchResult(
            findings=[],
            available=False,
            empty=False,
            message="数据源不可用（Governance）",
        )