from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.enums import MetricChannel

EVAL_PREFIX = "eval-"


@dataclass(frozen=True)
class ChannelResolution:
    channel: MetricChannel
    basis: str
    legacy: bool = False

    @property
    def excluded(self) -> bool:
        return self.channel is not MetricChannel.MAIN


@dataclass(frozen=True)
class ChannelExclusion:
    issue_id: str
    detail: str


@dataclass
class ChannelSummary:
    kept: list[str] = field(default_factory=list)
    eval_excluded: list[str] = field(default_factory=list)
    unknown_excluded: list[ChannelExclusion] = field(default_factory=list)

    @property
    def channel_excluded_count(self) -> int:
        return len(self.eval_excluded)

    def exclusion_entries(self) -> list[ChannelExclusion]:
        return list(self.unknown_excluded)


class ChannelResolver:
    def resolve(self, issue) -> ChannelResolution:
        explicit = "channel" in getattr(issue, "model_fields_set", frozenset())
        channel = getattr(issue, "channel", MetricChannel.MAIN)
        if explicit:
            return ChannelResolution(channel=channel, basis="explicit", legacy=False)
        if str(getattr(issue, "code_version", "")).startswith(EVAL_PREFIX):
            return ChannelResolution(channel=MetricChannel.EVAL, basis="legacy_prefix", legacy=True)
        return ChannelResolution(channel=MetricChannel.MAIN, basis="default", legacy=False)

    def summarize(self, issues: list) -> ChannelSummary:
        summary = ChannelSummary()
        for issue in issues:
            resolution = self.resolve(issue)
            if resolution.channel is MetricChannel.MAIN:
                summary.kept.append(issue.issue_id)
            elif resolution.channel is MetricChannel.EVAL:
                summary.eval_excluded.append(issue.issue_id)
            else:
                summary.unknown_excluded.append(
                    ChannelExclusion(issue_id=issue.issue_id, detail="通道不可判")
                )
        return summary