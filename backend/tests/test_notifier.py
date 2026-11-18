from __future__ import annotations

import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.dashboard.service import DashboardService
from app.domain.enums import EventType
from app.ops.notifier import (
    ALERT_KINDS,
    AlertMessage,
    ConsoleNotifier,
    DeliveryResult,
    NotifierRouter,
    WebhookNotifier,
)


class _Store:
    def __init__(self) -> None:
        self.events = []

    def append(self, event):
        self.events.append(event)
        return event


class _FailingOpener:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def open(self, request, timeout=0):
        raise self.error


class _OkOpener:
    def __init__(self, status: int = 200) -> None:
        self.status = status

    def open(self, request, timeout=0):
        class _Response:
            status = self.status

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        return _Response()


class _Tracker:
    def continuous_hours(self) -> float:
        return 0.0

    def interruptions(self) -> int:
        return 0


class _Breaker:
    def is_paused(self) -> bool:
        return False

    def pause_reason(self) -> str:
        return ""


class _EmptyStore:
    issues = {}
    dispositions = {}
    verdicts = {}
    circuits = {}
    metrics = {}
    recalc_runs = {}
    events = {}


class NotifierTest(unittest.TestCase):
    def test_four_alert_kinds_are_delivered_on_console(self) -> None:
        lines: list[str] = []
        router = NotifierRouter([ConsoleNotifier(sink=lines.append)])
        for kind in ALERT_KINDS:
            result = router.notify(AlertMessage(alert_kind=kind, message=f"{kind} test", run_id="run-1"))
            self.assertTrue(result.delivered, kind)
        self.assertEqual(len(lines), 4)
        self.assertFalse(router.degraded)

    def test_webhook_timeout_degrades_and_records_event(self) -> None:
        store = _Store()
        webhook = WebhookNotifier("https://example.invalid/hook", opener=_FailingOpener(urllib.error.URLError("timeout")))
        router = NotifierRouter([webhook], event_store=store)
        result = router.notify(AlertMessage(alert_kind="CIRCUIT_OPEN", message="breaker open", run_id="run-9"))
        self.assertFalse(result.delivered)
        self.assertTrue(router.degraded)
        self.assertEqual(router.status()["undelivered_alerts"], 1)
        self.assertEqual(len(store.events), 1)
        event = store.events[0]
        self.assertIs(event.event_type, EventType.ALERT)
        self.assertEqual(event.actor, "notifier")
        self.assertIn("undelivered:CIRCUIT_OPEN", event.payload_ref)
        self.assertEqual(event.run_id, "run-9")

    def test_fallback_channel_prevents_degradation(self) -> None:
        store = _Store()
        failing = WebhookNotifier("https://example.invalid/a", opener=_FailingOpener(urllib.error.URLError("down")))
        console = ConsoleNotifier(sink=lambda _line: None)
        router = NotifierRouter([failing, console], event_store=store)
        result = router.notify(AlertMessage(alert_kind="CONSECUTIVE_FAILURE", message="3 fails"))
        self.assertTrue(result.delivered)
        self.assertEqual(result.channel, "console")
        self.assertFalse(router.degraded)
        self.assertEqual(store.events, [])

    def test_webhook_non_2xx_is_not_delivered(self) -> None:
        webhook = WebhookNotifier("https://example.invalid/hook", opener=_OkOpener(status=500))
        result = webhook.deliver(AlertMessage(alert_kind="GATE_INTEGRATION_ERROR", message="500"))
        self.assertFalse(result.delivered)
        self.assertEqual(result.error, "http_500")

    def test_unknown_alert_kind_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            AlertMessage(alert_kind="UNKNOWN", message="x")
        with self.assertRaises(ValueError):
            AlertMessage(alert_kind="CIRCUIT_OPEN", message="  ")

    def test_dashboard_surfaces_degrated_notifier(self) -> None:
        router = NotifierRouter([])
        router.notify(AlertMessage(alert_kind="SELF_RUN_INTERRUPTED", message="interrupted"))
        dashboard = DashboardService(_EmptyStore(), _Tracker(), _Breaker(), notifier=router)
        summary = dashboard.summary()
        self.assertTrue(summary.notifier_degraded)
        self.assertEqual(summary.undelivered_alerts, 1)

    def test_dashboard_without_notifier_is_not_degraded(self) -> None:
        dashboard = DashboardService(_EmptyStore(), _Tracker(), _Breaker())
        summary = dashboard.summary()
        self.assertFalse(summary.notifier_degraded)
        self.assertEqual(summary.undelivered_alerts, 0)

    def test_result_shape(self) -> None:
        result = DeliveryResult("console", True, 3)
        self.assertTrue(result.delivered)
        self.assertEqual(result.error, "")


if __name__ == "__main__":
    unittest.main()