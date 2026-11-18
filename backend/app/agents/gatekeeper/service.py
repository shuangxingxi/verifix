from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.adapters.pipeline import (
    CodeArtsPipelinePort,
    GateJudger,
    GateParams,
)
from app.adapters.repo import CodeArtsRepoPort
from app.adapters.types import UpstreamUnavailable
from app.agents.critic.service import CriticOutcome, CriticStatus
from app.agents.patcher.templates import PatchCandidate
from app.api.envelope import ApiError, ErrorCode
from app.config import AppConfig
from app.domain.enums import (
    AuditVerdict,
    DispositionLevel,
    EventType,
    FixParadigm,
    GateOutcome,
    IssueStatus,
)
from app.domain.models import (
    Disposition,
    DispositionHistoryEntry,
    Event,
    GateAttempt,
    GateResult,
    Issue,
    Patch,
    Proof,
    utc_now,
)
from app.orchestration.service import OrchestrationService
from app.orchestration.state_machine import StateMachine, Transition, TransitionContext


@dataclass(frozen=True)
class GateOutcomeResult:
    status: str
    issue_status: IssueStatus
    disposition: Disposition | None
    gate_result: GateResult | None
    message: str
    error_code: ErrorCode | None
    pr_number: int | None = None
    merged_into: str | None = None


class GatekeeperService:
    def __init__(
        self,
        store,
        config: AppConfig,
        repo: CodeArtsRepoPort,
        pipeline: CodeArtsPipelinePort,
        judger: GateJudger | None = None,
        state_machine: StateMachine | None = None,
    ):
        self.store = store
        self.config = config
        self.repo = repo
        self.pipeline = pipeline
        self.judger = judger or GateJudger()
        self.machine = state_machine or StateMachine()
        self.orchestration = OrchestrationService(store, store, store, self.machine)

    def _ctx(self, **kwargs) -> TransitionContext:
        kwargs.setdefault("coverage_tolerance_pp", self.config.metrics.coverage_delta_tolerance_pp)
        return TransitionContext(**kwargs)

    def dispose(
        self,
        issue: Issue,
        patch: Patch,
        proof: Proof,
        candidate: PatchCandidate,
        critic: CriticOutcome,
        run_key: str,
    ) -> GateOutcomeResult:
        if critic.status == CriticStatus.L3:
            return self._reject_backdoor(issue, patch, critic)
        if critic.status == CriticStatus.L2:
            rejected = any(item.verdict is AuditVerdict.REJECT for item in critic.findings)
            if rejected:
                return self._downgrade_l2(issue, patch, critic)
            return self._fail_gate(issue, patch, critic.message, ErrorCode.GATE_RED_MISSING)

        current = self.store.get(issue.issue_id)
        if current.status is IssueStatus.AUDITING:
            self._apply(
                issue,
                Transition.T11,
                self._ctx(
                    issue=current,
                    proof=proof,
                    patch=patch,
                    audit_findings=list(critic.findings),
                    registered_test_fingerprint=proof.fingerprint,
                ),
                EventType.AUDIT,
                "critic",
            )
        gating = self.store.get(issue.issue_id)
        if gating.status is not IssueStatus.GATING:
            return GateOutcomeResult(
                "NOT_READY", gating.status, None, None,
                f"Issue 当前状态 {gating.status.value}，无法进入门禁", ErrorCode.NO_VERDICT,
            )

        branch = patch.branch
        try:
            self.repo.create_branch(issue.repo, branch, issue.code_version)
            self.repo.commit_files(issue.repo, branch, candidate.files, f"fix {issue.issue_id}")
        except Exception as exc:
            return GateOutcomeResult(
                "INTEGRATION_ERROR", gating.status, None, None,
                f"分支推送失败：{exc}", ErrorCode.GATE_NOT_EXECUTED,
            )

        try:
            run_ref = self.pipeline.trigger_gate(
                self.config.codearts.pipeline_id or "verifix-gate",
                GateParams(branch=branch, issue_id=issue.issue_id, run_key=run_key),
            )
        except UpstreamUnavailable as exc:
            return GateOutcomeResult(
                "INTEGRATION_ERROR", gating.status, None, None,
                f"门禁未执行：{exc}", ErrorCode.GATE_NOT_EXECUTED,
            )

        try:
            snapshot = self.pipeline.poll_gate_result(run_ref)
        except UpstreamUnavailable:
            return self._fail_gate(issue, patch, "门禁回读超时，已回滚", ErrorCode.GATE_TIMEOUT)

        gate = self.judger.judge(patch.patch_id, proof, snapshot, critic.regression_zero_fail)
        with self.store.transaction():
            self.store.add_gate_result(gate)
            self._record_gate_attempt(issue.issue_id, patch, gate)

        if gate.outcome is not GateOutcome.PASSED:
            return self._fail_gate(issue, patch, "三闸失败，已回滚", ErrorCode.GATE_RED_MISSING)

        level = DispositionLevel.L0 if patch.fix_paradigm is FixParadigm.VERSION_UPGRADE else DispositionLevel.L1
        pr_number: int | None = None
        merged_into: str | None = None
        ready_at: datetime | None = None
        try:
            if level is DispositionLevel.L0:
                merged = self.repo.merge_to_release_auto(issue.repo, branch)
                merged_into = merged.target
                action = f"merge to {merged.target}"
            else:
                body = (
                    f"issue={issue.issue_id} run={gate.gate_run_ref} "
                    f"red_green={gate.red_green_paired} regression_ok={gate.regression_zero_fail} "
                    f"rescan_new_alerts={gate.rescan_new_alerts} coverage_delta_pp={gate.coverage_delta_pp}"
                )
                pr = self.repo.open_pull_request(issue.repo, branch, "main", f"[VeriFix] {issue.issue_id}", body)
                pr_number = pr.number
                action = f"open pr #{pr.number}"
            ready_at = utc_now()
        except Exception as exc:
            return GateOutcomeResult(
                "INTEGRATION_ERROR", self.store.get(issue.issue_id).status, None, gate,
                f"落库失败：{exc}", ErrorCode.GATE_NOT_EXECUTED,
            )

        disposition = Disposition(
            disposition_id=f"D-{issue.issue_id}",
            issue_id=issue.issue_id,
            level=level,
            action=action,
            evidence_ref=gate.gate_run_ref,
            reason_code="GATE_PASSED",
            gate_outcome=GateOutcome.PASSED,
            decided_at=utc_now(),
            ready_at=ready_at,
        )
        with self.store.transaction():
            self.store.add_disposition(disposition)
            self._record_disposition(disposition)
            self.orchestration.apply(
                Transition.T14 if level is DispositionLevel.L0 else Transition.T15,
                self._ctx(
                    issue=self.store.get(issue.issue_id),
                    proof=proof,
                    patch=patch,
                    gate_result=gate,
                ),
                EventType.DISPOSITION,
                "gatekeeper",
            )
        updated = self.store.get(issue.issue_id)
        return GateOutcomeResult(
            level.value, updated.status, disposition, gate,
            f"{level.value} 处置完成：{action}（门禁 {gate.gate_run_ref}）",
            None, pr_number, merged_into,
        )

    def _latest_patch_attempt_id(self, issue_id: str) -> str | None:
        attempts = self.store.patch_attempts_for(issue_id)
        return attempts[-1].attempt_id if attempts else None

    def _record_gate_attempt(
        self,
        issue_id: str,
        patch: Patch,
        gate: GateResult | None = None,
    ) -> GateAttempt:
        index = len(self.store.gate_attempts_for(patch.patch_id)) + 1
        attempt = GateAttempt(
            attempt_id=f"GA-{patch.patch_id}#{index}",
            patch_id=patch.patch_id,
            issue_id=issue_id,
            outcome=gate.outcome if gate is not None else GateOutcome.NOT_EXECUTED,
            red_green_paired=gate.red_green_paired if gate is not None else False,
            regression_zero_fail=gate.regression_zero_fail if gate is not None else False,
            rescan_new_alerts=gate.rescan_new_alerts if gate is not None else 0,
            coverage_delta_pp=gate.coverage_delta_pp if gate is not None else 0.0,
            evidence_missing=gate.evidence_missing if gate is not None else True,
            observed_at=gate.observed_at if gate is not None else utc_now(),
        )
        self.store.record_gate(attempt)
        return attempt

    def _record_disposition(self, disposition: Disposition) -> DispositionHistoryEntry:
        entry = DispositionHistoryEntry(
            attempt_id=self._latest_patch_attempt_id(disposition.issue_id),
            issue_id=disposition.issue_id,
            level=disposition.level,
            gate_outcome=disposition.gate_outcome,
            decided_at=disposition.decided_at,
            ready_at=disposition.ready_at,
        )
        self.store.record_disposition(entry)
        return entry

    def _apply(self, issue: Issue, transition: Transition, ctx: TransitionContext, event_type: EventType, actor: str) -> None:
        with self.store.transaction():
            try:
                self.orchestration.apply(transition, ctx, event_type, actor)
            except ApiError:
                raise

    def _fail_gate(self, issue: Issue, patch: Patch, message: str, code: ErrorCode) -> GateOutcomeResult:
        current = self.store.get(issue.issue_id)
        if not self.store.gate_attempts_for(patch.patch_id):
            self._record_gate_attempt(issue.issue_id, patch)
        if current.status in {IssueStatus.AUDITING}:
            critic_findings = self.store.audit_findings_for(patch.patch_id)
            self._apply(
                issue,
                Transition.T11,
                self._ctx(
                    issue=current,
                    proof=self.store.proof_for(issue.issue_id),
                    patch=patch,
                    audit_findings=critic_findings,
                    registered_test_fingerprint=(self.store.proof_for(issue.issue_id).fingerprint
                                                 if self.store.proof_for(issue.issue_id) else None),
                ),
                EventType.AUDIT,
                "critic",
            )
            current = self.store.get(issue.issue_id)

        if current.status is IssueStatus.GATING:
            self._apply(
                issue,
                Transition.T16,
                self._ctx(issue=current, gate_failure_reason=message),
                EventType.GATE,
                "gatekeeper",
            )
            current = self.store.get(issue.issue_id)

        deletion = self.repo.delete_branch(issue.repo, patch.branch)
        if current.status is IssueStatus.ROLLING_BACK:
            self._apply(
                issue,
                Transition.T18,
                self._ctx(issue=current, branch_deleted=deletion.deleted, reason=message),
                EventType.ROLLBACK,
                "gatekeeper",
            )

        disposition = Disposition(
            disposition_id=f"D-{issue.issue_id}",
            issue_id=issue.issue_id,
            level=DispositionLevel.L2,
            action="rollback_and_report",
            evidence_ref=f"rollback/{patch.branch}",
            reason_code="GATE_FAILED",
            decided_at=utc_now(),
        )
        with self.store.transaction():
            self.store.add_disposition(disposition)
            self._record_disposition(disposition)
        return GateOutcomeResult(
            "L2", self.store.get(issue.issue_id).status, disposition, None, message, code
        )

    def _downgrade_l2(self, issue: Issue, patch: Patch, critic: CriticOutcome) -> GateOutcomeResult:
        current = self.store.get(issue.issue_id)
        if current.status is IssueStatus.AUDITING:
            self._apply(
                issue,
                Transition.T12,
                self._ctx(issue=current, patch=patch, audit_findings=list(critic.findings)),
                EventType.AUDIT,
                "critic",
            )
        disposition = Disposition(
            disposition_id=f"D-{issue.issue_id}",
            issue_id=issue.issue_id,
            level=DispositionLevel.L2,
            action="report_only",
            evidence_ref=f"audit/{patch.patch_id}",
            reason_code="AUDIT_REJECTED",
            decided_at=utc_now(),
        )
        with self.store.transaction():
            self.store.add_disposition(disposition)
            self._record_disposition(disposition)
        return GateOutcomeResult("L2", self.store.get(issue.issue_id).status, disposition, None, critic.message,
                                 ErrorCode.AUDIT_HIT)

    def _reject_backdoor(self, issue: Issue, patch: Patch, critic: CriticOutcome) -> GateOutcomeResult:
        current = self.store.get(issue.issue_id)
        if current.status is IssueStatus.AUDITING:
            self._apply(
                issue,
                Transition.T13,
                self._ctx(issue=current, patch=patch, audit_findings=list(critic.findings)),
                EventType.AUDIT,
                "critic",
            )
        disposition = Disposition(
            disposition_id=f"D-{issue.issue_id}",
            issue_id=issue.issue_id,
            level=DispositionLevel.L3,
            action="reject_and_alert",
            evidence_ref=f"audit/{patch.patch_id}",
            reason_code="BACKDOOR",
            decided_at=utc_now(),
        )
        with self.store.transaction():
            self.store.add_disposition(disposition)
            self._record_disposition(disposition)
            run = self.store.run_for_issue(issue.issue_id)
            self.store.append(
                Event(
                    event_id=f"ALERT-{issue.issue_id}",
                    run_id=run.run_id if run else f"run-{issue.issue_id}",
                    seq=1,
                    event_type=EventType.ALERT,
                    actor="gatekeeper",
                    payload_ref="backdoor/rejected",
                )
            )
        return GateOutcomeResult("L3", self.store.get(issue.issue_id).status, disposition, None, critic.message,
                                 ErrorCode.BACKDOOR)