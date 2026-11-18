from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.config import AppConfig

FROZEN_PATHS = (
    "branch.namespace",
    "release.auto_branch",
    "patch.max_lines",
    "patch.max_files",
    "patch.strength_l0_l1_min",
)
TUNABLE_PATHS = (
    "suspicion.threshold",
    "circuit.fail_streak",
    "circuit.blacklist_ttl_hours",
    "model.provider",
    "model.max_calls_per_issue",
    "model.call_timeout_seconds",
)
CONFIG_CHANGE_ACTION = "config_change"


class FrozenConfigError(ValueError):
    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"frozen configuration cannot be changed without an exemption record: {path}")


@dataclass(frozen=True)
class ChangeRecord:
    path: str
    old_value: object
    new_value: object
    actor: str
    reason: str
    frozen: bool
    exemption: str
    occurred_at: datetime


def _get(payload: dict, path: str):
    current: object = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"unknown configuration path: {path}")
        current = current[part]
    return current


def _set(payload: dict, path: str, value: object) -> None:
    parts = path.split(".")
    current: dict = payload
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            raise ValueError(f"unknown configuration path: {path}")
        current = current[part]
    current[parts[-1]] = value


def apply_changes(
    config: AppConfig,
    changes: dict[str, object],
    actor: str,
    reason: str,
    writer=None,
    exemption: str = "",
) -> tuple[AppConfig, list[ChangeRecord]]:
    if not actor:
        raise ValueError("actor is required for configuration change")
    payload = config.model_dump()
    known = set(FROZEN_PATHS) | set(TUNABLE_PATHS)
    unknown = sorted(set(changes) - known)
    if unknown:
        raise ValueError("unsupported configuration change: " + ",".join(unknown))
    records: list[ChangeRecord] = []
    for path, value in changes.items():
        frozen = path in FROZEN_PATHS
        if frozen and not exemption:
            raise FrozenConfigError(path)
        old_value = _get(payload, path)
        _set(payload, path, value)
        records.append(
            ChangeRecord(
                path=path,
                old_value=old_value,
                new_value=value,
                actor=actor,
                reason=reason,
                frozen=frozen,
                exemption=exemption if frozen else "",
                occurred_at=datetime.now(timezone.utc),
            )
        )
    updated = AppConfig(**payload)
    if writer is not None:
        for record in records:
            writer.write(
                CONFIG_CHANGE_ACTION,
                record.actor,
                f"old={record.old_value};new={record.new_value};reason={record.reason}"
                + (f";exemption={record.exemption}" if record.exemption else ""),
                record.path,
            )
    return updated, records