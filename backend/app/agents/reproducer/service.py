from __future__ import annotations

import hashlib
import shutil
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from app.agents.reproducer.executor import TestExecution, TestExecutorPort
from app.agents.reproducer.templates import render_test
from app.agents.reproducer.validator import InvalidTestError, assert_valid
from app.api.envelope import ErrorCode
from app.config import AppConfig
from app.domain.defects.plugins import default_registry
from app.domain.enums import EventType, IssueStatus, ProofResult, ReproductionAttemptStatus
from app.domain.models import (
    Alert,
    Event,
    Issue,
    Proof,
    ReproductionAttempt,
    Run,
    RunStep,
    StepKind,
    StepStatus,
    utc_now,
)
from app.orchestration.service import OrchestrationService
from app.orchestration.state_machine import StateMachine, Transition, TransitionContext


class ReproductionStatus(str, Enum):
    PROVEN = "PROVEN"
    REPRO_FAILED = "REPRO_FAILED"
    INFRA_ERROR = "INFRA_ERROR"
    INVALID_TEST = "INVALID_TEST"
    NOT_READY = "NOT_READY"


@dataclass(frozen=True)
class ReproductionOutcome:
    status: ReproductionStatus
    issue_status: IssueStatus
    proof: Proof | None
    message: str
    error_code: ErrorCode | None
    attempts: int
    test_path: str
    behavior: str
    execution: TestExecution | None = None


MAX_INFRA_ATTEMPTS = 2


