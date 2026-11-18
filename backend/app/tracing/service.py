from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from app.api.envelope import ApiError, ErrorCode
from app.config import AppConfig
from app.domain.enums import (
    DefectClass,
    EventType,
    IssueStatus,
    RunTerminalState,
    Severity,
    StepKind,
    StepStatus,
    VerdictConclusion,
)
from app.domain.models import Event, Issue, Run, RunStep, Verdict, utc_now
from app.orchestration.service import OrchestrationService
from app.orchestration.state_machine import StateMachine, Transition, TransitionContext
from app.tracing.callgraph import CallGraph, build_callgraph
from app.tracing.entrypoints import EntryKind, EntryPoint, discover_entrypoints
from app.tracing.taint import TaintResult, trace_best, trace_taint

SEVERITY_WEIGHT: dict[Severity, float] = {
    Severity.CRITICAL: 40.0,
    Severity.HIGH: 30.0,
    Severity.MEDIUM: 20.0,
    Severity.LOW: 10.0,
    Severity.INFO: 0.0,
}

CLASS_WEIGHT: dict[DefectClass, float] = {
    DefectClass.SQL_INJECTION: 8.0,
    DefectClass.COMMAND_INJECTION: 8.0,
    DefectClass.DEPENDENCY_CVE: 6.0,
    DefectClass.HARDCODED_SECRET: 6.0,
}

REACHABLE_BONUS: dict[VerdictConclusion, float] = {
    VerdictConclusion.REACHABLE: 20.0,
    VerdictConclusion.SUSPECTED: 10.0,
    VerdictConclusion.UNREACHABLE: 0.0,
}


@dataclass
class CodeIndex:
    entrypoints: list[EntryPoint]
    graph: CallGraph
    errors: list[str]


@dataclass(frozen=True)
class ReachabilityOutcome:
    verdict: Verdict | None
    issue_status: IssueStatus
    priority: float
    message: str
    error_code: ErrorCode | None
    entry_point_count: int
    taint_path: list[str]
    duration_ms: int
    degraded: bool = False


def compute_priority(issue: Issue, verdict: Verdict | None) -> float:
    severity = SEVERITY_WEIGHT.get(issue.severity, 0.0)
    defect_class = CLASS_WEIGHT.get(issue.defect_class, 0.0) if issue.defect_class else 0.0
    if verdict is None:
        return severity + defect_class
    bonus = REACHABLE_BONUS.get(verdict.conclusion, 0.0)
    return severity + defect_class + bonus + verdict.confidence * 10.0


