from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from app.adapters.types import (
    ComponentRef,
    RangeResult,
    UpstreamUnavailable,
    VersionRange,
    compare_versions,
    stricter_range,
)
from app.domain.enums import SourceKind


class VulnSourcePort(Protocol):
    def query(self, component: ComponentRef) -> RangeResult: ...


@dataclass
class OsvSource:
    advisory: dict[tuple[str, str], VersionRange] = field(default_factory=dict)
    fail: bool = False
    calls: int = 0
    source_kind: SourceKind = SourceKind.OSV

    def query(self, component: ComponentRef) -> RangeResult:
        self.calls += 1
        if self.fail:
            raise UpstreamUnavailable("osv", "recorded failure")
        key = (component.name.lower(), component.version)
        version_range = self.advisory.get(key)
        if version_range is None:
            default = self.advisory.get((component.name.lower(), "*"))
            if default is None or not default.contains(component.version):
                raise UpstreamUnavailable("osv", "no affected range")
            version_range = default
        fixed = version_range.fixed_exclusive
        return RangeResult(
            source=self.source_kind,
            affected=version_range,
            fixed=fixed,
            fetched_at=datetime.now(timezone.utc),
            contributing_sources=("OSV",),
            raw_ranges=(version_range,),
        )


@dataclass
class CnvdMirrorSource:
    advisory: dict[str, VersionRange] = field(default_factory=dict)
    fail: bool = False
    calls: int = 0
    source_kind: SourceKind = SourceKind.CNVD

    def query(self, component: ComponentRef) -> RangeResult:
        self.calls += 1
        if self.fail:
            raise UpstreamUnavailable("cnvd", "recorded failure")
        version_range = self.advisory.get(component.name.lower())
        if version_range is None:
            raise UpstreamUnavailable("cnvd", "no mirror entry")
        return RangeResult(
            source=self.source_kind,
            affected=version_range,
            fixed=version_range.fixed_exclusive,
            fetched_at=datetime.now(timezone.utc),
            contributing_sources=("CNVD",),
            raw_ranges=(version_range,),
        )


@dataclass
class VulnQueryOutcome:
    result: RangeResult | None
    degraded: bool
    message: str


class VulnSourceChain:
    def __init__(self, sources: list[VulnSourcePort]):
        if not sources:
            raise ValueError("vuln source chain requires at least one source")
        self.sources = sources

    def query(self, component: ComponentRef) -> VulnQueryOutcome:
        outcomes: list[RangeResult] = []
        failures: list[str] = []
        for source in self.sources:
            try:
                outcomes.append(source.query(component))
            except UpstreamUnavailable as exc:
                failures.append(exc.source)
        if not outcomes:
            return VulnQueryOutcome(
                result=None,
                degraded=True,
                message=f"依赖数据源均不可用: {', '.join(failures) or 'none'}",
            )
        merged = outcomes[0]
        conflict = False
        raw_ranges = list(merged.raw_ranges)
        contributing = list(merged.contributing_sources)
        affected = merged.affected
        for other in outcomes[1:]:
            candidate = stricter_range(affected, other.affected)
            if candidate != affected or candidate != other.affected:
                conflict = True
            affected = candidate
            raw_ranges.extend(other.raw_ranges)
            contributing.extend(other.contributing_sources)
        fixed = affected.fixed_exclusive
        if fixed is None:
            fixed = next((item.fixed for item in outcomes if item.fixed), None)
        needs_human = bool(failures) or conflict
        primary_failed = any(item == "osv" for item in failures)
        return VulnQueryOutcome(
            result=RangeResult(
                source=merged.source if not failures else SourceKind.CNVD,
                affected=affected,
                fixed=fixed,
                fetched_at=datetime.now(timezone.utc),
                conflict=conflict,
                contributing_sources=tuple(dict.fromkeys(contributing)),
                needs_human=needs_human,
                raw_ranges=tuple(raw_ranges),
            ),
            degraded=bool(failures),
            message=(
                "OSV 不可用，已切换 CNVD 兜底（需人工确认）"
                if primary_failed
                else "依赖源区间冲突，已取更严区间"
                if conflict
                else ""
            ),
        )

    def is_affected(self, component: ComponentRef) -> bool:
        outcome = self.query(component)
        if outcome.result is None:
            return False
        return outcome.result.affected.contains(component.version)