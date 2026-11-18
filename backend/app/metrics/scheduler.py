from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.enums import StageTier
from app.metrics.snapshot import window_bounds
from app.metrics.types import RecalcConflict, RecalcTrigger, RecalcResult

SCHEDULER_ACTOR = "scheduler:metrics"


def previous_windows(now: datetime, count: int = 12) -> list[str]:
    windows: list[str] = []
    year, month = now.year, now.month
    for _ in range(count):
        windows.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return windows


class RecalcScheduler:
    def __init__(self, service, store, config, clock=None) -> None:
        self.service = service
        self.store = store
        self.config = config
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._attempted: set[str] = set()
        self.skipped_locked = 0

    def tick(self, now: datetime | None = None) -> list[RecalcResult]:
        if not self.config.metrics.scheduler_enabled:
            return []
        current = now or self.clock()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        results: list[RecalcResult] = []
        for window in previous_windows(current):
            for tier in (StageTier.PRELIMINARY,):
                if self._archived(window, tier):
                    continue
                if not self._due(window, tier, current):
                    continue
                key = f"scheduler:{window}:{tier.value}:{current.astimezone(timezone.utc).date().isoformat()}"
                if key in self._attempted:
                    continue
                self._attempted.add(key)
                start, end = window_bounds(window)
                late = (not self._success(window, tier)) and current > end + timedelta(
                    seconds=self.config.metrics.recalc_on_close_delay_seconds
                )
                try:
                    result = self.service.recalc(
                        window,
                        tier,
                        RecalcTrigger.SCHEDULED,
                        SCHEDULER_ACTOR,
                        now=current,
                        late=late,
                    )
                except RecalcConflict:
                    self.skipped_locked += 1
                    continue
                results.append(result)
        return results

    def _archived(self, window: str, tier: StageTier) -> bool:
        return any(
            report.window == window and report.tier is tier
            for report in self.store.metric_reports.values()
        )

    def _success(self, window: str, tier: StageTier):
        runs = [
            run
            for run in self.store.recalc_runs.values()
            if run.window == window and run.tier is tier and run.status == "SUCCESS"
        ]
        return max(runs, key=lambda run: run.finished_at or run.started_at) if runs else None

    def _due(self, window: str, tier: StageTier, now: datetime) -> bool:
        start, end = window_bounds(window)
        last = self._success(window, tier)
        if last is None:
            return now >= end + timedelta(seconds=self.config.metrics.recalc_on_close_delay_seconds)
        finished = last.finished_at or last.started_at
        return (now - finished).total_seconds() >= self.config.metrics.daily_recalc_seconds