class ReachabilityService:
    def __init__(self, store, config: AppConfig, state_machine: StateMachine | None = None):
        self.store = store
        self.config = config
        self.machine = state_machine or StateMachine()
        self.orchestration = OrchestrationService(store, store, store, self.machine)
        self._index_cache: dict[str, CodeIndex] = {}

    def index(self, repo_root: Path) -> CodeIndex:
        key = str(Path(repo_root).resolve())
        cached = self._index_cache.get(key)
        if cached is not None:
            return cached
        entrypoints, errors = discover_entrypoints(Path(repo_root))
        graph = build_callgraph(Path(repo_root))
        index = CodeIndex(entrypoints=entrypoints, graph=graph, errors=list(errors) + list(graph.errors))
        self._index_cache[key] = index
        return index

    def analyze(
        self,
        issue: Issue,
        repo_root: Path,
        timeout_seconds: float | None = None,
    ) -> ReachabilityOutcome:
        started = time.monotonic()
        limit = self.config.stage.triage_seconds if timeout_seconds is None else timeout_seconds
        threshold = self.config.suspicion.threshold
        index = self.index(Path(repo_root))

        if time.monotonic() - started > limit:
            return self._record_timeout(issue, started)

        if not index.entrypoints:
            return self._record_suspected(issue, "入口点识别为空，请核对入口点配置", started, degraded=True)

        alerts = self.store.alerts_for(issue.issue_id)
        if not alerts:
            return self._record_suspected(issue, "缺少告警定位，无法判定可达性", started)
        location = alerts[0].location
        sink = index.graph.node_for_file_line(location.file, location.line)
        candidates = self._candidate_entries(index.entrypoints, location.file)
        result = trace_best(index.graph, candidates, sink, threshold)

        if time.monotonic() - started > limit:
            return self._record_timeout(issue, started)

        return self._record(issue, result, candidates, index, threshold, started)

    def _candidate_entries(self, entrypoints: list[EntryPoint], target_file: str) -> list[EntryPoint]:
        same_file = [entry for entry in entrypoints if entry.file == target_file]
        others = [entry for entry in entrypoints if entry.file != target_file]
        pool = same_file + others
        http_first = [entry for entry in pool if entry.kind is EntryKind.HTTP_ROUTE]
        rest = [entry for entry in pool if entry.kind is not EntryKind.HTTP_ROUTE]
        return http_first + rest

    def _ensure_run(self, issue: Issue) -> Run:
        existing = self.store.run_for_issue(issue.issue_id)
        if existing is not None:
            return existing
        now = utc_now()
        run = Run(
            run_id=f"RUN-{uuid.uuid4().hex[:12]}",
            issue_id=issue.issue_id,
            started_at=now,
            deadline_at=now + timedelta(seconds=self.config.run.deadline_seconds),
            steps=[RunStep(kind=kind, status=StepStatus.NOT_RUN) for kind in StepKind],
        )
        self.store.add_run(run)
        return run

    def _ensure_triaging(self, issue: Issue) -> Issue:
        if issue.status is IssueStatus.RECEIVED:
            self._ensure_run(issue)
            self.orchestration.apply(
                Transition.T1,
                TransitionContext(issue=issue),
                EventType.INGEST,
                "event-normalizer",
            )
            return self.store.get(issue.issue_id)
        return issue

    def _record(
        self,
        issue: Issue,
        result: TaintResult,
        entries: list[EntryPoint],
        index: CodeIndex,
        threshold: float,
        started: float,
    ) -> ReachabilityOutcome:
        issue = self._ensure_triaging(issue)
        verdict = Verdict(
            verdict_id=f"V-{uuid.uuid4().hex[:12]}",
            issue_id=issue.issue_id,
            conclusion=result.conclusion,
            confidence=result.confidence,
            taint_path=result.path,
            basis=result.basis,
            decided_by="tracer",
        )
        if issue.status is not IssueStatus.TRIAGING:
            self.store.add_verdict(verdict)
            return ReachabilityOutcome(
                verdict=verdict,
                issue_status=issue.status,
                priority=compute_priority(issue, verdict),
                message=f"Issue 当前状态 {issue.status.value}，已记录判定但未迁移",
                error_code=None,
                entry_point_count=len(index.entrypoints),
                taint_path=result.path,
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        transition = self._transition_for(result, threshold)
        reason = result.basis if transition is Transition.T4 else ""
        with self.store.transaction():
            self.store.add_verdict(verdict)
            self.orchestration.apply(
                transition,
                TransitionContext(
                    issue=issue,
                    verdict=verdict,
                    reason=reason,
                    suspicion_threshold=threshold,
                ),
                EventType.VERDICT,
                "tracer",
            )
        updated = self.store.get(issue.issue_id)
        message = {
            Transition.T2: f"可达，置信度 {result.confidence:.2f}，路径 {len(result.path)} 跳",
            Transition.T3: "不可达，已归档（计入无价值告警）",
            Transition.T4: f"可疑，转人工复核：{result.basis}",
        }[transition]
        return ReachabilityOutcome(
            verdict=verdict,
            issue_status=updated.status,
            priority=compute_priority(updated, verdict),
            message=message,
            error_code=None,
            entry_point_count=len(index.entrypoints),
            taint_path=result.path,
            duration_ms=int((time.monotonic() - started) * 1000),
            degraded=result.incomplete,
        )

    def _transition_for(self, result: TaintResult, threshold: float) -> Transition:
        if result.conclusion is VerdictConclusion.REACHABLE and result.confidence >= threshold:
            return Transition.T2
        if result.conclusion is VerdictConclusion.UNREACHABLE and result.confidence >= threshold:
            return Transition.T3
        return Transition.T4

    def _record_suspected(self, issue: Issue, reason: str, started: float, degraded: bool = False) -> ReachabilityOutcome:
        issue = self._ensure_triaging(issue)
        verdict = Verdict(
            verdict_id=f"V-{uuid.uuid4().hex[:12]}",
            issue_id=issue.issue_id,
            conclusion=VerdictConclusion.SUSPECTED,
            confidence=0.0,
            basis=reason,
            decided_by="tracer",
        )
        if issue.status is IssueStatus.TRIAGING:
            with self.store.transaction():
                self.store.add_verdict(verdict)
                self.orchestration.apply(
                    Transition.T4,
                    TransitionContext(issue=issue, verdict=verdict, reason=reason),
                    EventType.VERDICT,
                    "tracer",
                )
        else:
            self.store.add_verdict(verdict)
        updated = self.store.get(issue.issue_id)
        return ReachabilityOutcome(
            verdict=verdict,
            issue_status=updated.status,
            priority=compute_priority(updated, verdict),
            message=f"可疑：{reason}",
            error_code=None,
            entry_point_count=0,
            taint_path=[],
            duration_ms=int((time.monotonic() - started) * 1000),
            degraded=degraded,
        )

    def _record_timeout(self, issue: Issue, started: float) -> ReachabilityOutcome:
        issue = self._ensure_triaging(issue)
        basis = "判定超时，已转人工"
        verdict = Verdict(
            verdict_id=f"V-{uuid.uuid4().hex[:12]}",
            issue_id=issue.issue_id,
            conclusion=VerdictConclusion.SUSPECTED,
            confidence=0.0,
            basis=basis,
            decided_by="tracer",
        )
        if issue.status is IssueStatus.TRIAGING:
            with self.store.transaction():
                self.store.add_verdict(verdict)
                self.orchestration.apply(
                    Transition.T4,
                    TransitionContext(issue=issue, verdict=verdict, reason=basis),
                    EventType.VERDICT,
                    "tracer",
                )
        else:
            self.store.add_verdict(verdict)
        updated = self.store.get(issue.issue_id)
        return ReachabilityOutcome(
            verdict=verdict,
            issue_status=updated.status,
            priority=compute_priority(updated, verdict),
            message=basis,
            error_code=ErrorCode.VERDICT_TIMEOUT,
            entry_point_count=0,
            taint_path=[],
            duration_ms=int((time.monotonic() - started) * 1000),
            degraded=True,
        )

    def review(
        self,
        verdict_id: str,
        actor: str,
        reason: str,
        conclusion: VerdictConclusion | None = None,
        confidence: float | None = None,
    ) -> Verdict:
        for issue_id, history in self.store.verdicts.items():
            for verdict in history:
                if verdict.verdict_id != verdict_id:
                    continue
                new_verdict = Verdict(
                    verdict_id=f"V-{uuid.uuid4().hex[:12]}",
                    issue_id=issue_id,
                    conclusion=conclusion or verdict.conclusion,
                    confidence=verdict.confidence if confidence is None else confidence,
                    taint_path=list(verdict.taint_path),
                    basis=reason or verdict.basis,
                    decided_by=actor,
                    is_effective=True,
                )
                with self.store.transaction():
                    self.store.add_verdict(new_verdict)
                    self.store.append(
                        Event(
                            event_id=f"REVIEW-{new_verdict.verdict_id}",
                            run_id=self._run_id_for(issue_id),
                            seq=1,
                            event_type=EventType.VERDICT,
                            actor=actor,
                            step=StepKind.VERDICT,
                            payload_ref=f"verdict/{new_verdict.verdict_id}",
                        )
                    )
                return new_verdict
        raise ApiError(ErrorCode.EVIDENCE_MISSING, f"verdict {verdict_id} not found")

    def _run_id_for(self, issue_id: str) -> str:
        run = self.store.run_for_issue(issue_id)
        return run.run_id if run else f"run-{issue_id}"

    def mark_terminal(self, run_id: str, terminal: RunTerminalState) -> Run:
        return self.store.finish_run(run_id, terminal)