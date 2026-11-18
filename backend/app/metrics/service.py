from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from app.domain.enums import MetricChannel, MetricId, StageTier
from app.domain.models import ExclusionEntry, Metric, RecalcRun
from app.metrics.collectors.main_flow import MainFlowEvidenceCollector
from app.metrics.definitions import DefinitionRegistry
from app.metrics.judgment import ComputabilityPipeline, MetricComputation
from app.metrics.reason_codes import UncomputableReason
from app.metrics.reporting import build_source_ref
from app.metrics.rules import M1Rule, M2Rule, M3Rule, M4Rule, M5Rule, M6Rule, M7Rule, M8Rule, M9Rule
from app.metrics.rules.base import RuleResult
from app.metrics.snapshot import SnapshotBuilder, SnapshotVerifier
from app.metrics.types import (
    DefinitionMissing,
    RecalcConflict,
    RecalcFailed,
    RecalcResult,
    RecalcStatus,
    RecalcTrigger,
    new_recalc_id,
)

DEFAULT_RULES = {
    MetricId.M1: M1Rule(),
    MetricId.M2: M2Rule(),
    MetricId.M3: M3Rule(),
    MetricId.M4: M4Rule(),
    MetricId.M5: M5Rule(),
    MetricId.M6: M6Rule(),
    MetricId.M7: M7Rule(),
    MetricId.M8: M8Rule(),
    MetricId.M9: M9Rule(),
}


class RecalcGuard:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: dict[tuple[str, str], str] = {}

    @contextmanager
    def acquire(self, window: str, tier: StageTier, recalc_id: str):
        key = (window, tier.value)
        with self._lock:
            current = self._active.get(key)
            if current is not None:
                raise RecalcConflict(current)
            self._active[key] = recalc_id
        try:
            yield
        finally:
            with self._lock:
                self._active.pop(key, None)

    def active(self, window: str, tier: StageTier) -> str | None:
        with self._lock:
            return self._active.get((window, tier.value))


