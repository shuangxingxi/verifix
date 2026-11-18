from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.api.config_api import ConfigChangeRequest
from app.api.envelope import ApiError, Envelope, ErrorCode, ok_response, register_exception_handlers
from app.config import AppConfig, load_config
from app.container import AppContainer
from app.dashboard.drilldown import MetricDrilldownService
from app.dashboard.evidence_view import DispositionInspector
from app.dashboard.service import DashboardService
from app.domain.enums import DefectClass, MetricId, StageTier, VerdictConclusion
from app.domain.models import SCHEMA_VERSION
from app.evidence.replay import ReplayService
from app.eval.adjudication import AdjudicationService
from app.eval.loader import ExpectedAnswerReader
from app.eval.runner import EvalRunner
from app.evidence.store import LocalEvidenceStore
from app.intake.auth import AuthGuard, RateLimiter
from app.intake.dedup import DedupService
from app.intake.normalizer import IssueNormalizer
from app.intake.schedule import ScheduleTriggerInput, ScheduledTriggerService
from app.intake.service import IntakeService, ManualIssueInput
from app.intake.triggers import CvePayload, RepoWebhookPayload, RuntimeAlertPayload, TriggerService
from app.metrics.collectors.eval_channel import EvalConclusionReader, read_binding_digest
from app.metrics.collectors.main_flow import MainFlowEvidenceCollector
from app.metrics.collectors.runtime_sampler import SelfRunSampleReader
from app.metrics.report import MetricReportService, ReportInconsistent
from app.metrics.scheduler import RecalcScheduler
from app.metrics.service import RecalcGuard, RecalcService
from app.metrics.snapshot import SnapshotIntegrityError, SnapshotNotFound, SnapshotVerifier
from app.metrics.types import DefinitionMissing, RecalcConflict, RecalcFailed, RecalcTrigger
from app.readiness import readiness_snapshot
from app.runtime.circuit import CircuitBreaker
from app.runtime.control import ControlEventWriter
from app.runtime.self_run import SelfRunTracker
from app.runtime.supervisor import RuntimeSupervisor
from app.tracing.service import ReachabilityService


class HealthStatus(BaseModel):
    status: str
    brand: str
    branch_namespace: str
    release_auto_branch: str
    deadline_seconds: int


class MetaInfo(BaseModel):
    brand: str
    branch_namespace: str
    release_auto_branch: str
    deadline_seconds: int
    max_concurrency: int
    model_provider: str
    model_calls_per_issue: int
    schema_version: int
    webhook_auth_configured: bool


class IssueAccepted(BaseModel):
    issue_id: str
    run_id: str
    status: str
    idempotent: bool
    in_scope: bool


class ReviewInput(BaseModel):
    actor: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    conclusion: VerdictConclusion | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class ControlInput(BaseModel):
    actor: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class HeartbeatInfo(BaseModel):
    healthy: bool
    self_run_hours: float
    interruptions: int


class RecalcInput(BaseModel):
    window: str = Field(min_length=7, max_length=7)
    tier: StageTier = StageTier.PRELIMINARY
    trigger: RecalcTrigger = RecalcTrigger.MANUAL


def _metric_payload(metric) -> dict:
    return {
        "metric_id": metric.metric_id.value,
        "stage_tier": metric.stage_tier.value,
        "window": metric.window,
        "value": metric.value,
        "computable": metric.computable,
        "source_ref": metric.source_ref,
        "definition_version": metric.definition_version,
        "reason_code": metric.reason_code,
        "channel": metric.channel.value,
        "recalc_id": metric.recalc_id,
        "snapshot_id": metric.snapshot_id,
        "numerator": metric.numerator,
        "denominator": metric.denominator,
        "covered_count": metric.covered_count,
        "excluded_count": metric.excluded_count,
        "channel_excluded_count": metric.channel_excluded_count,
        "not_applicable_count": metric.not_applicable_count,
        "trial": metric.trial,
        "computed_at": metric.computed_at.isoformat(),
        "last_success_at": metric.last_success_at.isoformat() if metric.last_success_at else None,
    }


