from __future__ import annotations

import json
from datetime import datetime, timezone

from app.tools.redactor import SecretRedactor

LOG_FIELDS = ("run_id", "issue_id", "stage", "result", "duration_ms")
ALLOWED_RESULTS = frozenset({"DONE", "FAILED", "SKIPPED", "NOT_RUN"})


class StructuredLogger:
    def __init__(self, sink=None, redactor: SecretRedactor | None = None) -> None:
        self._sink = sink if sink is not None else []
        self.redactor = redactor or SecretRedactor()

    def emit(
        self,
        run_id: str,
        issue_id: str,
        stage: str,
        result: str,
        duration_ms: int,
        **extra: object,
    ) -> dict[str, object]:
        if not run_id or not issue_id or not stage:
            raise ValueError("run_id, issue_id and stage are required")
        if result not in ALLOWED_RESULTS:
            raise ValueError(f"unsupported log result: {result}")
        if not isinstance(duration_ms, int) or duration_ms < 0:
            raise ValueError("duration_ms must be a non-negative integer")
        record: dict[str, object] = {
            "run_id": run_id,
            "issue_id": issue_id,
            "stage": stage,
            "result": result,
            "duration_ms": duration_ms,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }
        safe_extra: dict[str, object] = {}
        redacted_flag = False
        for key, value in extra.items():
            verdict = self.redactor.redact(f"{key}={value}")
            if getattr(verdict, "redacted", False):
                safe_extra[key] = "***REDACTED***"
                redacted_flag = True
            else:
                safe_extra[key] = value
        record.update(safe_extra)
        if redacted_flag:
            record["redacted"] = True
        self._sink.append(record)
        return record

    def records(self) -> list[dict[str, object]]:
        return list(self._sink)

    def by_run(self, run_id: str) -> list[dict[str, object]]:
        return [item for item in self._sink if item.get("run_id") == run_id]

    def text_lines(self) -> list[str]:
        return [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in self._sink]