from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.domain.enums import Severity, SourceKind


class UpstreamUnavailable(Exception):
    def __init__(self, source: str, detail: str = ""):
        self.source = source
        self.detail = detail
        super().__init__(f"upstream unavailable ({source})" + (f": {detail}" if detail else ""))


class ScanTaskStatus(str, Enum):
    SUCCESS = "SUCCESS"
    RUNNING = "RUNNING"
    FAILED = "FAILED"


CheckTaskStatus = ScanTaskStatus


@dataclass(frozen=True)
class ScanTaskRef:
    task_id: str


@dataclass(frozen=True)
class RepoRef:
    repo: str
    base_sha: str


@dataclass(frozen=True)
class RawAlert:
    alert_ref: str
    source_kind: SourceKind
    rule_id: str
    file_path: str
    line: int | None
    severity: Severity
    snippet: str = ""
    component: str | None = None
    component_version: str | None = None
    observed_at: datetime | None = None

    def locator_ok(self) -> bool:
        if self.line is not None:
            return True
        return bool(self.component and self.component_version)


@dataclass(frozen=True)
class RawDependencyAlert:
    alert_ref: str
    source_kind: SourceKind
    package: str
    current_version: str
    affected_introduced: str
    fixed_version: str | None
    severity: Severity
    reported_at: datetime | None = None


@dataclass(frozen=True)
class ComponentRef:
    name: str
    version: str


@dataclass(frozen=True)
class VersionRange:
    introduced_inclusive: str
    fixed_exclusive: str | None

    def contains(self, version: str) -> bool:
        if compare_versions(version, self.introduced_inclusive) < 0:
            return False
        if self.fixed_exclusive is None:
            return True
        return compare_versions(version, self.fixed_exclusive) < 0


@dataclass(frozen=True)
class RangeResult:
    source: SourceKind
    affected: VersionRange
    fixed: str | None
    fetched_at: datetime
    conflict: bool = False
    contributing_sources: tuple[str, ...] = ()
    needs_human: bool = False
    raw_ranges: tuple[VersionRange, ...] = ()


def parse_version(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in version.replace("-", ".").split("."):
        if chunk.isdigit():
            parts.append(int(chunk))
        else:
            digits = "".join(character for character in chunk if character.isdigit())
            parts.append(int(digits) if digits else 0)
    return tuple(parts)


def compare_versions(left: str, right: str) -> int:
    left_parts = parse_version(left)
    right_parts = parse_version(right)
    width = max(len(left_parts), len(right_parts))
    padded_left = left_parts + (0,) * (width - len(left_parts))
    padded_right = right_parts + (0,) * (width - len(right_parts))
    if padded_left < padded_right:
        return -1
    if padded_left > padded_right:
        return 1
    return 0


def stricter_range(left: VersionRange, right: VersionRange) -> VersionRange:
    introduced = (
        left.introduced_inclusive
        if compare_versions(left.introduced_inclusive, right.introduced_inclusive) <= 0
        else right.introduced_inclusive
    )
    if left.fixed_exclusive is None or right.fixed_exclusive is None:
        fixed: str | None = None
    else:
        fixed = (
            left.fixed_exclusive
            if compare_versions(left.fixed_exclusive, right.fixed_exclusive) >= 0
            else right.fixed_exclusive
        )
    return VersionRange(introduced_inclusive=introduced, fixed_exclusive=fixed)