from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.domain.enums import CircuitStatus, DefectClass, DispositionLevel, EventType, IssueStatus
from app.domain.models import Event, Issue, Metric


@dataclass(frozen=True)
class DashboardSummary:
    in_progress: int
    archived: int
    level_distribution: dict[str, int]
    circuit_open_classes: list[str]
    circuit_states: dict[str, str]
    paused: bool
    pause_reason: str
    self_run_hours: float
    interruptions: int
    failure_reasons: list[tuple[str, int]]
    metrics: list[dict]
    generated_at: datetime
    notifier_degraded: bool = False
    undelivered_alerts: int = 0


class DashboardService:
    def __init__(self, store, tracker, breaker, notifier=None):
        self.store = store
        self.tracker = tracker
        self.breaker = breaker
        self.notifier = notifier
        self._event_cursor: dict[str, int] = {}

    def summary(self) -> DashboardSummary:
        issues = list(self.store.issues.values())
        in_progress = sum(
            1 for issue in issues if issue.status not in {
                IssueStatus.ARCHIVED,
                IssueStatus.DISPOSED_L0,
                IssueStatus.DISPOSED_L1,
                IssueStatus.DISPOSED_L2,
                IssueStatus.DISPOSED_L3,
            }
        )
        archived = sum(1 for issue in issues if issue.status is IssueStatus.ARCHIVED)
        levels = {level.value: 0 for level in DispositionLevel}
        for disposition in self.store.dispositions.values():
            levels[disposition.level.value] = levels.get(disposition.level.value, 0) + 1
        reason_counts: dict[str, int] = {}
        for disposition in self.store.dispositions.values():
            reason_counts[disposition.reason_code] = reason_counts.get(disposition.reason_code, 0) + 1
        for issue_id, history in self.store.verdicts.items():
            del issue_id
            for verdict in history:
                if verdict.conclusion.value == "SUSPECTED":
                    reason_counts["SUSPECTED"] = reason_counts.get("SUSPECTED", 0) + 1
        failure_reasons = sorted(reason_counts.items(), key=lambda item: item[1], reverse=True)[:5]
        circuit_states = {
            defect.value: state.state.value for defect, state in self.store.circuits.items()
        }
        open_classes = [name for name, state in circuit_states.items() if state == CircuitStatus.OPEN.value]
        metrics = [
            {
                "metric_id": metric.metric_id.value,
                "value": metric.value,
                "computable": metric.computable,
                "unverified": metric.unverified,
                "unverified_reason": metric.unverified_reason,
                "source_ref": metric.source_ref,
                "computed_at": metric.computed_at.isoformat(),
                "reason_code": metric.reason_code,
                "channel": metric.channel.value,
                "recalc_id": metric.recalc_id,
                "trial": metric.trial,
                "last_success_at": metric.last_success_at.isoformat() if metric.last_success_at else None,
                "last_failure": self._last_failure(metric.metric_id.value),
            }
            for metric in self.store.metrics.values()
        ]
        return DashboardSummary(
            in_progress=in_progress,
            archived=archived,
            level_distribution=levels,
            circuit_open_classes=open_classes,
            circuit_states=circuit_states,
            paused=self.breaker.is_paused(),
            pause_reason=self.breaker.pause_reason(),
            self_run_hours=self.tracker.continuous_hours(),
            interruptions=self.tracker.interruptions(),
            failure_reasons=failure_reasons,
            metrics=metrics,
            generated_at=datetime.now(timezone.utc),
            notifier_degraded=self._notifier_status("degraded"),
            undelivered_alerts=int(self._notifier_status("undelivered_alerts") or 0),
        )

    def _notifier_status(self, key: str):
        if self.notifier is None or not hasattr(self.notifier, "status"):
            return False if key == "degraded" else 0
        return self.notifier.status().get(key, False if key == "degraded" else 0)

    def _last_failure(self, metric_id: str) -> dict | None:
        latest = None
        for run in self.store.recalc_runs.values():
            if run.status != "FAILED":
                continue
            if metric_id not in (run.reason_distribution or {}) and not run.failure_reason:
                continue
            if latest is None or (run.finished_at or run.started_at) > (latest.finished_at or latest.started_at):
                latest = run
        if latest is None:
            return None
        return {
            "recalc_id": latest.recalc_id,
            "finished_at": (latest.finished_at or latest.started_at).isoformat(),
            "reason": latest.failure_reason,
        }

    def events_since(self, run_id: str, since_seq: int = 0) -> list[Event]:
        events = self.store.list_for_run(run_id)
        return [event for event in events if event.seq > since_seq]

    def all_events_since(self, since: dict[str, int] | None = None) -> list[Event]:
        cursor = dict(since or self._event_cursor)
        collected: list[Event] = []
        for run_id in sorted(self.store.events):
            last = cursor.get(run_id, 0)
            new_events = [event for event in self.store.events[run_id] if event.seq > last]
            if new_events:
                cursor[run_id] = new_events[-1].seq
                collected.extend(new_events)
        self._event_cursor = cursor
        return collected

    def cursor(self) -> dict[str, int]:
        return dict(self._event_cursor)

    def register_metric(self, metric: Metric) -> Metric:
        return self.store.add_metric(metric)