from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from app.api.envelope import ApiError, ErrorCode
from app.domain.enums import (
    BACKDOOR_RULES,
    AuditVerdict,
    DispositionLevel,
    FixParadigm,
    GateOutcome,
    IssueStatus,
    ProofResult,
    VerdictConclusion,
)
from app.domain.models import (
    AuditFinding,
    GateResult,
    Issue,
    Patch,
    Proof,
    Verdict,
)


class Transition(str, Enum):
    T0 = "T0"
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"
    T4 = "T4"
    T5 = "T5"
    T6 = "T6"
    T7 = "T7"
    T8 = "T8"
    T8B = "T8B"
    T9 = "T9"
    T10 = "T10"
    T11 = "T11"
    T12 = "T12"
    T13 = "T13"
    T14 = "T14"
    T15 = "T15"
    T16 = "T16"
    T17 = "T17"
    T18 = "T18"


PRIMARY_TRANSITIONS: tuple[Transition, ...] = (
    Transition.T1,
    Transition.T2,
    Transition.T3,
    Transition.T4,
    Transition.T6,
    Transition.T7,
    Transition.T8,
    Transition.T9,
    Transition.T10,
    Transition.T11,
    Transition.T12,
    Transition.T13,
    Transition.T14,
    Transition.T15,
    Transition.T16,
    Transition.T17,
    Transition.T18,
)

AUXILIARY_TRANSITIONS: tuple[Transition, ...] = (Transition.T0, Transition.T5, Transition.T8B)


class StateTransitionError(Exception):
    def __init__(self, transition: Transition, current: IssueStatus, reason: str):
        self.transition = transition
        self.current = current
        self.reason = reason
        super().__init__(f"{transition.value} rejected from {current.value}: {reason}")

    def to_api_error(self) -> ApiError:
        return ApiError(ErrorCode.NO_VERDICT, self.reason)


@dataclass
class TransitionContext:
    issue: Issue
    verdict: Verdict | None = None
    proof: Proof | None = None
    patch: Patch | None = None
    gate_result: GateResult | None = None
    audit_findings: list[AuditFinding] = field(default_factory=list)
    registered_test_fingerprint: str | None = None
    suspicion_threshold: float = 0.60
    coverage_tolerance_pp: float = 0.5
    patch_max_lines: int = 30
    patch_max_files: int = 3
    patch_strength_min: float = 0.60
    reason: str = ""
    actor: str = ""
    branch_deleted: bool = False
    gate_failure_reason: str = ""


@dataclass(frozen=True)
class TransitionSpec:
    transition: Transition
    source: frozenset[IssueStatus]
    target: IssueStatus
    guard: Callable[[TransitionContext], None]
    code: ErrorCode | None = None
    label: str = ""


def _require(condition: bool, code: ErrorCode, message: str) -> None:
    if not condition:
        raise ApiError(code, message)


def _guard_normalized(ctx: TransitionContext) -> None:
    _require(ctx.issue.in_scope and ctx.issue.defect_class is not None, ErrorCode.NOT_NORMALIZED, "defect_class missing")
    _require(bool(ctx.issue.fingerprint), ErrorCode.NOT_NORMALIZED, "fingerprint missing")


def _guard_reachable(ctx: TransitionContext) -> None:
    verdict = ctx.verdict
    _require(verdict is not None, ErrorCode.NO_VERDICT, "Verdict required before REACHABLE")
    assert verdict is not None
    _require(verdict.conclusion is VerdictConclusion.REACHABLE, ErrorCode.NO_VERDICT, "conclusion must be REACHABLE")
    _require(verdict.confidence >= ctx.suspicion_threshold, ErrorCode.NO_VERDICT, "confidence below suspicion threshold")
    _require(bool(verdict.taint_path), ErrorCode.NO_VERDICT, "taint_path must not be empty")


def _guard_unreachable(ctx: TransitionContext) -> None:
    verdict = ctx.verdict
    _require(verdict is not None, ErrorCode.NO_VERDICT, "Verdict required before ARCHIVED")
    assert verdict is not None
    _require(verdict.conclusion is VerdictConclusion.UNREACHABLE, ErrorCode.NO_VERDICT, "conclusion must be UNREACHABLE")
    _require(verdict.confidence >= ctx.suspicion_threshold, ErrorCode.NO_VERDICT, "confidence below threshold")
    _require(bool(verdict.basis), ErrorCode.NO_VERDICT, "basis must record missing propagation path")


