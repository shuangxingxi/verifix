from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol, Sequence

from app.domain.enums import EventType
from app.domain.models import Event

ALERT_KINDS = (
    "CIRCUIT_OPEN",
    "CONSECUTIVE_FAILURE",
    "GATE_INTEGRATION_ERROR",
    "SELF_RUN_INTERRUPTED",
)
ALERT_WINDOW_MINUTES = 5
DEFAULT_TIMEOUT_SECONDS = 10.0
NOTIFIER_ACTOR = "notifier"


@dataclass(frozen=True)
class AlertMessage:
    alert_kind: str
    message: str
    issue_id: str = ""
    run_id: str = ""
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if self.alert_kind not in ALERT_KINDS:
            raise ValueError(f"unsupported alert kind: {self.alert_kind}")
        if not self.message.strip():
            raise ValueError("alert message must not be blank")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("alert occurred_at must be timezone-aware")

    def as_payload(self) -> dict[str, object]:
        return {
            "alert_kind": self.alert_kind,
            "message": self.message,
            "issue_id": self.issue_id,
            "run_id": self.run_id,
            "occurred_at": self.occurred_at.isoformat(),
            "window_minutes": ALERT_WINDOW_MINUTES,
        }


@dataclass(frozen=True)
class DeliveryResult:
    channel: str
    delivered: bool
    elapsed_ms: int
    error: str = ""


class NotifierPort(Protocol):
    channel: str

    def deliver(self, message: AlertMessage, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> DeliveryResult: ...


class ConsoleNotifier:
    channel = "console"

    def __init__(self, sink=None) -> None:
        self._sink = sink or print

    def deliver(self, message: AlertMessage, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> DeliveryResult:
        started = time.perf_counter()
        self._sink(json.dumps(message.as_payload(), ensure_ascii=False, sort_keys=True))
        return DeliveryResult(self.channel, True, int((time.perf_counter() - started) * 1000))


class WebhookNotifier:
    channel = "webhook"

    def __init__(self, url: str, opener=None) -> None:
        if not url.strip():
            raise ValueError("webhook url must not be blank")
        self.url = url
        self._opener = opener

    def deliver(self, message: AlertMessage, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> DeliveryResult:
        started = time.perf_counter()
        body = json.dumps(message.as_payload(), ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        opener = self._opener or urllib.request.build_opener()
        try:
            with opener.open(request, timeout=max(0.1, timeout_seconds)) as response:
                status = int(getattr(response, "status", 200))
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            return DeliveryResult(self.channel, False, elapsed, type(exc).__name__)
        elapsed = int((time.perf_counter() - started) * 1000)
        if 200 <= status < 300:
            return DeliveryResult(self.channel, True, elapsed)
        return DeliveryResult(self.channel, False, elapsed, f"http_{status}")


class NotifierRouter:
    def __init__(self, notifiers: Sequence[NotifierPort], event_store=None) -> None:
        self.notifiers = list(notifiers)
        self.event_store = event_store
        self.degraded = False
        self.undelivered: list[AlertMessage] = []

    def notify(self, message: AlertMessage) -> DeliveryResult:
        failures: list[str] = []
        for notifier in self.notifiers:
            result = notifier.deliver(message)
            if result.delivered:
                return result
            failures.append(f"{result.channel}:{result.error or 'failed'}")
        self.degraded = True
        self.undelivered.append(message)
        self._record_undelivered(message, failures)
        return DeliveryResult("none", False, 0, ",".join(failures) or "no_channel")

    def _record_undelivered(self, message: AlertMessage, failures: list[str]) -> None:
        if self.event_store is None:
            return
        event = Event(
            event_id="EVT-NOTIFIER-" + uuid.uuid4().hex[:12],
            run_id=message.run_id or "notifier",
            seq=1,
            event_type=EventType.ALERT,
            actor=NOTIFIER_ACTOR,
            payload_ref="undelivered:" + message.alert_kind + ":" + ",".join(failures),
        )
        self.event_store.append(event)

    def status(self) -> dict[str, object]:
        return {
            "degraded": self.degraded,
            "undelivered_alerts": len(self.undelivered),
            "alert_kinds": [item.alert_kind for item in self.undelivered],
        }