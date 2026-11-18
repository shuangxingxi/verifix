from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.runtime.exec_domain import ExecDomain, FailureKind

EVIDENCE_ID_PATTERN = r"^(VER|SCAN|ISO)-[0-9]{8}T[0-9]{6}(\+[0-9]{4}|Z)-[0-9a-f]{4}$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
DEFAULT_ADOPTION_PATTERN = r"^(Q|O)-[0-9]{2}$"
FORBIDDEN_KEYS = frozenset(
    {
        "category",
        "reachable",
        "expected_fix_kind",
        "should_reject",
        "proof_pre_patch",
        "proof_post_patch",
        "answer_digest",
        "ground_truth",
    }
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CapabilityState(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    UNVERIFIED = "UNVERIFIED"


class Judgement(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNVERIFIED = "UNVERIFIED"


class BoundaryKind(str, Enum):
    REAL_CONTAINER = "REAL_CONTAINER"
    REAL_LOCAL = "REAL_LOCAL"
    RECORDED_STUB = "RECORDED_STUB"
    CLOUD_CREDENTIAL_MISSING = "CLOUD_CREDENTIAL_MISSING"


class DenialKind(str, Enum):
    PATH_NOT_EXIST = "PATH_NOT_EXIST"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    UNKNOWN = "UNKNOWN"



class ScanVerdict(str, Enum):
    ESTABLISHED = "ESTABLISHED"
    NOT_ESTABLISHED = "NOT_ESTABLISHED"
    UNVERIFIED = "UNVERIFIED"


class ExecMode(str, Enum):
    AUTO = "AUTO"
    CONTAINER = "CONTAINER"
    HOST = "HOST"


class VerificationSource(str, Enum):
    UNIT_TEST = "UNIT_TEST"
    REAL_EXECUTION = "REAL_EXECUTION"
    UNVERIFIED = "UNVERIFIED"


class _RealscanModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _forbidden_keys(self) -> "_RealscanModel":
        present = FORBIDDEN_KEYS.intersection(self.model_fields_set)
        if present:
            raise ValueError("realscan models must not use answer keys: " + ",".join(sorted(present)))
        return self


def _require_tz(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


class RuntimeFacts(_RealscanModel):
    network_mode: str = Field(min_length=1)
    read_only_rootfs: bool
    cap_drop: list[str] = Field(default_factory=list)
    security_opts: list[str] = Field(default_factory=list)
    user: str = Field(min_length=1)
    memory_bytes: int = Field(ge=0)
    nano_cpus: int = Field(ge=0)
    pids_limit: int = Field(ge=0)
    tmpfs_mounts: list[str] = Field(default_factory=list)
    docker_version: str = Field(min_length=1)
    runtime_driver: str = Field(min_length=1)
    cgroup_version: str = Field(min_length=1)


class EnvironmentCapability(_RealscanModel):
    docker_cli: CapabilityState
    daemon: CapabilityState
    socket_permission: CapabilityState
    image_availability: CapabilityState
    egress_network: CapabilityState
    loopback: CapabilityState
    detected_at: datetime = Field(default_factory=utc_now)
    exec_domain: ExecDomain
    runtime: RuntimeFacts
    details: list[str] = Field(default_factory=list)

    @field_validator("detected_at")
    @classmethod
    def _tz(cls, value: datetime) -> datetime:
        return _require_tz(value, "detected_at")

    def blocking_missing(self) -> list[str]:
        names = ("docker_cli", "daemon", "socket_permission", "image_availability")
        return [name for name in names if getattr(self, name) is CapabilityState.UNAVAILABLE]

    def all_available(self) -> bool:
        return not self.blocking_missing()


class ImageResolution(_RealscanModel):
    policy_image: str = Field(min_length=1)
    resolved_image: str = ""
    image_id: str = ""
    repo_digests: list[str] = Field(default_factory=list)
    local_build: bool = False
    alias_used: bool = False
    source: str = "MISSING"

    @model_validator(mode="after")
    def _consistency(self) -> "ImageResolution":
        if self.source not in {"POLICY_IMAGE", "LOCAL_ALIAS", "LOCAL_BUILD", "MISSING"}:
            raise ValueError(f"unsupported image source: {self.source}")
        if self.alias_used and not self.image_id:
            raise ValueError("alias image must carry image_id")
        if self.source == "MISSING" and (self.resolved_image or self.image_id):
            raise ValueError("missing image must not carry resolved identity")
        if self.image_id and not self.image_id.startswith("sha256:"):
            raise ValueError("image_id must use sha256: prefix")
        return self


class ConstraintCheck(_RealscanModel):
    check_id: str = Field(min_length=1)
    policy_key: str = Field(min_length=1)
    expected: str = ""
    observed: str = ""
    judgement: Judgement
    duration_ms: int = Field(ge=0, default=0)
    evidence_ref: str = ""
    basis: str = ""
    missing_reason: str = ""
    retest_hint: str = ""

    @model_validator(mode="after")
    def _unverified_explainable(self) -> "ConstraintCheck":
        if self.judgement is Judgement.UNVERIFIED:
            allowed = {"probe_timeout", "not_executed", "capability_unavailable", "terminated_early"}
            if self.missing_reason not in allowed:
                raise ValueError("unverified checks require a missing_reason from " + ",".join(sorted(allowed)))
            if not self.retest_hint.strip():
                raise ValueError("unverified checks require a retest_hint")
        return self


class DefaultAdoption(_RealscanModel):
    q_id: str = Field(pattern=DEFAULT_ADOPTION_PATTERN)
    value: str = Field(min_length=1)
    source: str = "SPEC_DEFAULT"
    pending: bool = True


class ConstraintVerificationRecord(_RealscanModel):
    verification_id: str = Field(pattern=EVIDENCE_ID_PATTERN)
    executed_at: datetime = Field(default_factory=utc_now)
    exec_domain: ExecDomain
    policy_version: str = Field(min_length=1)
    policy_sha256: str = Field(pattern=SHA256_PATTERN)
    image: ImageResolution
    privilege_route: str = Field(min_length=1)
    capability: EnvironmentCapability
    checks: list[ConstraintCheck] = Field(default_factory=list)
    verdict: Judgement = Judgement.UNVERIFIED
    evidence_ref: str = ""
    adopted_defaults: list[DefaultAdoption] = Field(default_factory=list)

    @field_validator("executed_at")
    @classmethod
    def _tz(cls, value: datetime) -> datetime:
        return _require_tz(value, "executed_at")

    @model_validator(mode="after")
    def _verdict_guard(self) -> "ConstraintVerificationRecord":
        if self.verdict is Judgement.PASS:
            if not self.checks:
                raise ValueError("PASS verification requires at least one check")
            if any(check.judgement is not Judgement.PASS for check in self.checks):
                raise ValueError("PASS verification must not contain non-PASS checks")
            if self.capability.blocking_missing():
                raise ValueError("PASS verification requires all blocking capabilities available")
        return self


class TargetView(_RealscanModel):
    view_id: str = Field(min_length=1)
    source_root: str = Field(min_length=1)
    view_root: str = Field(min_length=1)
    included_paths: list[str] = Field(default_factory=list)
    excluded_paths: list[str] = Field(default_factory=list)
    file_digests: dict[str, str] = Field(default_factory=dict)
    view_digest: str = Field(pattern=SHA256_PATTERN)
    truth_present: bool = False

    @model_validator(mode="after")
    def _no_truth(self) -> "TargetView":
        if self.truth_present:
            raise ValueError("target view must not contain the truth file")
        return self


class Detection(_RealscanModel):
    detection_id: str = Field(min_length=1)
    file: str = Field(min_length=1)
    line: int = Field(ge=1)
    rule_id: str = Field(min_length=1)
    defect_class: str = Field(min_length=1)
    source_kind: BoundaryKind = BoundaryKind.REAL_CONTAINER
    exec_location: str = Field(min_length=1)
    snippet_masked: str = ""
    rule_basis: str = ""


class DynamicCheck(_RealscanModel):
    check_id: str = Field(min_length=1)
    detection_id: str = Field(min_length=1)
    endpoint: str = Field(min_length=1)
    method: str = Field(min_length=1)
    normal_digest: str = ""
    injected_digest: str = ""
    behavior_diff: bool = False
    conclusion: str = "STATIC_ONLY"
    duration_ms: int = Field(ge=0, default=0)
    retries: int = Field(ge=0, default=0)


class ScanScope(_RealscanModel):
    defect_classes: list[str] = Field(default_factory=list)
    item_count: int = Field(ge=0, default=15)
    full_count: int = Field(ge=1, default=15)
    uncovered_classes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _scope_consistency(self) -> "ScanScope":
        if self.item_count < self.full_count and not self.uncovered_classes:
            raise ValueError("partial scope must declare uncovered_classes")
        return self


class ScanRecord(_RealscanModel):
    scan_id: str = Field(pattern=EVIDENCE_ID_PATTERN)
    target: str = Field(min_length=1)
    target_version: str = Field(min_length=1)
    target_view_digest: str = Field(pattern=SHA256_PATTERN)
    listen_port: int = Field(ge=0)
    port_source: str = "DYNAMIC"
    network_mode: str = "NONE_LOOPBACK"
    sandbox_scope: bool = False
    scope: ScanScope
    detections: list[Detection] = Field(default_factory=list)
    dynamic_checks: list[DynamicCheck] = Field(default_factory=list)
    scan_verdict: ScanVerdict = ScanVerdict.UNVERIFIED
    verdict_missing: list[str] = Field(default_factory=list)
    boundary_summary: dict[str, int] = Field(default_factory=dict)
    scan_phase_truth_reads: int = Field(ge=0, default=0)
    stub_count: int = Field(ge=0, default=0)
    cloud_section: str = ""
    repeat_diff: list[str] = Field(default_factory=list)
    interrupted_at: int | None = None
    completed_count: int = Field(ge=0, default=0)
    unverified_count: int = Field(ge=0, default=0)
    evidence_ref: str = ""
    adopted_defaults: list[DefaultAdoption] = Field(default_factory=list)

    @model_validator(mode="after")
    def _boundary_balance(self) -> "ScanRecord":
        if self.scan_phase_truth_reads != 0:
            raise ValueError("scan phase must not read the truth file")
        if self.boundary_summary:
            expected = len(self.detections) + len(self.dynamic_checks) + self.stub_count
            if self.cloud_section:
                expected += 1
            if sum(self.boundary_summary.values()) != expected:
                raise ValueError("boundary summary counts must equal detection and dynamic check totals")
        if self.scan_verdict is ScanVerdict.ESTABLISHED:
            if self.listen_port < 1:
                raise ValueError("established scan requires a live listen port")
            if not self.sandbox_scope:
                raise ValueError("established sandbox scan requires sandbox_scope=true")
            if self.network_mode != "NONE_LOOPBACK":
                raise ValueError("established sandbox scan requires NONE_LOOPBACK network mode")
        return self


class ReconcileRecord(_RealscanModel):
    reconcile_id: str = Field(min_length=1)
    scan_id: str = Field(min_length=1)
    truth_version: str = Field(min_length=1)
    truth_sha256: str = Field(pattern=SHA256_PATTERN)
    truth_read_count: int = Field(ge=0, default=1)
    read_phase: str = "POST_SCAN"
    matched: int = Field(ge=0, default=0)
    missing: list[str] = Field(default_factory=list)
    extra: list[str] = Field(default_factory=list)
    coverage: str = ""

    @model_validator(mode="after")
    def _read_once(self) -> "ReconcileRecord":
        if self.truth_read_count != 1:
            raise ValueError("reconcile must read the truth file exactly once")
        if self.read_phase != "POST_SCAN":
            raise ValueError("reconcile must run after the scan")
        return self


class IsolationProbeResult(_RealscanModel):
    probe: str = Field(min_length=1)
    result: str = Field(min_length=1)
    denial_kind: DenialKind = DenialKind.UNKNOWN


class IsolationBridgeRecord(_RealscanModel):
    iso_id: str = Field(pattern=EVIDENCE_ID_PATTERN)
    exec_identity: str = Field(min_length=1)
    exec_domain: ExecDomain
    visible_roots: list[str] = Field(default_factory=list)
    probes: list[IsolationProbeResult] = Field(default_factory=list)
    denial_kind: DenialKind = DenialKind.UNKNOWN
    exec_success_count: int = Field(ge=0, default=0)
    enforcement_mode: str = "MANDATORY_SELF_CHECK"
    publishable: bool = False
    failure_kind: FailureKind | None = None
    audit_ref: str = ""

    @model_validator(mode="after")
    def _publishable_guard(self) -> "IsolationBridgeRecord":
        if self.enforcement_mode not in {"MANDATORY_SELF_CHECK", "RECORD_ONLY"}:
            raise ValueError("unsupported enforcement mode")
        if any("expected" in root.lower() for root in self.visible_roots):
            raise ValueError("visible roots must not include the expected directory")
        if self.publishable:
            if self.exec_domain is not ExecDomain.CONTAINER_EXEC:
                raise ValueError("only the container domain can publish isolation results")
            if self.exec_success_count != 0:
                raise ValueError("publishable isolation requires exec_success_count=0")
            if self.failure_kind is not None:
                raise ValueError("publishable isolation must not carry a failure kind")
        return self


class BoundaryEntry(_RealscanModel):
    item_ref: str = Field(min_length=1)
    boundary_kind: BoundaryKind
    basis: str = Field(min_length=1)
    evidence_ref: str = ""
    stub_ref: str = ""

    @model_validator(mode="after")
    def _refs(self) -> "BoundaryEntry":
        if self.boundary_kind in {BoundaryKind.REAL_CONTAINER, BoundaryKind.REAL_LOCAL} and not self.evidence_ref:
            raise ValueError("real boundary entries require evidence_ref")
        if self.boundary_kind is BoundaryKind.RECORDED_STUB and not self.stub_ref:
            raise ValueError("stub boundary entries require stub_ref")
        return self


class EvidencePack(_RealscanModel):
    evidence_id: str = Field(pattern=EVIDENCE_ID_PATTERN)
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: int = Field(ge=0)
    commands: list[str] = Field(min_length=1)
    runtime_facts: dict[str, object] = Field(default_factory=dict)
    raw_output_digest: str = Field(pattern=SHA256_PATTERN)
    reuse_conditions: dict[str, object] = Field(default_factory=dict)
    boundary_tags: list[BoundaryKind] = Field(default_factory=list)
    verification_source: VerificationSource
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("created_at")
    @classmethod
    def _tz(cls, value: datetime) -> datetime:
        return _require_tz(value, "created_at")

    @field_validator("commands")
    @classmethod
    def _command_hygiene(cls, value: list[str]) -> list[str]:
        for command in value:
            if not command.strip():
                raise ValueError("evidence commands must not be blank")
            if "\n" in command:
                raise ValueError("each evidence command must be a single line")
        return value


_SHORT_RANDOM = re.compile(r"^[0-9a-f]{4}$")


def short_random_suffix(value: str) -> str:
    if not _SHORT_RANDOM.match(value):
        raise ValueError("short random suffix must be 4 lowercase hex characters")
    return value