def _guard_suspected(ctx: TransitionContext) -> None:
    _require(bool(ctx.reason), ErrorCode.NO_VERDICT, "downgrade reason required")


def _guard_review(ctx: TransitionContext) -> None:
    _require(bool(ctx.actor), ErrorCode.NO_VERDICT, "reviewer identity required")
    _require(bool(ctx.reason), ErrorCode.NO_VERDICT, "review reason required")


def _guard_grading(ctx: TransitionContext) -> None:
    verdict = ctx.verdict
    _require(verdict is not None and verdict.is_effective, ErrorCode.NO_VERDICT, "effective Verdict required")


def _guard_proven(ctx: TransitionContext) -> None:
    proof = ctx.proof
    _require(proof is not None, ErrorCode.REPRO_FAILED, "Proof required")
    assert proof is not None
    _require(proof.pre_patch_result is ProofResult.FAIL, ErrorCode.REPRO_FAILED, "pre_patch must fail")


def _guard_repro_failed(ctx: TransitionContext) -> None:
    _require(bool(ctx.reason), ErrorCode.REPRO_FAILED, "failure classification required")


def _guard_secondary_failure_to_l2(ctx: TransitionContext) -> None:
    _require(bool(ctx.reason), ErrorCode.REPRO_FAILED, "failure reason code required")


def _guard_patch_proof(ctx: TransitionContext) -> None:
    _require(ctx.proof is not None and ctx.proof.pre_patch_result is ProofResult.FAIL, ErrorCode.REPRO_FAILED, "valid Proof required")


def _guard_patch_quota(ctx: TransitionContext) -> None:
    patch = ctx.patch
    _require(patch is not None, ErrorCode.PATCH_OVERSIZED, "Patch required")
    assert patch is not None
    _require(patch.lines_changed <= ctx.patch_max_lines, ErrorCode.PATCH_OVERSIZED, f"lines_changed > {ctx.patch_max_lines}")
    _require(patch.files_changed <= ctx.patch_max_files, ErrorCode.PATCH_OVERSIZED, f"files_changed > {ctx.patch_max_files}")
    if patch.patch_strength < ctx.patch_strength_min:
        raise ApiError(ErrorCode.PATCH_WEAK, f"patch_strength {patch.patch_strength:.2f} < {ctx.patch_strength_min:.2f}")
    _require(patch.quotas_ok, ErrorCode.PATCH_OVERSIZED, "paradigm/quota check not passed")


def _guard_audit_passed(ctx: TransitionContext) -> None:
    findings = ctx.audit_findings
    _require(bool(findings), ErrorCode.AUDIT_HIT, "audit findings required")
    rejected = [finding for finding in findings if finding.verdict is AuditVerdict.REJECT]
    if rejected:
        finding = rejected[0]
        raise ApiError(ErrorCode.AUDIT_HIT, f"{finding.rule_id.value} {finding.reason} at {finding.hit_location}")
    proof = ctx.proof
    _require(proof is not None, ErrorCode.AUDIT_HIT, "Proof missing")
    assert proof is not None
    _require(
        ctx.registered_test_fingerprint is not None and proof.fingerprint == ctx.registered_test_fingerprint,
        ErrorCode.AUDIT_HIT,
        "test fingerprint mismatch (anti-cheat)",
    )


def _guard_audit_failed(ctx: TransitionContext) -> None:
    patch = ctx.patch
    rejected = [finding for finding in ctx.audit_findings if finding.verdict is AuditVerdict.REJECT]
    weak = patch is not None and patch.patch_strength < ctx.patch_strength_min
    _require(bool(rejected) or weak, ErrorCode.AUDIT_HIT, "no audit rejection or weak strength recorded")
    if patch is None:
        raise ApiError(ErrorCode.AUDIT_HIT, "Patch missing")


def _guard_backdoor(ctx: TransitionContext) -> None:
    hits = [
        finding
        for finding in ctx.audit_findings
        if finding.verdict is AuditVerdict.REJECT and finding.rule_id in BACKDOOR_RULES
    ]
    if not hits:
        raise ApiError(ErrorCode.BACKDOOR, "backdoor rule R2-R5 not hit")



