"""PERF-02 规模夹具（冻结 1100 Issue / 1000 Run / 12000 Event）。

本模块只构造测试夹具，不含产品逻辑。夹具必须跨进程可重建：
所有带默认时间戳的字段都显式固定，禁止依赖 ``utc_now``。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.enums import EventType, StageTier
from app.domain.models import Event, Run
from app.repo.memory import MemoryStore
from tests.support.mainflow_builder import seed_synthetic

NOW = datetime(2027, 1, 6, 12, 0, tzinfo=timezone.utc)
WINDOW = "2026-12"
TIER = StageTier.PRELIMINARY

PERF02_FULL_ISSUES = 1000
PERF02_REPRO_FAILED = 100
PERF02_ISSUES = 1100
PERF02_RUNS = 1000
EVENTS_PER_RUN = 12
PERF02_EVENTS = 12000

FIXTURE_OBSERVED_AT = datetime(2026, 12, 5, 10, 0, tzinfo=timezone.utc)
EVENT_OCCURRED_AT = NOW - timedelta(minutes=5)


def build_store(
    *,
    full: int = PERF02_FULL_ISSUES,
    repro_failed: int = PERF02_REPRO_FAILED,
    runs: int | None = None,
    events_per_run: int = EVENTS_PER_RUN,
    window: str = WINDOW,
    now: datetime = NOW,
) -> tuple[MemoryStore, dict]:
    """构造确定性 store 并返回 (store, scale)。

    ``runs`` 缺省时对每个 ``ISF-*`` Issue 建 1 个 Run（默认 1000）。
    """
    run_count = full if runs is None else runs
    store = MemoryStore()
    seed_synthetic(store, window, full=full, repro_failed=repro_failed)

    # Issue.updated_at 默认取 utc_now；夹具必须显式固定，否则 digest 跨进程漂移。
    for issue_id in sorted(store.issues):
        issue = store.issues[issue_id]
        store.update(issue.model_copy(update={"updated_at": FIXTURE_OBSERVED_AT}))

    event_total = 0
    for index in range(run_count):
        issue_id = f"ISF-{index + 1:03d}"
        run = Run(
            run_id=f"RUN-{issue_id}",
            issue_id=issue_id,
            started_at=now - timedelta(hours=2),
            deadline_at=now,
        )
        store.add_run(run)
        for seq in range(events_per_run):
            store.append(
                Event(
                    event_id=f"E-{issue_id}-{seq}",
                    run_id=run.run_id,
                    seq=seq + 1,
                    event_type=EventType.INGEST,
                    actor="perf",
                    occurred_at=EVENT_OCCURRED_AT,
                )
            )
            event_total += 1

    scale = {
        "window": window,
        "tier": TIER.value,
        "now": now.astimezone(timezone.utc).isoformat(),
        "full": full,
        "repro_failed": repro_failed,
        "issues": full + repro_failed,
        "runs": run_count,
        "events_per_run": events_per_run,
        "events": event_total,
    }
    return store, scale


def build_perf02_store(now: datetime = NOW) -> tuple[MemoryStore, dict]:
    """PERF-02 冻结规模：1100 Issue / 1000 Run / 12000 Event。"""
    return build_store(now=now)


def build_small_store(now: datetime = NOW) -> tuple[MemoryStore, dict]:
    """最小可复现实体归档夹具：5 Issue / 1 Run / 12 Event。"""
    return build_store(full=5, repro_failed=0, runs=1, events_per_run=12, now=now)