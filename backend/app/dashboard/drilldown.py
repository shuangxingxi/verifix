from __future__ import annotations

from app.domain.enums import MetricChannel, MetricId, StageTier


class DrilldownMismatch(Exception):
    pass


class MetricDrilldownService:
    def __init__(self, store, verifier=None) -> None:
        self.store = store
        self.verifier = verifier

    def drilldown(self, metric_id: MetricId, tier: StageTier, window: str) -> dict | None:
        record = self.store.metrics.get((metric_id.value, tier.value, window))
        if record is None:
            return None
        exclusions = [
            {
                "issue_id": item.issue_id,
                "reason_code": item.reason_code,
                "detail": item.detail,
            }
            for item in self.store.exclusions(record.recalc_id, metric_id)
        ] if record.recalc_id else []
        snapshot = self.store.get_snapshot(record.snapshot_id) if record.snapshot_id else None
        verifiable = False
        detail = ""
        issues: list[str] = []
        if snapshot is None:
            detail = "快照不可用，指标值保留但证据不可校验"
        elif self.verifier is None:
            detail = "未配置快照校验器"
        else:
            try:
                report = self.verifier.verify(snapshot.snapshot_id, snapshot.digest)
            except Exception as exc:
                detail = f"快照不可用：{exc}"
                report = None
            if report is not None:
                verifiable = bool(report.digest_match and report.chain_valid)
                if not verifiable:
                    detail = "快照摘要或事件链校验失败"
                else:
                    payload = self.verifier.load(snapshot.snapshot_id, snapshot.digest)
                    issues = [
                        issue_id
                        for issue_id, annotation in (payload.get("annotations") or {}).items()
                        if annotation.get("channel") == MetricChannel.MAIN.value and annotation.get("window_owner")
                    ]
        return {
            "metric_id": record.metric_id.value,
            "window": record.window,
            "tier": record.stage_tier.value,
            "value": record.value,
            "computable": record.computable,
            "reason_code": record.reason_code,
            "recalc_id": record.recalc_id,
            "snapshot_id": record.snapshot_id,
            "snapshot_digest": record.snapshot_digest,
            "covered_count": record.covered_count,
            "excluded_count": record.excluded_count,
            "channel_excluded_count": record.channel_excluded_count,
            "not_applicable_count": record.not_applicable_count,
            "issues": issues,
            "exclusions": exclusions,
            "verifiable": verifiable,
            "detail": detail,
        }