def _gate_passed(ctx: TransitionContext) -> GateResult:
    gate = ctx.gate_result
    _require(gate is not None, ErrorCode.GATE_NOT_EXECUTED, "GateResult required")
    assert gate is not None
    _require(gate.outcome is GateOutcome.PASSED, ErrorCode.GATE_NOT_EXECUTED, "gate outcome not PASSED")
    _require(gate.red_green_paired, ErrorCode.GATE_RED_MISSING, "red/green pairing missing")
    _require(gate.regression_zero_fail, ErrorCode.GATE_NOT_EXECUTED, "regression not zero-fail")
    _require(
        gate.coverage_delta_pp >= -ctx.coverage_tolerance_pp,
        ErrorCode.GATE_NOT_EXECUTED,
        f"coverage drop > {ctx.coverage_tolerance_pp}pp",
    )
    _require(gate.rescan_new_alerts == 0, ErrorCode.GATE_NOT_EXECUTED, "rescan introduced new alerts")
    return gate


def _guard_l0(ctx: TransitionContext) -> None:
    _gate_passed(ctx)
    patch = ctx.patch
    _require(patch is not None, ErrorCode.PATCH_OVERSIZED, "Patch required")
    assert patch is not None
    _require(patch.fix_paradigm is FixParadigm.VERSION_UPGRADE, ErrorCode.GATE_NOT_EXECUTED, "L0 requires dependency-only change; use T15")


def _guard_l1(ctx: TransitionContext) -> None:
    _gate_passed(ctx)
    patch = ctx.patch
    _require(patch is not None, ErrorCode.PATCH_OVERSIZED, "Patch required")
    assert patch is not None
    _require(patch.fix_paradigm is not FixParadigm.VERSION_UPGRADE, ErrorCode.GATE_NOT_EXECUTED, "L1 requires code change; use T14")


def _guard_rollback(ctx: TransitionContext) -> None:
    _require(bool(ctx.gate_failure_reason), ErrorCode.GATE_NOT_EXECUTED, "gate failure reason required")


def _guard_reviewed_unfixable(ctx: TransitionContext) -> None:
    _require(bool(ctx.actor), ErrorCode.NO_VERDICT, "reviewer identity required")
    _require(bool(ctx.reason), ErrorCode.NO_VERDICT, "review reason required")


def _guard_rollback_done(ctx: TransitionContext) -> None:
    _require(ctx.branch_deleted, ErrorCode.GATE_NOT_EXECUTED, "branch deletion must complete idempotently")


