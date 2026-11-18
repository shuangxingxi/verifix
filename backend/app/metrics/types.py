from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from app.domain.enums import MetricId, StageTier
from app.domain.models import MetricSnapshotRef
from app.metrics.judgment import MetricComputation


class RecalcTrigger(str, Enum):
    MANUAL = "MANUAL"
    DASHBOARD = "DASHBOARD"
    SCHEDULED = "SCHEDULED"


class RecalcStatus(str, Enum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


def new_recalc_id(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    stamp = current.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    return f"RC-{stamp}-{secrets.token_hex(3)}"


class RecalcConflict(Exception):
    def __init__(self, recalc_id: str):
        self.recalc_id = recalc_id
        super().__init__(f"recalc already in progress: {recalc_id}")


class DefinitionMissing(Exception):
    def __init__(self, metrics: set[MetricId]):
        self.metrics = metrics
        super().__init__("metric definitions missing: " + ",".join(sorted(item.value for item in metrics)))


class RecalcFailed(Exception):
    def __init__(self, recalc_id: str, reason: str):
        self.recalc_id = recalc_id
        self.reason = reason
        super().__init__(f"{recalc_id} failed: {reason}")


@dataclass
class RecalcResult:
    recalc_id: str
    status: RecalcStatus
    window: str
    tier: StageTier
    trigger: RecalcTrigger
    actor: str
    computations: dict[MetricId, MetricComputation] = field(default_factory=dict)
    snapshot: MetricSnapshotRef | None = None
    failure_reason: str = ""
    late: bool = False

    @property
    def succeeded(self) -> bool:
        return self.status is RecalcStatus.SUCCESS