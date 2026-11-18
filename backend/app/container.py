from __future__ import annotations

from dataclasses import dataclass, field

from app.config import AppConfig
from app.ops.structured_log import StructuredLogger
from app.orchestration.guards import ConcurrencyController, RetryPolicy, RunDeadlineGuard
from app.orchestration.service import OrchestrationService
from app.orchestration.state_machine import StateMachine
from app.repo.memory import MemoryStore


@dataclass
class AppContainer:
    config: AppConfig
    store: MemoryStore = field(default_factory=MemoryStore)
    state_machine: StateMachine = field(default_factory=StateMachine)
    concurrency: ConcurrencyController | None = None
    deadline_guard: RunDeadlineGuard | None = None
    retry_policy: RetryPolicy | None = None
    recalc_guard: object | None = None
    recalc_service: object | None = None
    recalc_scheduler: object | None = None
    logger: StructuredLogger = field(default_factory=StructuredLogger)

    def __post_init__(self) -> None:
        self.concurrency = ConcurrencyController(self.config.run.max_concurrency)
        self.deadline_guard = RunDeadlineGuard(self.config.run.deadline_seconds)
        self.retry_policy = RetryPolicy()

    def orchestration(self) -> OrchestrationService:
        return OrchestrationService(self.store, self.store, self.store, self.state_machine, self.logger)