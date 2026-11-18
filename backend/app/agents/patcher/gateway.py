from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class TaskKind(str, Enum):
    REPRO_GEN = "repro_gen"
    PATCH_GEN = "patch_gen"
    CONTEXT_ADAPT = "context_adapt"


class ModelBudgetExceeded(Exception):
    def __init__(self, issue_id: str, max_calls: int):
        self.issue_id = issue_id
        self.max_calls = max_calls
        super().__init__(f"model budget exceeded for {issue_id}: max {max_calls} calls")


class ModelOutputRejected(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"model output rejected: {reason}")


class BugContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: str = Field(min_length=1)
    rule_id: str = Field(min_length=1)
    defect_class: str = Field(min_length=1)
    file: str = Field(min_length=1)
    line: int = Field(ge=1)
    code_context: str = ""
    reachability_path: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class ModelResult:
    content: str
    provider: str
    latency_ms: int
    tokens: int = 0


@dataclass(frozen=True)
class CostEstimate:
    budget_yuan: float


@dataclass(frozen=True)
class ProviderHealth:
    healthy: bool
    detail: str = ""


class ModelProvider(Protocol):
    name: str

    def infer(self, task: TaskKind, payload: dict) -> ModelResult: ...

    def health(self) -> ProviderHealth: ...

    def estimate_cost(self, task: TaskKind, payload: dict) -> CostEstimate: ...


class ModelGateway:
    def __init__(
        self,
        provider: ModelProvider,
        max_calls_per_issue: int = 5,
        timeout_seconds: int = 60,
    ):
        self.provider = provider
        self.max_calls_per_issue = max(1, min(max_calls_per_issue, 5))
        self.timeout_seconds = max(1, min(timeout_seconds, 60))
        self._calls: dict[str, int] = {}
        self._history: list[dict] = []
        self.model_provider_name = provider.name

    def calls_for(self, issue_id: str) -> int:
        return self._calls.get(issue_id, 0)

    def _charge(self, ctx: BugContext) -> None:
        used = self._calls.get(ctx.issue_id, 0)
        if used >= self.max_calls_per_issue:
            raise ModelBudgetExceeded(ctx.issue_id, self.max_calls_per_issue)
        self._calls[ctx.issue_id] = used + 1

    def generate_patch(self, ctx: BugContext) -> dict:
        self._charge(ctx)
        payload = ctx.model_dump()
        result = self.provider.infer(TaskKind.PATCH_GEN, payload)
        self._history.append(
            {
                "issue_id": ctx.issue_id,
                "task": TaskKind.PATCH_GEN.value,
                "provider": result.provider,
                "latency_ms": result.latency_ms,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return self._validate_patch_output(result.content)

    def generate_test(self, ctx: BugContext) -> dict:
        self._charge(ctx)
        result = self.provider.infer(TaskKind.REPRO_GEN, ctx.model_dump())
        return self._validate_json(result.content, required=("test_path", "content"))

    def adapt_context(self, ctx: BugContext) -> str:
        self._charge(ctx)
        result = self.provider.infer(TaskKind.CONTEXT_ADAPT, ctx.model_dump())
        return result.content

    def _validate_patch_output(self, content: str) -> dict:
        payload = self._validate_json(content, required=("files", "fix_paradigm"))
        files = payload.get("files")
        if not isinstance(files, dict) or not files:
            raise ModelOutputRejected("patch output must contain a non-empty files mapping")
        for path, body in files.items():
            if not isinstance(path, str) or not path:
                raise ModelOutputRejected("invalid file path in patch output")
            if not isinstance(body, str):
                raise ModelOutputRejected("file content must be a string")
            try:
                compile(body, path, "exec")
            except SyntaxError as exc:
                raise ModelOutputRejected(f"syntax error in {path}: {exc.msg}") from exc
        return payload

    def _validate_json(self, content: str, required: tuple[str, ...]) -> dict:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ModelOutputRejected(f"invalid json: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ModelOutputRejected("output must be a json object")
        missing = [key for key in required if key not in payload]
        if missing:
            raise ModelOutputRejected(f"missing keys: {', '.join(missing)}")
        return payload

    def history(self) -> list[dict]:
        return list(self._history)


@dataclass
class FakeProvider:
    name: str = "fake"
    payload: str = "{}"
    healthy: bool = True
    calls: list[tuple[TaskKind, dict]] = field(default_factory=list)

    def infer(self, task: TaskKind, payload: dict) -> ModelResult:
        self.calls.append((task, payload))
        return ModelResult(content=self.payload, provider=self.name, latency_ms=5, tokens=10)

    def health(self) -> ProviderHealth:
        return ProviderHealth(healthy=self.healthy)

    def estimate_cost(self, task: TaskKind, payload: dict) -> CostEstimate:
        del task, payload
        return CostEstimate(budget_yuan=0.01)