TRANSITION_SPECS: dict[Transition, TransitionSpec] = {
    Transition.T0: TransitionSpec(Transition.T0, frozenset(), IssueStatus.RECEIVED, _guard_normalized, ErrorCode.NOT_NORMALIZED, "接入受理"),
    Transition.T1: TransitionSpec(Transition.T1, frozenset({IssueStatus.RECEIVED}), IssueStatus.TRIAGING, _guard_normalized, ErrorCode.NOT_NORMALIZED, "归一化完成"),
    Transition.T2: TransitionSpec(Transition.T2, frozenset({IssueStatus.TRIAGING}), IssueStatus.REACHABLE, _guard_reachable, ErrorCode.NO_VERDICT, "判定可达"),
    Transition.T3: TransitionSpec(Transition.T3, frozenset({IssueStatus.TRIAGING}), IssueStatus.ARCHIVED, _guard_unreachable, ErrorCode.NO_VERDICT, "判定不可达"),
    Transition.T4: TransitionSpec(Transition.T4, frozenset({IssueStatus.TRIAGING}), IssueStatus.SUSPECTED, _guard_suspected, ErrorCode.NO_VERDICT, "降级可疑"),
    Transition.T5: TransitionSpec(Transition.T5, frozenset({IssueStatus.SUSPECTED}), IssueStatus.TRIAGING, _guard_review, ErrorCode.NO_VERDICT, "人工复核重判"),
    Transition.T6: TransitionSpec(Transition.T6, frozenset({IssueStatus.REACHABLE}), IssueStatus.REPRODUCING, _guard_grading, ErrorCode.NO_VERDICT, "定级通过"),
    Transition.T7: TransitionSpec(Transition.T7, frozenset({IssueStatus.REPRODUCING}), IssueStatus.PROVEN, _guard_proven, ErrorCode.REPRO_FAILED, "红态确认"),
    Transition.T8: TransitionSpec(Transition.T8, frozenset({IssueStatus.REPRODUCING}), IssueStatus.REPRO_FAILED, _guard_repro_failed, ErrorCode.REPRO_FAILED, "复现失败"),
    Transition.T8B: TransitionSpec(Transition.T8B, frozenset({IssueStatus.REPRO_FAILED}), IssueStatus.DISPOSED_L2, _guard_secondary_failure_to_l2, ErrorCode.REPRO_FAILED, "复现失败转 L2"),
    Transition.T9: TransitionSpec(Transition.T9, frozenset({IssueStatus.PROVEN}), IssueStatus.PATCHING, _guard_patch_proof, ErrorCode.REPRO_FAILED, "进入补丁生成"),
    Transition.T10: TransitionSpec(Transition.T10, frozenset({IssueStatus.PATCHING}), IssueStatus.AUDITING, _guard_patch_quota, ErrorCode.PATCH_OVERSIZED, "补丁前置校验"),
    Transition.T11: TransitionSpec(Transition.T11, frozenset({IssueStatus.AUDITING}), IssueStatus.GATING, _guard_audit_passed, ErrorCode.AUDIT_HIT, "审计通过"),
    Transition.T12: TransitionSpec(Transition.T12, frozenset({IssueStatus.AUDITING}), IssueStatus.DISPOSED_L2, _guard_audit_failed, ErrorCode.AUDIT_HIT, "审计拒绝转 L2"),
    Transition.T13: TransitionSpec(Transition.T13, frozenset({IssueStatus.AUDITING}), IssueStatus.DISPOSED_L3, _guard_backdoor, ErrorCode.BACKDOOR, "后门拒绝"),
    Transition.T14: TransitionSpec(Transition.T14, frozenset({IssueStatus.GATING}), IssueStatus.DISPOSED_L0, _guard_l0, ErrorCode.GATE_NOT_EXECUTED, "三闸全过且仅依赖变更"),
    Transition.T15: TransitionSpec(Transition.T15, frozenset({IssueStatus.GATING}), IssueStatus.DISPOSED_L1, _guard_l1, ErrorCode.GATE_NOT_EXECUTED, "三闸全过且存在代码改动"),
    Transition.T16: TransitionSpec(Transition.T16, frozenset({IssueStatus.GATING}), IssueStatus.ROLLING_BACK, _guard_rollback, ErrorCode.GATE_NOT_EXECUTED, "门禁失败进入回滚"),
    Transition.T17: TransitionSpec(Transition.T17, frozenset({IssueStatus.GATING, IssueStatus.SUSPECTED}), IssueStatus.DISPOSED_L2, _guard_reviewed_unfixable, ErrorCode.NO_VERDICT, "复核判定不可修"),
    Transition.T18: TransitionSpec(Transition.T18, frozenset({IssueStatus.ROLLING_BACK}), IssueStatus.DISPOSED_L2, _guard_rollback_done, ErrorCode.GATE_NOT_EXECUTED, "回滚完成"),
}


class StateMachine:
    def spec(self, transition: Transition) -> TransitionSpec:
        return TRANSITION_SPECS[transition]

    def target_status(self, current: IssueStatus, transition: Transition, ctx: TransitionContext) -> IssueStatus:
        spec = self.spec(transition)
        if spec.source and current not in spec.source:
            raise StateTransitionError(transition, current, f"illegal source state; allowed: {sorted(s.value for s in spec.source)}")
        spec.guard(ctx)
        return spec.target

    def allowed(self, current: IssueStatus) -> list[Transition]:
        return [spec.transition for spec in TRANSITION_SPECS.values() if current in spec.source]

    def disposition_level(self, status: IssueStatus) -> DispositionLevel | None:
        mapping = {
            IssueStatus.DISPOSED_L0: DispositionLevel.L0,
            IssueStatus.DISPOSED_L1: DispositionLevel.L1,
            IssueStatus.DISPOSED_L2: DispositionLevel.L2,
            IssueStatus.DISPOSED_L3: DispositionLevel.L3,
        }
        return mapping.get(status)