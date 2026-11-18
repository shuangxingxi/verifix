from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Protocol

import httpx

from app.adapters.types import RawAlert, ScanTaskRef, ScanTaskStatus, UpstreamUnavailable
from app.domain.enums import Severity, SourceKind

CHECK_TIMEOUT_SECONDS = 10.0

FIELD_MAP: dict[str, str] = {
    "alert_ref": "alertId",
    "rule_id": "ruleId",
    "file_path": "filePath",
    "line": "startLine",
    "severity": "severity",
    "snippet": "codeSnippet",
    "component": "componentName",
    "component_version": "componentVersion",
    "task_id": "taskId",
    "status": "taskStatus",
}

SEVERITY_MAP: dict[str, Severity] = {
    "critical": Severity.CRITICAL,
    "high": Severity.HIGH,
    "medium": Severity.MEDIUM,
    "low": Severity.LOW,
    "info": Severity.INFO,
    "提示": Severity.INFO,
    "低": Severity.LOW,
    "中": Severity.MEDIUM,
    "高": Severity.HIGH,
    "严重": Severity.CRITICAL,
}

STATUS_MAP: dict[str, ScanTaskStatus] = {
    "success": ScanTaskStatus.SUCCESS,
    "finished": ScanTaskStatus.SUCCESS,
    "running": ScanTaskStatus.RUNNING,
    "failed": ScanTaskStatus.FAILED,
    "error": ScanTaskStatus.FAILED,
}


class CheckClient(Protocol):
    def fetch_alerts(self, task: ScanTaskRef) -> list[dict]: ...
    def fetch_task_status(self, task: ScanTaskRef) -> dict: ...


@dataclass
class RecordedCheckClient:
    alerts: list[dict] = field(default_factory=list)
    status: str = "success"
    fail: bool = False
    calls: int = 0

    def fetch_alerts(self, task: ScanTaskRef) -> list[dict]:
        self.calls += 1
        if self.fail:
            raise UpstreamUnavailable("check", "recorded failure")
        return list(self.alerts)

    def fetch_task_status(self, task: ScanTaskRef) -> dict:
        if self.fail:
            raise UpstreamUnavailable("check", "recorded failure")
        return {"taskId": task.task_id, "taskStatus": self.status}


class HttpCheckClient:
    def __init__(self, base_url: str, token: str, transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.transport = transport

    def fetch_alerts(self, task: ScanTaskRef) -> list[dict]:
        url = f"{self.base_url}/v1/check/tasks/{task.task_id}/alerts"
        payload = self._request(url)
        return list(payload.get("alerts", []))

    def fetch_task_status(self, task: ScanTaskRef) -> dict:
        url = f"{self.base_url}/v1/check/tasks/{task.task_id}"
        return self._request(url)

    def _request(self, url: str) -> dict:
        headers = {"X-Auth-Token": self.token}
        with httpx.Client(timeout=CHECK_TIMEOUT_SECONDS, transport=self.transport) as client:
            response = client.get(url, headers=headers)
        if response.status_code >= 500 or response.status_code == 429:
            raise UpstreamUnavailable("check", f"http {response.status_code}")
        if response.status_code >= 400:
            raise UpstreamUnavailable("check", f"http {response.status_code}")
        return response.json()


@dataclass(frozen=True)
class CheckFetchResult:
    alerts: list[RawAlert]
    degraded: bool
    message: str
    task_status: ScanTaskStatus


class CheckAdapter:
    def __init__(
        self,
        client: CheckClient,
        field_map: dict[str, str] | None = None,
        max_attempts: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.client = client
        self.field_map = dict(FIELD_MAP if field_map is None else field_map)
        self.max_attempts = max_attempts
        self.sleeper = sleeper
        self._last_good: list[RawAlert] = []

    def _pick(self, record: dict, key: str):
        return record.get(self.field_map[key])

    def map_alert(self, record: dict) -> RawAlert:
        raw_severity = str(self._pick(record, "severity") or "medium").strip().lower()
        severity = SEVERITY_MAP.get(raw_severity, Severity.MEDIUM)
        line = self._pick(record, "line")
        return RawAlert(
            alert_ref=str(self._pick(record, "alert_ref") or "check:unknown"),
            source_kind=SourceKind.CHECK,
            rule_id=str(self._pick(record, "rule_id") or ""),
            file_path=str(self._pick(record, "file_path") or ""),
            line=int(line) if line is not None and str(line).isdigit() else None,
            severity=severity,
            snippet=str(self._pick(record, "snippet") or ""),
            component=self._pick(record, "component"),
            component_version=self._pick(record, "component_version"),
            observed_at=datetime.now(timezone.utc),
        )

    def fetch_alerts(self, task: ScanTaskRef) -> CheckFetchResult:
        attempt = 0
        last_error = ""
        while attempt < self.max_attempts:
            attempt += 1
            try:
                records = self.client.fetch_alerts(task)
                alerts = [self.map_alert(record) for record in records]
                self._last_good = alerts
                status = self.fetch_task_status(task)
                return CheckFetchResult(alerts=alerts, degraded=False, message="", task_status=status)
            except UpstreamUnavailable as exc:
                last_error = exc.detail or exc.source
                if attempt < self.max_attempts:
                    self.sleeper(2 ** (attempt - 1))
        return CheckFetchResult(
            alerts=list(self._last_good),
            degraded=True,
            message="数据源不可用（Check）",
            task_status=ScanTaskStatus.FAILED,
        )

    def fetch_task_status(self, task: ScanTaskRef) -> ScanTaskStatus:
        try:
            payload = self.client.fetch_task_status(task)
        except UpstreamUnavailable:
            return ScanTaskStatus.FAILED
        raw = str(payload.get(self.field_map["status"], "failed")).strip().lower()
        return STATUS_MAP.get(raw, ScanTaskStatus.FAILED)