class EvalStartInput(BaseModel):
    set_path: str | None = None
    digest: str | None = None
    set_version: str | None = None
    actor: str = "exec"


def create_app(config: AppConfig | None = None, container: AppContainer | None = None) -> FastAPI:
    resolved = config or load_config()
    box = container or AppContainer(resolved)
    intake = IntakeService(box.store, resolved)
    replay_service = ReplayService(box.store)
    reachability = ReachabilityService(box.store, resolved, box.state_machine)
    schedule = ScheduledTriggerService(box.store)
    normalizer = IssueNormalizer(box.store, DedupService(box.store), resolved)
    webhook_secret = os.environ.get("VERIFIX_WEBHOOK_SECRET", "dev-secret")
    auth = AuthGuard(secret=webhook_secret)
    triggers = TriggerService(normalizer, resolved, auth, RateLimiter())
    breaker = CircuitBreaker(box.store, resolved.circuit.fail_streak, resolved.circuit.blacklist_ttl_hours)
    tracker = SelfRunTracker()
    dashboard = DashboardService(box.store, tracker, breaker)
    evidence_root = Path(os.environ.get("VERIFIX_EVIDENCE_ROOT", ".evidence"))
    evidence = LocalEvidenceStore(evidence_root)
    control_writer = ControlEventWriter(box.store)
    supervisor = RuntimeSupervisor(box.store, box.deadline_guard)
    inspector = DispositionInspector(box.store, evidence)
    project_root = Path(__file__).resolve().parents[2]
    eval_runner = EvalRunner(resolved, project_root / "verifix-target", project_root / "eval" / "runs")
    eval_answer_reader = ExpectedAnswerReader(
        project_root / resolved.eval.expected_dir, eval_runner.audit, resolved.eval.set_version
    )
    adjudicator = AdjudicationService(project_root / "eval" / "verdicts")
    sample_path = Path(resolved.metrics.self_run_sample_path)
    if not sample_path.is_absolute():
        sample_path = project_root / sample_path
    sample_reader = SelfRunSampleReader(sample_path)
    metrics_root = Path(resolved.metrics.snapshot_dir)
    if not metrics_root.is_absolute():
        metrics_root = project_root / metrics_root
    metrics_evidence = LocalEvidenceStore(metrics_root)
    eval_run_dir = Path(resolved.metrics.eval_run_dir)
    if not eval_run_dir.is_absolute():
        eval_run_dir = project_root / eval_run_dir
    eval_binding_digest = read_binding_digest(project_root / resolved.eval.cases_dir / "manifest.json")
    eval_reader = EvalConclusionReader(
        eval_run_dir,
        eval_binding_digest,
        verdict_dir=project_root / "eval" / "verdicts",
    )
    recalc_collector = MainFlowEvidenceCollector(
        sample_reader,
        eval_reader,
        eval_binding_digest,
    )
    recalc_guard = RecalcGuard()
    recalc_service = RecalcService(
        box.store,
        metrics_evidence,
        resolved,
        guard=recalc_guard,
        collector=recalc_collector,
    )
    recalc_scheduler = RecalcScheduler(recalc_service, box.store, resolved)
    snapshot_verifier = SnapshotVerifier(metrics_evidence)
    report_dir = Path(resolved.metrics.report_dir)
    if not report_dir.is_absolute():
        report_dir = project_root / report_dir
    report_service = MetricReportService(box.store, report_dir=report_dir)
    drilldown_service = MetricDrilldownService(box.store, snapshot_verifier)
    box.recalc_guard = recalc_guard
    box.recalc_service = recalc_service
    box.recalc_scheduler = recalc_scheduler

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.config = resolved
        app.state.container = box
        app.state.breaker = breaker
        app.state.tracker = tracker
        app.state.dashboard = dashboard
        app.state.evidence = evidence
        app.state.recalc_service = recalc_service
        scheduler_task = None
        if resolved.metrics.scheduler_enabled:

            async def _scheduler_loop() -> None:
                while True:
                    try:
                        recalc_scheduler.tick()
                    except Exception:
                        pass
                    await asyncio.sleep(max(1, resolved.metrics.scheduler_tick_seconds))

            scheduler_task = asyncio.create_task(_scheduler_loop())
        try:
            yield
        finally:
            if scheduler_task is not None:
                scheduler_task.cancel()
                try:
                    await scheduler_task
                except (asyncio.CancelledError, Exception):
                    pass

    app = FastAPI(
        title=f"{resolved.product.brand} API",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.config = resolved
    app.state.container = box
    app.state.breaker = breaker
    app.state.tracker = tracker
    app.state.dashboard = dashboard
    app.state.evidence = evidence
    register_exception_handlers(app)

    @app.middleware("http")
    async def trace_middleware(request: Request, call_next):
        trace_id = request.headers.get("x-trace-id") or uuid.uuid4().hex
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["x-trace-id"] = trace_id
        return response

    def envelope_json(data, trace_id: str, status_code: int = 200, code=0, message: str = "ok") -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content=jsonable_encoder(Envelope(code=code, message=message, data=data, trace_id=trace_id)),
        )

    @app.get("/healthz")
    async def healthz(request: Request):
        return ok_response(
            HealthStatus(
                status="ok",
                brand=resolved.product.brand,
                branch_namespace=resolved.branch.namespace,
                release_auto_branch=resolved.release.auto_branch,
                deadline_seconds=resolved.run.deadline_seconds,
            ),
            trace_id=request.state.trace_id,
        )

    @app.get("/readyz")
    async def readyz(request: Request):
        return envelope_json(readiness_snapshot(resolved), request.state.trace_id)

    @app.get("/api/v1/meta")
    async def meta(request: Request):
        return ok_response(
            MetaInfo(
                brand=resolved.product.brand,
                branch_namespace=resolved.branch.namespace,
                release_auto_branch=resolved.release.auto_branch,
                deadline_seconds=resolved.run.deadline_seconds,
                max_concurrency=resolved.run.max_concurrency,
                model_provider=resolved.model.provider,
                model_calls_per_issue=resolved.model.max_calls_per_issue,
                schema_version=SCHEMA_VERSION,
                webhook_auth_configured=webhook_secret != "dev-secret",
            ),
            trace_id=request.state.trace_id,
        )

    @app.post("/api/v1/issues")
    async def submit_issue(payload: ManualIssueInput, request: Request):
        actor = request.headers.get("x-actor", "manual-submit")
        result = intake.submit_manual(payload, actor=actor)
        accepted = IssueAccepted(
            issue_id=result.issue_id,
            run_id=result.run_id,
            status=result.status.value,
            idempotent=result.idempotent,
            in_scope=result.in_scope,
        )
        if result.idempotent:
            return envelope_json(accepted, request.state.trace_id, 202, ErrorCode.IDEMPOTENT_HIT.value, "幂等命中")
        if breaker.is_paused():
            control_writer.write("queue_by_pause", actor, breaker.pause_reason(), result.issue_id)
            return envelope_json(
                accepted,
                request.state.trace_id,
                202,
                0,
                "自动处置已暂停，任务已排队（QUEUED_BY_PAUSE）",
            )
        if not result.in_scope:
            return envelope_json(accepted, request.state.trace_id, 202, ErrorCode.OUT_OF_SCOPE.value, "范围外：已归档")
        return envelope_json(accepted, request.state.trace_id, 202, 0, "accepted")

    @app.get("/api/v1/issues")
    async def list_issues(request: Request, status: str | None = None, limit: int = 50):
        issues = list(box.store.issues.values())
        if status:
            issues = [issue for issue in issues if issue.status.value == status.upper()]
        issues = sorted(issues, key=lambda item: item.occurred_at, reverse=True)[: max(1, min(limit, 200))]
        return envelope_json(issues, request.state.trace_id)

    @app.get("/api/v1/issues/{issue_id}")
    async def issue_detail(issue_id: str, request: Request):
        try:
            issue = box.store.get(issue_id)
        except KeyError as exc:
            raise ApiError(ErrorCode.EVIDENCE_MISSING, f"issue {issue_id} not found") from exc
        data = {
            "issue": issue,
            "verdict": box.store.effective(issue_id),
            "proof": box.store.proof_for(issue_id),
            "patch": box.store.patch_for(issue_id),
            "disposition": box.store.disposition_for(issue_id),
            "alerts": box.store.alerts_for(issue_id),
        }
        return envelope_json(data, request.state.trace_id)

    @app.post("/api/v1/issues/{issue_id}/retry")
    async def retry_issue(issue_id: str, request: Request):
        try:
            issue = box.store.get(issue_id)
        except KeyError as exc:
            raise ApiError(ErrorCode.EVIDENCE_MISSING, f"issue {issue_id} not found") from exc
        box.store.enqueue(f"retry:{issue_id}:{uuid.uuid4().hex[:8]}", "retry", f"issue/{issue_id}")
        control_writer.write("retry", request.headers.get("x-actor", "operator"), "manual retry", issue_id)
        return envelope_json(
            {"issue_id": issue_id, "queued": True, "status": issue.status.value},
            request.state.trace_id,
            202,
        )

    @app.post("/api/v1/issues/{issue_id}/handoff")
    async def handoff_issue(issue_id: str, payload: ControlInput, request: Request):
        try:
            issue = box.store.get(issue_id)
        except KeyError as exc:
            raise ApiError(ErrorCode.EVIDENCE_MISSING, f"issue {issue_id} not found") from exc
        control_writer.write("handoff", payload.actor, payload.reason, issue_id)
        return envelope_json(
            {"issue_id": issue_id, "handoff": True, "status": issue.status.value},
            request.state.trace_id,
            202,
        )

    @app.get("/api/v1/issues/{issue_id}/disposition")
    async def issue_disposition(issue_id: str, request: Request):
        view = inspector.inspect(issue_id)
        if view is None:
            raise ApiError(ErrorCode.EVIDENCE_MISSING, f"issue {issue_id} has no disposition")
        if not view.conclusion_trusted:
            raise ApiError(ErrorCode.EVIDENCE_MISSING, "证据缺失，结论不可信")
        return envelope_json(view, request.state.trace_id)

    @app.post("/api/v1/metrics/recalc")
    async def metrics_recalc(payload: RecalcInput, request: Request):
        actor = (request.headers.get("x-actor") or "").strip()
        if not actor:
            raise ApiError(ErrorCode.UNAUTHORIZED, "x-actor is required")
        expected_token = resolved.metrics.operator_token
        if expected_token and request.headers.get("x-operator-token") != expected_token:
            raise ApiError(ErrorCode.UNAUTHORIZED, "operator token invalid")
        try:
            result = recalc_service.recalc(payload.window, payload.tier, payload.trigger, actor)
        except RecalcConflict as exc:
            raise ApiError(ErrorCode.RECALC_CONFLICT, f"recalc {exc.recalc_id} in progress") from exc
        except DefinitionMissing as exc:
            raise ApiError(ErrorCode.DEFINITION_MISSING, str(exc)) from exc
        except RecalcFailed as exc:
            raise ApiError(ErrorCode.RECALC_FAILED, f"{exc.recalc_id}: {exc.reason}") from exc
        metrics = [
            _metric_payload(metric)
            for metric in recalc_service.store.metrics_for(payload.window, payload.tier)
            if metric.recalc_id == result.recalc_id
        ]
        return envelope_json(
            {
                "recalc_id": result.recalc_id,
                "status": result.status.value,
                "window": result.window,
                "tier": result.tier.value,
                "trigger": result.trigger.value,
                "actor": result.actor,
                "late": result.late,
                "snapshot_id": result.snapshot.snapshot_id if result.snapshot else None,
                "metrics": metrics,
            },
            request.state.trace_id,
            202,
        )

    @app.get("/api/v1/metrics/recalc/{recalc_id}")
    async def metrics_recalc_status(recalc_id: str, request: Request):
        run = recalc_service.store.get_recalc(recalc_id)
        if run is None:
            raise ApiError(ErrorCode.EVIDENCE_MISSING, f"recalc {recalc_id} not found")
        metrics = [
            _metric_payload(metric)
            for metric in recalc_service.store.metrics_for(run.window, run.tier)
            if metric.recalc_id == recalc_id
        ]
        return envelope_json(
            {
                "recalc_id": run.recalc_id,
                "status": run.status,
                "window": run.window,
                "tier": run.tier.value,
                "trigger": run.trigger,
                "actor": run.actor,
                "definition_versions": run.definition_versions,
                "started_at": run.started_at.isoformat(),
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "issue_total": run.issue_total,
                "excluded_total": run.excluded_total,
                "reason_distribution": run.reason_distribution,
                "failure_reason": run.failure_reason,
                "late": run.late,
                "metrics": metrics,
            },
            request.state.trace_id,
        )

    @app.get("/api/v1/metrics")
    async def metric_list(request: Request, window: str | None = None, tier: StageTier | None = None):
        metrics = [_metric_payload(metric) for metric in box.store.metrics_for(window, tier)]
        return envelope_json(metrics, request.state.trace_id)

    @app.post("/api/v1/metrics/reports")
    async def metrics_report(payload: RecalcInput, request: Request):
        actor = (request.headers.get("x-actor") or "report-generator").strip()
        try:
            outcome = report_service.generate(payload.window, payload.tier, actor)
        except ReportInconsistent as exc:
            code = ErrorCode.DEFINITION_MISSING if any("定义" in item for item in exc.issues) else ErrorCode.REPORT_INCONSISTENT
            raise ApiError(code, str(exc)) from exc
        return envelope_json(
            {
                "report_id": outcome.record.report_id,
                "version": outcome.record.version,
                "window": outcome.record.window,
                "tier": outcome.record.tier.value,
                "conclusion": outcome.record.conclusion,
                "content_digest": outcome.record.content_digest,
                "archive_ref": outcome.record.archive_ref,
                "archived": bool(outcome.record.archive_ref),
                "rows": outcome.rows,
                "markdown": outcome.markdown,
            },
            request.state.trace_id,
            201,
        )

    @app.get("/api/v1/metrics/reports/{report_id}")
    async def metrics_report_get(report_id: str, request: Request):
        report = box.store.get_report(report_id)
        if report is None:
            raise ApiError(ErrorCode.EVIDENCE_MISSING, f"report {report_id} not found")
        markdown = ""
        if report.archive_ref:
            candidate = Path(report.archive_ref)
            if candidate.is_file():
                markdown = candidate.read_text(encoding="utf-8")
        digest_ok = hashlib.sha256(markdown.encode("utf-8")).hexdigest() == report.content_digest if markdown else False
        return envelope_json(
            {
                "report_id": report.report_id,
                "version": report.version,
                "window": report.window,
                "tier": report.tier.value,
                "definition_version": report.definition_version,
                "conclusion": report.conclusion,
                "generated_at": report.generated_at.isoformat(),
                "content_digest": report.content_digest,
                "archive_ref": report.archive_ref,
                "archived_at": report.archived_at.isoformat() if report.archived_at else None,
                "digest_ok": digest_ok,
                "markdown": markdown,
            },
            request.state.trace_id,
        )

    @app.get("/api/v1/metrics/snapshots/{snapshot_id}/verify")
    async def metrics_snapshot_verify(snapshot_id: str, request: Request, expected_digest: str | None = None):
        cached = box.store.get_snapshot(snapshot_id)
        digest = expected_digest or (cached.digest if cached is not None else None)
        if digest is None:
            raise ApiError(ErrorCode.EVIDENCE_MISSING, f"snapshot {snapshot_id} not found")
        try:
            report = snapshot_verifier.verify(snapshot_id, digest)
        except SnapshotNotFound as exc:
            raise ApiError(ErrorCode.EVIDENCE_MISSING, str(exc)) from exc
        except SnapshotIntegrityError as exc:
            raise ApiError(ErrorCode.SNAPSHOT_INTEGRITY, str(exc)) from exc
        if not report.digest_match or not report.chain_valid:
            raise ApiError(
                ErrorCode.SNAPSHOT_INTEGRITY,
                f"digest_match={report.digest_match} broken_runs={','.join(report.broken_runs)}",
            )
        return envelope_json(
            {
                "snapshot_id": report.snapshot_id,
                "digest_match": report.digest_match,
                "chain_valid": report.chain_valid,
                "broken_runs": report.broken_runs,
                "record_counts": report.record_counts,
            },
            request.state.trace_id,
        )

    @app.get("/api/v1/metrics/{metric_id}/drilldown")
    async def metrics_drilldown(metric_id: str, request: Request, window: str, tier: StageTier = StageTier.PRELIMINARY):
        try:
            metric_key = MetricId(metric_id)
        except ValueError as exc:
            raise ApiError(ErrorCode.NOT_NORMALIZED, f"unknown metric {metric_id}") from exc
        record = box.store.metrics.get((metric_key.value, tier.value, window))
        if record is None:
            raise ApiError(ErrorCode.EVIDENCE_MISSING, f"{metric_id}@{window} not found")
        data = drilldown_service.drilldown(metric_key, tier, window)
        if data is None:
            raise ApiError(ErrorCode.EVIDENCE_MISSING, f"{metric_id}@{window} not found")
        return envelope_json(data, request.state.trace_id)

    @app.post("/api/v1/webhooks/codearts-repo")
    async def repo_webhook(payload: RepoWebhookPayload, request: Request):
        body = await request.body()
        outcome = triggers.handle_repo_webhook(
            payload,
            request.headers.get("x-codearts-signature"),
            body,
            request.headers.get("x-auth-token"),
        )
        return envelope_json(asdict(outcome), request.state.trace_id, 202, 0, "accepted")

    @app.post("/api/v1/triggers/cve")
    async def cve_trigger(payload: CvePayload, request: Request):
        outcome = triggers.handle_cve(payload, request.headers.get("x-auth-token"))
        code = 0
        if outcome.outcome is not None and outcome.outcome.value == "MERGED":
            code = ErrorCode.IDEMPOTENT_HIT.value
        return envelope_json(asdict(outcome), request.state.trace_id, 202, code, outcome.reason)

    @app.post("/api/v1/runtime/alerts")
    async def runtime_alert(payload: RuntimeAlertPayload, request: Request):
        outcome = triggers.handle_runtime_alert(payload, request.headers.get("x-auth-token"))
        return envelope_json(asdict(outcome), request.state.trace_id, 202, 0, outcome.reason)

    @app.post("/api/v1/triggers/scheduled")
    async def scheduled_trigger(payload: ScheduleTriggerInput, request: Request):
        outcome = schedule.register(payload)
        data = asdict(outcome)
        code = ErrorCode.IDEMPOTENT_HIT.value if outcome.duplicate else 0
        message = "同一时间窗重复触发，未重复登记扫描任务" if outcome.duplicate else "scheduled"
        return envelope_json(data, request.state.trace_id, 202, code, message)

    @app.post("/api/v1/heartbeat")
    async def heartbeat(request: Request):
        tracker.heartbeat()
        sample_reader.append(tracker.sample().to_dict())
        return ok_response(
            HeartbeatInfo(
                healthy=tracker.is_healthy(),
                self_run_hours=tracker.continuous_hours(),
                interruptions=tracker.interruptions(),
            ),
            trace_id=request.state.trace_id,
        )

    @app.get("/api/v1/dashboard/summary")
    async def dashboard_summary(request: Request):
        return envelope_json(dashboard.summary(), request.state.trace_id)

    @app.get("/api/v1/events/stream")
    async def events_stream(request: Request, since: int = 0, iterations: int = 1, interval: float = 5.0):
        async def generator():
            cursor = {run_id: since for run_id in box.store.events}
            dashboard._event_cursor = dict(cursor)
            for _ in range(max(1, min(iterations, 60))):
                for event in dashboard.all_events_since():
                    payload = jsonable_encoder(event.model_dump())
                    yield f"id: {event.run_id}:{event.seq}\ndata: {payload}\n\n"
                yield ": heartbeat\n\n"
                await asyncio.sleep(max(0.0, interval))

        return StreamingResponse(generator(), media_type="text/event-stream")

    @app.post("/api/v1/control/config")
    async def apply_config_change(payload: ConfigChangeRequest, request: Request):
        from app.api.envelope import ApiError, ErrorCode
        from app.ops.config_change import FrozenConfigError, apply_changes

        try:
            updated, records = apply_changes(
                resolved,
                payload.changes,
                payload.actor,
                payload.reason,
                writer=control_writer,
                exemption=payload.exemption,
            )
        except FrozenConfigError as exc:
            raise ApiError(ErrorCode.CONFIG_FROZEN, f"frozen configuration path: {exc.path}") from exc
        except ValueError as exc:
            raise ApiError(ErrorCode.CONFIG_INVALID, str(exc)) from exc
        data = {
            "applied": False,
            "effective_after": "restart",
            "records": [
                {
                    "path": item.path,
                    "old_value": item.old_value,
                    "new_value": item.new_value,
                    "actor": item.actor,
                    "reason": item.reason,
                    "frozen": item.frozen,
                    "exemption": item.exemption,
                    "occurred_at": item.occurred_at.isoformat(),
                }
                for item in records
            ],
            "schema_version": SCHEMA_VERSION,
        }
        del updated
        return envelope_json(data, request.state.trace_id, 202, 0, "config change recorded")

    @app.get("/api/v1/control/events")
    async def control_events(request: Request, limit: int = 50):
        return envelope_json(control_writer.records(limit), request.state.trace_id)

    @app.get("/api/v1/runs/{run_id}/deadline")
    async def run_deadline(run_id: str, request: Request):
        try:
            enforcement = supervisor.enforce_deadline(run_id)
        except KeyError as exc:
            raise ApiError(ErrorCode.EVIDENCE_MISSING, f"run {run_id} not found") from exc
        return envelope_json(enforcement, request.state.trace_id)

    @app.post("/api/v1/circuits/{defect_class}/reset")
    async def reset_circuit(defect_class: str, payload: ControlInput, request: Request):
        try:
            target = DefectClass(defect_class)
        except ValueError as exc:
            raise ApiError(ErrorCode.NOT_NORMALIZED, f"unknown defect class: {defect_class}") from exc
        state = breaker.reset(target, payload.actor, payload.reason)
        control_writer.write("reset_circuit", payload.actor, payload.reason, defect_class)
        return envelope_json(state, request.state.trace_id)

    @app.post("/api/v1/control/pause")
    async def pause(payload: ControlInput, request: Request):
        breaker.pause(payload.actor, payload.reason)
        control_writer.write("pause", payload.actor, payload.reason, "auto-disposition")
        return envelope_json(
            {"paused": breaker.is_paused(), "reason": breaker.pause_reason()},
            request.state.trace_id,
        )

    @app.post("/api/v1/control/resume")
    async def resume(request: Request):
        breaker.resume()
        control_writer.write("resume", request.headers.get("x-actor", "operator"), "resume", "auto-disposition")
        return envelope_json({"paused": breaker.is_paused()}, request.state.trace_id)

    @app.post("/api/v1/verdicts/{verdict_id}/review")
    async def review_verdict(verdict_id: str, payload: ReviewInput, request: Request):
        verdict = reachability.review(
            verdict_id, payload.actor, payload.reason, payload.conclusion, payload.confidence
        )
        return ok_response(verdict, trace_id=request.state.trace_id)

    @app.get("/api/v1/runs/{run_id}")
    async def get_run(run_id: str, request: Request):
        try:
            run = box.store.get_run(run_id)
        except KeyError as exc:
            raise ApiError(ErrorCode.EVIDENCE_MISSING, f"run {run_id} not found") from exc
        return ok_response(run, trace_id=request.state.trace_id)

    @app.get("/api/v1/runs/{run_id}/events")
    async def list_events(run_id: str, request: Request):
        events = box.store.list_for_run(run_id)
        if not events:
            raise ApiError(ErrorCode.EVIDENCE_MISSING, f"run {run_id} has no events")
        return ok_response(events, trace_id=request.state.trace_id)

    @app.get("/api/v1/runs/{run_id}/replay")
    async def replay_run(run_id: str, request: Request):
        try:
            snapshot = replay_service.replay(run_id)
        except KeyError as exc:
            raise ApiError(ErrorCode.EVIDENCE_MISSING, f"run {run_id} not found") from exc
        return ok_response(snapshot, trace_id=request.state.trace_id)

    @app.post("/api/v1/eval/runs")
    async def start_eval(payload: EvalStartInput, request: Request):
        project_root = Path(__file__).resolve().parents[2]
        set_path = Path(payload.set_path) if payload.set_path else project_root / resolved.eval.cases_dir
        run = eval_runner.start(
            set_path,
            payload.set_version or resolved.eval.set_version,
            payload.actor,
            payload.digest,
        )
        return envelope_json(run.to_dict(), request.state.trace_id, 202)

    @app.get("/api/v1/eval/runs/{eval_run_id}")
    async def get_eval_run(eval_run_id: str, request: Request):
        try:
            run = eval_runner.status(eval_run_id)
        except KeyError as exc:
            raise ApiError(ErrorCode.EVIDENCE_MISSING, f"eval run {eval_run_id} not found") from exc
        return envelope_json(run.to_dict(), request.state.trace_id)

    @app.post("/api/v1/eval/runs/{eval_run_id}/step")
    async def step_eval_run(eval_run_id: str, request: Request, limit: int = 5):
        try:
            run = eval_runner.step(eval_run_id, limit)
        except KeyError as exc:
            raise ApiError(ErrorCode.EVIDENCE_MISSING, f"eval run {eval_run_id} not found") from exc
        return envelope_json(run.to_dict(), request.state.trace_id)

    @app.post("/api/v1/eval/runs/{eval_run_id}/resume")
    async def resume_eval_run(eval_run_id: str, request: Request, limit: int = 5):
        try:
            run = eval_runner.resume(eval_run_id, limit)
        except KeyError as exc:
            raise ApiError(ErrorCode.EVIDENCE_MISSING, f"eval run {eval_run_id} not found") from exc
        return envelope_json(run.to_dict(), request.state.trace_id)

    @app.post("/api/v1/eval/runs/{eval_run_id}/interrupt")
    async def interrupt_eval_run(eval_run_id: str, payload: ControlInput, request: Request):
        try:
            run = eval_runner.interrupt(eval_run_id, payload.reason)
        except KeyError as exc:
            raise ApiError(ErrorCode.EVIDENCE_MISSING, f"eval run {eval_run_id} not found") from exc
        return envelope_json(run.to_dict(), request.state.trace_id)

    @app.get("/api/v1/eval/runs/{eval_run_id}/load-record")
    async def get_eval_load_record(eval_run_id: str, request: Request):
        try:
            run = eval_runner.status(eval_run_id)
        except KeyError as exc:
            raise ApiError(ErrorCode.EVIDENCE_MISSING, f"eval run {eval_run_id} not found") from exc
        record = run.load_record.model_dump(mode="json") if run.load_record else None
        return envelope_json(record, request.state.trace_id)

    @app.get("/api/v1/eval/audit/access")
    async def search_eval_audit(request: Request, run_ref: str | None = None):
        entries = [item.model_dump(mode="json") for item in eval_runner.audit.search(run_ref=run_ref)]
        return envelope_json(entries, request.state.trace_id)

    @app.post("/api/v1/eval/runs/{eval_run_id}/adjudicate")
    async def adjudicate_eval_run(eval_run_id: str, request: Request):
        try:
            run = eval_runner.status(eval_run_id)
        except KeyError as exc:
            raise ApiError(ErrorCode.EVIDENCE_MISSING, f"eval run {eval_run_id} not found") from exc
        if run.status != "COMPLETED":
            raise ApiError(ErrorCode.EVAL_NOT_ADJUDICATED, f"运行状态 {run.status} 不允许裁决")
        answers = eval_answer_reader.load("judge", eval_run_id)
        result = adjudicator.adjudicate(
            eval_run_id,
            run.binding_digest,
            answers,
            run.results,
        )
        eval_runner.mark_adjudicated(eval_run_id)
        return envelope_json(
            {
                "eval_run_id": eval_run_id,
                "idempotent": result.idempotent,
                "verdict": result.verdict.model_dump(mode="json"),
            },
            request.state.trace_id,
        )

    dist_dir = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="console")

    return app


app = create_app()