class ReproducerService:
    def __init__(
        self,
        store,
        executor: TestExecutorPort,
        config: AppConfig,
        state_machine: StateMachine | None = None,
        max_infra_attempts: int = MAX_INFRA_ATTEMPTS,
    ):
        self.store = store
        self.executor = executor
        self.config = config
        self.machine = state_machine or StateMachine()
        self.orchestration = OrchestrationService(store, store, store, self.machine)
        self.registry = default_registry()
        self.max_infra_attempts = max_infra_attempts

    def reproduce(self, issue: Issue, target_root: Path) -> ReproductionOutcome:
        alerts = self.store.alerts_for(issue.issue_id)
        if not alerts:
            return ReproductionOutcome(
                status=ReproductionStatus.NOT_READY,
                issue_status=issue.status,
                proof=None,
                message="缺少告警定位，无法生成复现测试",
                error_code=ErrorCode.NOT_NORMALIZED,
                attempts=0,
                test_path="",
                behavior="",
            )
        alert: Alert = alerts[0]
        plugin = self.registry.by_class(issue.defect_class) if issue.defect_class else None
        if plugin is None:
            return ReproductionOutcome(
                status=ReproductionStatus.NOT_READY,
                issue_status=issue.status,
                proof=None,
                message="缺陷类别不在本轮范围，无法生成复现测试",
                error_code=ErrorCode.OUT_OF_SCOPE,
                attempts=0,
                test_path="",
                behavior="",
            )

        generated = render_test(issue, alert, Path(target_root))
        try:
            assert_valid(generated.source, plugin.assertion_policy())
        except InvalidTestError as exc:
            self._record_attempt(issue.issue_id, ReproductionAttemptStatus.INVALID_TEST)
            return ReproductionOutcome(
                status=ReproductionStatus.INVALID_TEST,
                issue_status=issue.status,
                proof=None,
                message=f"复现测试未通过断言有效性审查：{exc}",
                error_code=ErrorCode.AUDIT_HIT,
                attempts=0,
                test_path=generated.relative_path,
                behavior=generated.behavior,
            )

        issue = self._enter_reproducing(issue)
        if issue.status is not IssueStatus.REPRODUCING:
            return ReproductionOutcome(
                status=ReproductionStatus.NOT_READY,
                issue_status=issue.status,
                proof=None,
                message=f"Issue 当前状态 {issue.status.value} 不具备复现条件（必须已有可达结论）",
                error_code=ErrorCode.NO_VERDICT,
                attempts=0,
                test_path=generated.relative_path,
                behavior=generated.behavior,
            )

        attempts = 0
        execution: TestExecution | None = None
        while attempts < self.max_infra_attempts:
            attempts += 1
            with tempfile.TemporaryDirectory(prefix="verifix-repro-", ignore_cleanup_errors=True) as tmp:
                workspace = Path(tmp) / "workspace"
                shutil.copytree(Path(target_root), workspace)
                target_file = workspace / generated.relative_path
                target_file.parent.mkdir(parents=True, exist_ok=True)
                target_file.write_text(generated.source, encoding="utf-8")
                execution = self.executor.run_tests(workspace, generated.relative_path)
            if execution.infra_error is None and not execution.timed_out:
                break

        if execution is None:
            return self._fail(issue, "复现执行未产生结果", ReproductionStatus.INFRA_ERROR, ErrorCode.REPRO_FAILED, attempts)

        if execution.infra_error is not None or execution.timed_out:
            return self._fail(
                issue,
                f"沙箱异常，任务已重试 {attempts} 次",
                ReproductionStatus.INFRA_ERROR,
                ErrorCode.REPRO_FAILED,
                attempts,
                execution,
            )

        if execution.exit_code == 0:
            return self._fail(
                issue,
                "补丁前测试已通过，无法证明漏洞存在",
                ReproductionStatus.REPRO_FAILED,
                ErrorCode.REPRO_FAILED,
                attempts,
                execution,
            )

        if not execution.assertion_failed:
            return self._fail(
                issue,
                "复现测试执行异常（非断言失败），视为测试无效",
                ReproductionStatus.INVALID_TEST,
                ErrorCode.AUDIT_HIT,
                attempts,
                execution,
            )

        fingerprint = hashlib.sha256(generated.source.encode("utf-8")).hexdigest()
        proof = Proof(
            proof_id=f"P-{issue.issue_id}",
            issue_id=issue.issue_id,
            test_path=generated.relative_path,
            pre_patch_result=ProofResult.FAIL,
            fingerprint=fingerprint,
            env_snapshot=execution.env_snapshot,
            generated_marker="AUTOGENERATED",
        )
        with self.store.transaction():
            self.store.add_proof(proof)
            self._record_attempt(
                issue.issue_id,
                ReproductionAttemptStatus.PROVEN,
                proof_id=proof.proof_id,
            )
            self.orchestration.apply(
                Transition.T7,
                TransitionContext(issue=self.store.get(issue.issue_id), proof=proof),
                EventType.PROOF,
                "reproducer",
            )
        updated = self.store.get(issue.issue_id)
        return ReproductionOutcome(
            status=ReproductionStatus.PROVEN,
            issue_status=updated.status,
            proof=proof,
            message=f"红态确认：{generated.behavior} 测试在补丁前失败（{execution.backend}，{execution.duration_ms}ms）",
            error_code=None,
            attempts=attempts,
            test_path=generated.relative_path,
            behavior=generated.behavior,
            execution=execution,
        )

    def _enter_reproducing(self, issue: Issue) -> Issue:
        if issue.status is IssueStatus.REPRODUCING:
            return issue
        if issue.status is IssueStatus.REACHABLE:
            verdict = self.store.effective(issue.issue_id)
            with self.store.transaction():
                self.orchestration.apply(
                    Transition.T6,
                    TransitionContext(issue=issue, verdict=verdict),
                    EventType.VERDICT,
                    "reproducer",
                )
            return self.store.get(issue.issue_id)
        return issue

    def _attempt_status(self, status: ReproductionStatus) -> ReproductionAttemptStatus:
        if status is ReproductionStatus.REPRO_FAILED:
            return ReproductionAttemptStatus.REPRO_FAILED
        if status is ReproductionStatus.INVALID_TEST:
            return ReproductionAttemptStatus.INVALID_TEST
        return ReproductionAttemptStatus.INFRA_ERROR

    def _record_attempt(
        self,
        issue_id: str,
        status: ReproductionAttemptStatus,
        proof_id: str | None = None,
    ) -> ReproductionAttempt:
        index = self.store.next_reproduction_index(issue_id)
        attempt = ReproductionAttempt(
            attempt_id=f"RA-{issue_id}#{index}",
            issue_id=issue_id,
            attempt_index=index,
            status=status,
            proof_id=proof_id,
        )
        self.store.record_reproduction(attempt)
        return attempt

    def _fail(
        self,
        issue: Issue,
        message: str,
        status: ReproductionStatus,
        code: ErrorCode,
        attempts: int,
        execution: TestExecution | None = None,
    ) -> ReproductionOutcome:
        current = self.store.get(issue.issue_id)
        if current.status is IssueStatus.REPRODUCING:
            with self.store.transaction():
                self.orchestration.apply(
                    Transition.T8,
                    TransitionContext(issue=current, reason=message),
                    EventType.PROOF,
                    "reproducer",
                )
                failed = self.store.get(issue.issue_id)
                self.orchestration.apply(
                    Transition.T8B,
                    TransitionContext(issue=failed, reason=message),
                    EventType.DISPOSITION,
                    "reproducer",
                )
        updated = self.store.get(issue.issue_id)
        self._record_attempt(issue.issue_id, self._attempt_status(status))
        return ReproductionOutcome(
            status=status,
            issue_status=updated.status,
            proof=None,
            message=message,
            error_code=code,
            attempts=attempts,
            test_path="",
            behavior="",
            execution=execution,
        )


def ensure_run(store, issue: Issue, config: AppConfig) -> Run:
    from datetime import timedelta

    existing = store.run_for_issue(issue.issue_id)
    if existing is not None:
        return existing
    now = utc_now()
    run = Run(
        run_id=f"RUN-{issue.issue_id}",
        issue_id=issue.issue_id,
        started_at=now,
        deadline_at=now + timedelta(seconds=config.run.deadline_seconds),
        steps=[RunStep(kind=kind, status=StepStatus.NOT_RUN) for kind in StepKind],
    )
    store.add_run(run)
    store.append(
        Event(
            event_id=f"REPRO-{issue.issue_id}",
            run_id=run.run_id,
            seq=1,
            event_type=EventType.PROOF,
            actor="reproducer",
            step=StepKind.PROOF,
        )
    )
    return run