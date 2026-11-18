from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import (
    AuditRuleId,
    AuditVerdict,
    CircuitStatus,
    DefectClass,
    DispositionLevel,
    EvalCategory,
    EventType,
    FixParadigm,
    GateOutcome,
    IssueStatus,
    MetricChannel,
    MetricId,
    ProofResult,
    ReproductionAttemptStatus,
    RunTerminalState,
    Severity,
    SourceKind,
    StageTier,
    StepKind,
    StepStatus,
    VerdictConclusion,
)

SCHEMA_VERSION = 1
BRANCH_NAMESPACE = "verifix/"
RELEASE_AUTO_BRANCH = "release/auto"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class _DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BlobRef(_DomainModel):
    ref: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    schema_version: int = SCHEMA_VERSION


class Location(_DomainModel):
    file: str = Field(min_length=1)
    line: int | None = Field(default=None, ge=1)
    component: str | None = None
    component_version: str | None = None

    @model_validator(mode="after")
    def _require_locator(self) -> "Location":
        if self.line is None and not (self.component and self.component_version):
            raise ValueError("Location requires either line or component+component_version")
        return self


class EnvSnapshot(_DomainModel):
    network_disabled: bool = True
    read_only: bool = True
    timeout_seconds: int = Field(default=60, ge=1, le=60)
    memory_mb: int = Field(default=1024, ge=1, le=1024)
    uid: int = Field(default=10001, ge=1)


class Alert(_DomainModel):
    alert_ref: str = Field(min_length=1)
    source_kind: SourceKind
    rule_id: str = Field(min_length=1)
    location: Location
    raw_severity: Severity
    snippet_fingerprint: str = Field(min_length=1)
    defect_class: DefectClass | None = None
    snippet: str = ""
    observed_at: datetime = Field(default_factory=utc_now)


class Issue(_DomainModel):
    issue_id: str = Field(min_length=1)
    repo: str = Field(min_length=1)
    code_version: str = Field(min_length=1)
    defect_class: DefectClass | None = None
    severity: Severity
    status: IssueStatus = IssueStatus.RECEIVED
    source_count: int = Field(default=1, ge=1)
    fingerprint: str = Field(min_length=1)
    in_scope: bool = True
    occurred_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    channel: MetricChannel = MetricChannel.MAIN

    @model_validator(mode="after")
    def _scope_requires_class(self) -> "Issue":
        if self.in_scope and self.defect_class is None:
            raise ValueError("in-scope Issue requires defect_class within C01/C02/C03/C05")
        return self


class Verdict(_DomainModel):
    verdict_id: str = Field(min_length=1)
    issue_id: str = Field(min_length=1)
    conclusion: VerdictConclusion
    confidence: float = Field(ge=0.0, le=1.0)
    taint_path: list[str] = Field(default_factory=list)
    basis: str = ""
    decided_by: str = Field(min_length=1)
    decided_at: datetime = Field(default_factory=utc_now)
    is_effective: bool = True

    @model_validator(mode="after")
    def _reachable_path(self) -> "Verdict":
        if self.conclusion is VerdictConclusion.REACHABLE and not self.taint_path:
            raise ValueError("Verdict.taint_path must not be empty when conclusion is REACHABLE")
        if self.conclusion is VerdictConclusion.UNREACHABLE and not self.basis:
            raise ValueError("Verdict.basis must record the missing-path evidence when conclusion is UNREACHABLE")
        return self


class Proof(_DomainModel):
    proof_id: str = Field(min_length=1)
    issue_id: str = Field(min_length=1)
    test_path: str = Field(min_length=1)
    pre_patch_result: ProofResult
    post_patch_result: ProofResult = ProofResult.NOT_RUN
    fingerprint: str = Field(min_length=1)
    env_snapshot: EnvSnapshot
    generated_marker: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _pre_patch_must_fail(self) -> "Proof":
        if self.pre_patch_result is not ProofResult.FAIL:
            raise ValueError("Proof.pre_patch_result must be FAIL")
        return self


class ReproductionAttempt(_DomainModel):
    attempt_id: str = Field(min_length=1)
    issue_id: str = Field(min_length=1)
    attempt_index: int = Field(ge=1)
    status: ReproductionAttemptStatus
    proof_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class PatchAttempt(_DomainModel):
    attempt_id: str = Field(min_length=1)
    issue_id: str = Field(min_length=1)
    attempt_index: int = Field(ge=1)
    patch_id: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)


class GateAttempt(_DomainModel):
    attempt_id: str = Field(min_length=1)
    patch_id: str = Field(min_length=1)
    issue_id: str = Field(min_length=1)
    outcome: GateOutcome = GateOutcome.NOT_EXECUTED
    red_green_paired: bool = False
    regression_zero_fail: bool = False
    rescan_new_alerts: int = Field(default=0, ge=0)
    coverage_delta_pp: float = 0.0
    evidence_missing: bool = False
    observed_at: datetime = Field(default_factory=utc_now)