class RecalcService:
    def __init__(
        self,
        store,
        evidence,
        config,
        definitions: DefinitionRegistry | None = None,
        builder: SnapshotBuilder | None = None,
        verifier: SnapshotVerifier | None = None,
        guard: RecalcGuard | None = None,
        collector: MainFlowEvidenceCollector | None = None,
        rules: dict | None = None,
        pipeline: ComputabilityPipeline | None = None,
        clock=None,
        late: bool = False,
    ) -> None:
        self.store = store
        self.config = config
        self.definitions = definitions or DefinitionRegistry()
        self.evidence = evidence
        self.builder = builder or SnapshotBuilder(store, evidence)
        self.verifier = verifier or SnapshotVerifier(evidence)
        self.guard = guard or RecalcGuard()
        self.collector = collector or MainFlowEvidenceCollector()
        self.rules = rules or DEFAULT_RULES
        self.pipeline = pipeline or ComputabilityPipeline(config.metrics.exclusion_ratio_limit)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.late = late

    def recalc(
        self,
        window: str,
        tier: StageTier,
        trigger: RecalcTrigger,
        actor: str,
        now: datetime | None = None,
        late: bool | None = None,
    ) -> RecalcResult:
        current = self._now(now)
        effective_late = self.late if late is None else late
        recalc_id = new_recalc_id(current)
        with self.guard.acquire(window, tier, recalc_id):
            running = RecalcRun(
                recalc_id=recalc_id,
                window=window,
                tier=tier,
                trigger=trigger.value if isinstance(trigger, RecalcTrigger) else str(trigger),
                actor=actor,
                status=RecalcStatus.RUNNING.value,
                started_at=current,
                late=effective_late,
            )
            self.store.put_recalc(running)

            missing = self.definitions.missing(current)
            if missing:
                self._mark_failed(running, current, UncomputableReason.DEFINITION_UNREGISTERED.value)
                raise DefinitionMissing(missing)

            try:
                envelope = self.builder.capture(window, tier)
            except Exception as exc:
                self._mark_failed(running, current, f"快照抓取失败：{exc}")
                raise RecalcFailed(recalc_id, f"快照抓取失败：{exc}") from exc

            try:
                report = self.verifier.verify(envelope.ref.snapshot_id, envelope.ref.digest)
            except Exception as exc:
                self._mark_failed(running, current, f"快照校验失败：{exc}")
                raise RecalcFailed(recalc_id, f"快照校验失败：{exc}") from exc
            if not report.digest_match or not report.chain_valid:
                reason = "快照摘要不一致" if not report.digest_match else f"事件链断裂：{','.join(report.broken_runs)}"
                self._mark_failed(running, current, reason)
                raise RecalcFailed(recalc_id, reason)

            evidence = self.collector.build(
                envelope.payload,
                snapshot_id=envelope.ref.snapshot_id,
                snapshot_digest=envelope.ref.digest,
                now=current,
            )

            computations: dict[MetricId, MetricComputation] = {}
            rule_results: dict[MetricId, RuleResult] = {}
            for metric_id in MetricId:
                definition = self.definitions.effective(metric_id, current)
                rule = self.rules[metric_id]
                result = rule.evaluate(evidence, definition, current)
                rule_results[metric_id] = result
                computations[metric_id] = self.pipeline.evaluate(
                    metric_id, definition, result, evidence, current
                )

            try:
                with self.store.transaction():
                    for metric_id, computation in computations.items():
                        record = self._metric_record(
                            metric_id,
                            computation,
                            window,
                            tier,
                            recalc_id,
                            envelope.ref,
                            current,
                        )
                        self.store.add_metric(record)
                        self.store.put_exclusions(
                            recalc_id,
                            metric_id,
                            [
                                ExclusionEntry(
                                    issue_id=item.issue_id,
                                    reason_code=item.reason_code.value,
                                    detail=item.detail,
                                    metric_id=metric_id,
                                    recalc_id=recalc_id,
                                )
                                for item in computation.exclusions
                            ],
                        )
                    self.store.put_snapshot(envelope.ref)
                    distribution: dict[str, int] = {}
                    for computation in computations.values():
                        if computation.reason_code is not None:
                            code = computation.reason_code.value
                            distribution[code] = distribution.get(code, 0) + 1
                    finished = running.model_copy(
                        update={
                            "status": RecalcStatus.SUCCESS.value,
                            "finished_at": current,
                            "definition_versions": sorted({item.definition_version for item in computations.values()}),
                            "issue_total": len(evidence.issues),
                            "excluded_total": sum(item.excluded_count for item in computations.values()),
                            "reason_distribution": distribution,
                            "failure_reason": "",
                        }
                    )
                    self.store.update_recalc(finished)
            except Exception as exc:
                self._mark_failed(running, current, f"复算写入失败：{exc}")
                raise RecalcFailed(recalc_id, f"复算写入失败：{exc}") from exc

            return RecalcResult(
                recalc_id=recalc_id,
                status=RecalcStatus.SUCCESS,
                window=window,
                tier=tier,
                trigger=trigger if isinstance(trigger, RecalcTrigger) else RecalcTrigger(str(trigger)),
                actor=actor,
                computations=computations,
                snapshot=envelope.ref,
                late=effective_late,
            )

    def _metric_record(
        self,
        metric_id: MetricId,
        computation: MetricComputation,
        window: str,
        tier: StageTier,
        recalc_id: str,
        snapshot,
        now: datetime,
    ) -> Metric:
        key = (metric_id.value, tier.value, window)
        previous = self.store.metrics.get(key)
        last_success = previous.computed_at if previous is not None else None
        return Metric(
            metric_id=metric_id,
            stage_tier=tier,
            window=window,
            definition_version=computation.definition_version,
            value=computation.value,
            source_ref=build_source_ref(computation),
            computed_at=now,
            computable=computation.computable,
            reason_code=computation.reason_code.value if computation.reason_code else None,
            channel=MetricChannel.MAIN,
            recalc_id=recalc_id,
            snapshot_id=snapshot.snapshot_id,
            snapshot_digest=snapshot.digest,
            numerator=computation.numerator,
            denominator=float(computation.denominator),
            covered_count=computation.covered_count,
            excluded_count=computation.excluded_count,
            channel_excluded_count=computation.channel_excluded_count,
            not_applicable_count=computation.not_applicable_count,
            exclusion_ref=f"{recalc_id}:{metric_id.value}",
            trial=computation.trial,
            last_success_at=last_success,
            unverified=computation.unverified,
            unverified_reason=computation.unverified_reason,
        )

    def _mark_failed(self, running: RecalcRun, now: datetime, reason: str) -> None:
        self.store.update_recalc(
            running.model_copy(
                update={
                    "status": RecalcStatus.FAILED.value,
                    "finished_at": now,
                    "failure_reason": reason,
                }
            )
        )

    def _now(self, now: datetime | None) -> datetime:
        current = now or self.clock()
        if current.tzinfo is None:
            return current.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc)