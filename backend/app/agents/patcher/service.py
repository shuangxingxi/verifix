from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.agents.patcher.gateway import (
    BugContext,
    ModelBudgetExceeded,
    ModelGateway,
    ModelOutputRejected,
)
from app.agents.patcher.guard import GuardResult, evaluate
from app.agents.patcher.templates import (
    GUARD_STRENGTH,
    PatchCandidate,
    PatchGenerationError,
    render_patch,
)
from app.api.envelope import ErrorCode
from app.config import AppConfig
from app.domain.enums import EventType, FixParadigm, IssueStatus
from app.domain.models import Event, Patch, PatchAttempt, utc_now
from app.orchestration.service import OrchestrationService
from app.orchestration.state_machine import StateMachine, Transition, TransitionContext


class PatchStatus(str):
    PATCHED = "PATCHED"
    REJECTED = "REJECTED"
    NOT_READY = "NOT_READY"
    GENERATION_FAILED = "GENERATION_FAILED"


@dataclass(frozen=True)
class PatchOutcome:
    status: str
    issue_status: IssueStatus
    patch: Patch | None
    message: str
    error_code: ErrorCode | None
    guard: GuardResult | None
    candidate: PatchCandidate | None


class PatcherService:
    def __init__(
        self,
        store,
        config: AppConfig,
        gateway: ModelGateway | None = None,
        state_machine: StateMachine | None = None,
    ):
        self.store = store
        self.config = config
        self.gateway = gateway
        self.machine = state_machine or StateMachine()
        self.orchestration = OrchestrationService(store, store, store, self.machine)

    def patch(self, issue, target_root: Path, fixed_version: str | None = None) -> PatchOutcome:
        if issue.status is not IssueStatus.PROVEN:
            return PatchOutcome(
                "NOT_READY", issue.status, None,
                f"Issue 当前状态 {issue.status.value}，补丁生成要求先取得红态证明",
                ErrorCode.REPRO_FAILED, None, None,
            )
        proof = self.store.proof_for(issue.issue_id)
        if proof is None:
            return PatchOutcome("NOT_READY", issue.status, None, "缺少复现证据，无法生成补丁",
                                ErrorCode.REPRO_FAILED, None, None)
        alerts = self.store.alerts_for(issue.issue_id)
        if not alerts:
            return PatchOutcome("NOT_READY", issue.status, None, "缺少告警定位，无法生成补丁",
                                ErrorCode.NOT_NORMALIZED, None, None)
        alert = alerts[0]

        candidate: PatchCandidate | None = None
        generation_error = ""
        try:
            candidate = render_patch(issue, alert, Path(target_root), fixed_version=fixed_version)
            self._validate_python(candidate)
        except PatchGenerationError as exc:
            generation_error = str(exc)
            candidate = self._model_candidate(issue, alert, Path(target_root), generation_error)
            if candidate is not None:
                try:
                    self._validate_python(candidate)
                except PatchGenerationError as model_exc:
                    generation_error = f"{generation_error}; model: {model_exc}"
                    candidate = None

        if candidate is None:
            return PatchOutcome("GENERATION_FAILED", issue.status, None, f"补丁生成失败：{generation_error}",
                                ErrorCode.PATCH_OVERSIZED, None, None)

        guard = evaluate(
            candidate,
            max_lines=self.config.patch.max_lines,
            max_files=self.config.patch.max_files,
            strength_min=self.config.patch.strength_l0_l1_min,
            target_files={alert.location.file},
        )
        patch = Patch(
            patch_id=f"PA-{issue.issue_id}",
            issue_id=issue.issue_id,
            proof_id=proof.proof_id,
            branch=f"{self.config.branch.namespace}{issue.issue_id}",
            diff_ref=f"sha256:{hashlib.sha256(candidate.diff.encode('utf-8')).hexdigest()}",
            lines_changed=candidate.lines_changed,
            files_changed=candidate.files_changed,
            fix_paradigm=candidate.fix_paradigm,
            patch_strength=guard.strength,
            quotas_ok=guard.ok,
        )

        if not guard.ok:
            with self.store.transaction():
                self.store.add_patch(patch)
                self._record_attempt(issue.issue_id, patch)
                self._write_guard_event(issue, patch, guard)
            return PatchOutcome(
                "REJECTED", issue.status, patch,
                f"补丁前置校验拒绝：{'; '.join(item.detail for item in guard.issues)}",
                guard.first_code, guard, candidate,
            )

        with self.store.transaction():
            self.store.add_patch(patch)
            self._record_attempt(issue.issue_id, patch)
            current = self.store.get(issue.issue_id)
            self.orchestration.apply(
                Transition.T9,
                TransitionContext(issue=current, proof=proof),
                EventType.PATCH,
                "patcher",
            )
            patching = self.store.get(issue.issue_id)
            self.orchestration.apply(
                Transition.T10,
                TransitionContext(issue=patching, proof=proof, patch=patch),
                EventType.PATCH,
                "patcher",
            )
        updated = self.store.get(issue.issue_id)
        return PatchOutcome(
            "PATCHED", updated.status, patch,
            f"补丁生成完成：{candidate.rationale}（{candidate.lines_changed} 行 / {candidate.files_changed} 文件，强度 {guard.strength:.2f}）",
            None, guard, candidate,
        )

    def _record_attempt(self, issue_id: str, patch: Patch) -> PatchAttempt:
        index = self.store.next_patch_index(issue_id)
        attempt = PatchAttempt(
            attempt_id=f"PA-{issue_id}#{index}",
            issue_id=issue_id,
            attempt_index=index,
            patch_id=patch.patch_id,
        )
        self.store.record_patch(attempt)
        return attempt

    def _validate_python(self, candidate: PatchCandidate) -> None:
        for path, content in candidate.files.items():
            if not path.endswith(".py"):
                continue
            try:
                compile(content, path, "exec")
            except SyntaxError as exc:
                raise PatchGenerationError(f"generated patch has syntax error in {path}: {exc.msg}") from exc

    def _model_candidate(
        self,
        issue,
        alert,
        target_root: Path,
        reason: str,
    ) -> PatchCandidate | None:
        if self.gateway is None:
            return None
        source_path = target_root / alert.location.file
        if not source_path.is_file():
            return None
        source = source_path.read_text(encoding="utf-8")
        lines = source.splitlines()
        line = alert.location.line or 1
        context = "\n".join(lines[max(0, line - 3) : line + 2])
        ctx = BugContext(
            issue_id=issue.issue_id,
            rule_id=alert.rule_id,
            defect_class=issue.defect_class.value if issue.defect_class else "",
            file=alert.location.file,
            line=line,
            code_context=context,
            reachability_path=[],
        )
        try:
            payload = self.gateway.generate_patch(ctx)
        except (ModelBudgetExceeded, ModelOutputRejected):
            return None
        files = {str(path): str(body) for path, body in payload["files"].items()}
        if alert.location.file not in files:
            files[alert.location.file] = source
        paradigm_name = str(payload.get("fix_paradigm", ""))
        try:
            paradigm = FixParadigm(paradigm_name)
        except ValueError:
            paradigm = FixParadigm.PARAMETERIZED_QUERY
        from app.agents.patcher.templates import _unified_diff

        old_map = {path: (target_root / path).read_text(encoding="utf-8") if (target_root / path).is_file() else "" for path in files}
        diff, changed = _unified_diff(old_map, files)
        return PatchCandidate(
            files=files,
            diff=diff,
            lines_changed=changed,
            files_changed=len(files),
            fix_paradigm=paradigm,
            strength=GUARD_STRENGTH.get(paradigm, 0.70),
            rationale=f"模型补丁（模板降级：{reason}）",
            referenced_files=tuple(files),
        )

    def _write_guard_event(self, issue, patch: Patch, guard: GuardResult) -> None:
        run = self.store.run_for_issue(issue.issue_id)
        self.store.append(
            Event(
                event_id=f"GUARD-{patch.patch_id}",
                run_id=run.run_id if run else f"run-{issue.issue_id}",
                seq=1,
                event_type=EventType.PATCH,
                actor="patcher",
                payload_ref=f"patch/{patch.patch_id}",
            )
        )
        del guard, utc_now