class DispositionHistoryEntry(_DomainModel):
    attempt_id: str | None = None
    issue_id: str = Field(min_length=1)
    level: DispositionLevel
    gate_outcome: GateOutcome | None = None
    decided_at: datetime = Field(default_factory=utc_now)
    ready_at: datetime | None = None



class Patch(_DomainModel):
    patch_id: str = Field(min_length=1)
    issue_id: str = Field(min_length=1)
    proof_id: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    diff_ref: str = Field(min_length=1)
    lines_changed: int = Field(ge=0)
    files_changed: int = Field(ge=0)
    fix_paradigm: FixParadigm
    patch_strength: float = Field(ge=0.0, le=1.0)
    quotas_ok: bool = False
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _branch_namespace(self) -> "Patch":
        if not self.branch.startswith(BRANCH_NAMESPACE):
            raise ValueError(f"Patch.branch must use namespace {BRANCH_NAMESPACE}")
        if self.branch in {"main", "master"}:
            raise ValueError("Patch.branch must never target main/master")
        return self


class AuditFinding(_DomainModel):
    patch_id: str = Field(min_length=1)
    rule_id: AuditRuleId
    threshold: str = Field(min_length=1)
    hit_location: str = Field(min_length=1)
    verdict: AuditVerdict
    reason: str = ""


class GateResult(_DomainModel):
    gate_result_id: str = Field(min_length=1)
    patch_id: str = Field(min_length=1)
    gate_run_ref: str = Field(min_length=1)
    red_green_paired: bool = False
    regression_zero_fail: bool = False
    coverage_delta_pp: float = 0.0
    rescan_new_alerts: int = Field(default=0, ge=0)
    outcome: GateOutcome = GateOutcome.NOT_EXECUTED
    evidence_missing: bool = False
    observed_at: datetime = Field(default_factory=utc_now)


class Disposition(_DomainModel):
    disposition_id: str = Field(min_length=1)
    issue_id: str = Field(min_length=1)
    level: DispositionLevel
    action: str = Field(min_length=1)
    evidence_ref: str = Field(min_length=1)
    reason_code: str = Field(min_length=1)
    decided_at: datetime = Field(default_factory=utc_now)
    gate_outcome: GateOutcome | None = None
    ready_at: datetime | None = None

    @model_validator(mode="after")
    def _l0_l1_require_gate(self) -> "Disposition":
        if self.level in {DispositionLevel.L0, DispositionLevel.L1} and self.gate_outcome is not GateOutcome.PASSED:
            raise ValueError("Disposition.level L0/L1 requires GateResult.outcome PASSED")
        return self


class RunStep(_DomainModel):
    kind: StepKind
    status: StepStatus = StepStatus.NOT_RUN
    started_at: datetime | None = None
    ended_at: datetime | None = None
    evidence_ref: str | None = None
    detail: str = ""


class Run(_DomainModel):
    run_id: str = Field(min_length=1)
    issue_id: str = Field(min_length=1)
    started_at: datetime = Field(default_factory=utc_now)
    ended_at: datetime | None = None
    terminal_state: RunTerminalState | None = None
    deadline_at: datetime
    steps: list[RunStep] = Field(default_factory=list)

    def missing_steps(self) -> list[str]:
        return [step.kind.value for step in self.steps if step.status is StepStatus.NOT_RUN]


class Event(_DomainModel):
    event_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    seq: int = Field(ge=1)
    event_type: EventType
    occurred_at: datetime = Field(default_factory=utc_now)
    actor: str = Field(min_length=1)
    step: StepKind | None = None
    payload_ref: str | None = None
    prev_hash: str = ""
    self_hash: str = ""
    schema_version: int = SCHEMA_VERSION


class Metric(_DomainModel):
    metric_id: MetricId
    stage_tier: StageTier
    window: str = Field(min_length=1)
    definition_version: str = Field(min_length=1)
    value: float | None = None
    source_ref: str = Field(min_length=1)
    computed_at: datetime = Field(default_factory=utc_now)
    computable: bool = True
    reason_code: str | None = None
    channel: MetricChannel = MetricChannel.MAIN
    recalc_id: str | None = None
    snapshot_id: str | None = None
    snapshot_digest: str | None = None
    numerator: float | None = None
    denominator: float | None = None
    covered_count: int = Field(default=0, ge=0)
    excluded_count: int = Field(default=0, ge=0)
    channel_excluded_count: int = Field(default=0, ge=0)
    not_applicable_count: int = Field(default=0, ge=0)
    exclusion_ref: str | None = None
    trial: bool = False
    last_success_at: datetime | None = None
    unverified: bool = False
    unverified_reason: str | None = None

    @model_validator(mode="after")
    def _uncomputable_has_no_value(self) -> "Metric":
        if self.computable and self.value is None:
            raise ValueError("computable Metric requires a numeric value")
        if not self.computable and self.value is not None:
            raise ValueError("uncomputable Metric must not carry a value")
        if self.trial and self.computable:
            raise ValueError("trial Metric must not be computable")
        if self.unverified:
            if self.metric_id is not MetricId.M9:
                raise ValueError("only M9 may be marked unverified")
            if self.computable:
                raise ValueError("unverified Metric must not be computable")
            if self.value is not None:
                raise ValueError("unverified Metric must not carry a value")
            if self.reason_code != "EVIDENCE_MISSING":
                raise ValueError("unverified Metric must use EVIDENCE_MISSING")
        elif self.computable:
            self.unverified_reason = None
        return self


class MetricDefinitionRecord(_DomainModel):
    metric_id: MetricId
    name: str = Field(min_length=1)
    numerator_spec: str = Field(min_length=1)
    denominator_spec: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    channel: MetricChannel
    source_bindings: list[str] = Field(default_factory=list)
    definition_version: str = Field(min_length=1)
    effective_at: datetime
    preliminary_target: float | None = None
    finals_target: float | None = None
    direction: str = "HIGHER_IS_BETTER"
    note: str = ""


class MetricSnapshotRef(_DomainModel):
    snapshot_id: str = Field(min_length=1)
    window: str = Field(min_length=1)
    tier: StageTier
    digest: str = Field(min_length=1)
    generated_at: datetime = Field(default_factory=utc_now)
    issue_count: int = Field(default=0, ge=0)
    event_count: int = Field(default=0, ge=0)
    record_counts: dict[str, int] = Field(default_factory=dict)
    chain_valid: bool = False
    capture_ms: int = Field(default=0, ge=0)
    redaction_hits: int = Field(default=0, ge=0)
    used_by: list[str] = Field(default_factory=list)


class RecalcRun(_DomainModel):
    recalc_id: str = Field(min_length=1)
    window: str = Field(min_length=1)
    tier: StageTier
    trigger: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    definition_versions: list[str] = Field(default_factory=list)
    status: str = Field(min_length=1)
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    issue_total: int = Field(default=0, ge=0)
    excluded_total: int = Field(default=0, ge=0)
    reason_distribution: dict[str, int] = Field(default_factory=dict)
    failure_reason: str = ""
    late: bool = False


class ExclusionEntry(_DomainModel):
    issue_id: str = Field(min_length=1)
    reason_code: str = Field(min_length=1)
    detail: str = ""
    metric_id: MetricId
    recalc_id: str = Field(min_length=1)


class MetricReport(_DomainModel):
    report_id: str = Field(min_length=1)
    version: int = Field(default=1, ge=1)
    window: str = Field(min_length=1)
    tier: StageTier
    definition_version: str = Field(min_length=1)
    conclusion: str = Field(min_length=1)
    generated_at: datetime = Field(default_factory=utc_now)
    content_digest: str = ""
    archive_ref: str = ""
    archived_at: datetime | None = None
    eval_run_id: str | None = None
    binding_digest: str | None = None
    history_digest: str | None = None


class GroundTruth(_DomainModel):
    reachable: bool
    fixable: bool
    expected_fix_kind: FixParadigm
    should_reject: bool


class EvalCase(_DomainModel):
    case_id: str = Field(pattern=r"^EVAL-\d{4}$")
    category: EvalCategory
    location: Location
    rule_id: str = Field(min_length=1)
    severity: Severity
    ground_truth: GroundTruth
    proof_test_path: str | None = None
    proof_pre_patch: ProofResult | None = None
    proof_post_patch: ProofResult | None = None
    content_digest: str = Field(min_length=1)

    @model_validator(mode="after")
    def _positive_case_has_proof(self) -> "EvalCase":
        if self.category is EvalCategory.POSITIVE:
            if not self.proof_test_path or self.proof_pre_patch is None or self.proof_post_patch is None:
                raise ValueError("POSITIVE EvalCase requires proof test path and pre/post patch expectations")
        return self


class BlacklistEntry(_DomainModel):
    fingerprint: str = Field(min_length=1)
    failed_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime


class CircuitState(_DomainModel):
    defect_class: DefectClass
    fail_streak: int = Field(default=0, ge=0)
    state: CircuitStatus = CircuitStatus.CLOSED
    opened_at: datetime | None = None
    blacklist_entries: list[BlacklistEntry] = Field(default_factory=list)