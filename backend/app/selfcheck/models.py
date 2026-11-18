"""自检框架的领域模型。

本模块只定义枚举与不可变数据契约，不包含任何 I/O、子进程或文件写入。
字段与 `.codeartsdoer/specs/selfcheck_harness/design.md` §2.3.2 类图对齐；
`CheckSpec.handler` 是"定义 + 执行"两职中的执行绑定，语义等价于类图里的
`execute(ctx)` 方法，不引入新的业务字段。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class Dimension(str, Enum):
    REPRODUCIBLE = "D1"
    CAPABILITY = "D2"
    EVIDENCE = "D3"
    CONSISTENCY = "D4"
    DELIVERY = "D5"

    @property
    def label(self) -> str:
        return {
            Dimension.REPRODUCIBLE: "可复现性",
            Dimension.CAPABILITY: "能力真实性",
            Dimension.EVIDENCE: "证据完整性",
            Dimension.CONSISTENCY: "口径一致性",
            Dimension.DELIVERY: "交付完整性",
        }[self]


DIMENSION_ORDER: tuple[Dimension, ...] = (
    Dimension.REPRODUCIBLE,
    Dimension.CAPABILITY,
    Dimension.EVIDENCE,
    Dimension.CONSISTENCY,
    Dimension.DELIVERY,
)

DIMENSION_BY_CODE: dict[str, Dimension] = {item.value: item for item in Dimension}


class Status(str, Enum):
    PASS = "通过"
    WARNING = "警告"
    BLOCKED = "阻塞"
    MANUAL_PENDING = "人工待填"
    UNVERIFIED = "未验证"


STATUS_ORDER: tuple[Status, ...] = (
    Status.PASS,
    Status.WARNING,
    Status.BLOCKED,
    Status.MANUAL_PENDING,
    Status.UNVERIFIED,
)

# 状态严格程度：数字越大越严格，用于依赖传导与冲突合并。
STATUS_SEVERITY: dict[Status, int] = {
    Status.PASS: 0,
    Status.WARNING: 1,
    Status.UNVERIFIED: 2,
    Status.MANUAL_PENDING: 3,
    Status.BLOCKED: 4,
}


class JudgmentMode(str, Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"


class ThreeQuestion(str, Enum):
    REAL = "真实"
    BOUNDARY = "边界"
    REPRODUCE = "复现"


class VerificationKind(str, Enum):
    REAL_EXECUTION = "REAL_EXECUTION"
    STUB = "STUB"
    INFERRED = "INFERRED"


_CHECK_ID_RE = re.compile(r"^D[1-5]-\d+$")


@dataclass
class CheckSpec:
    """一个检查项的不可变定义。`handler` 为空表示尚未实装（返回未验证）。"""

    check_id: str
    title: str
    dimension: Dimension
    mode: JudgmentMode
    question: ThreeQuestion
    criterion: str
    depends_on: tuple[str, ...] = ()
    timeout_seconds: float = 600.0
    handler: Optional[Callable[[Any], "CheckResult"]] = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if not _CHECK_ID_RE.match(self.check_id):
            raise ValueError(f"invalid check id: {self.check_id!r}")
        if not isinstance(self.dimension, Dimension):
            raise ValueError(f"{self.check_id}: dimension must be Dimension")
        if not isinstance(self.mode, JudgmentMode):
            raise ValueError(f"{self.check_id}: mode must be JudgmentMode")
        if not isinstance(self.question, ThreeQuestion):
            raise ValueError(f"{self.check_id}: question must be ThreeQuestion")
        if not str(self.criterion).strip():
            raise ValueError(f"{self.check_id}: criterion must not be empty")
        if not isinstance(self.depends_on, tuple):
            raise ValueError(f"{self.check_id}: depends_on must be a tuple")
        if self.timeout_seconds <= 0:
            raise ValueError(f"{self.check_id}: timeout_seconds must be positive")

    @property
    def is_implemented(self) -> bool:
        return self.handler is not None

    def execute(self, ctx: Any) -> "CheckResult":
        if self.handler is None:
            return build_result(
                self,
                Status.UNVERIFIED,
                sub_reason="NOT_IMPLEMENTED",
                output_summary="本项尚未实装，按未验证处理。",
            )
        return self.handler(ctx)


@dataclass
class CheckResult:
    check_id: str
    dimension: Dimension
    mode: JudgmentMode
    question: ThreeQuestion
    status: Status
    sub_reason: Optional[str] = None
    command: Optional[str] = None
    exit_code: Optional[int] = None
    output_digest: Optional[str] = None
    output_summary: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    duration_seconds: float = 0.0
    baseline_change: str = ""


@dataclass
class ProbeOutput:
    exit_code: Optional[int]
    stdout_tail: str = ""
    stderr_tail: str = ""
    duration_seconds: float = 0.0
    timed_out: bool = False
    unavailable: bool = False


@dataclass
class ClaimRecord:
    claim_id: str
    text: str
    carrier: str
    location: str
    claim_type: str
    level: Optional[str] = None
    source: Optional[str] = None
    evidence_refs: list[str] = field(default_factory=list)
    sample_size: Optional[int] = None
    confirmed: Optional[bool] = None


@dataclass
class EvidenceEntry:
    evidence_id: str
    path: str
    index_sha256: str
    manifest_sha256: str = ""
    recomputed_sha256: str = ""
    verification_source: str = ""
    referenced_by: list[str] = field(default_factory=list)
    integrity_ok: bool = False
    mismatches: list[str] = field(default_factory=list)


@dataclass
class ConsistencyRow:
    field: str
    values_by_carrier: dict[str, str] = field(default_factory=dict)
    sample_size: str = ""
    definition_version: str = "v2"
    verdict: str = ""
    conflict_level: str = ""


@dataclass
class DeliveryRow:
    template_item: str
    mapped_file: Optional[str] = None
    mapped_section: Optional[str] = None
    gap_level: str = ""
    cost_estimate: str = ""


@dataclass
class DimensionSummary:
    dimension: Dimension
    passed: int = 0
    warning: int = 0
    blocked: int = 0
    manual_pending: int = 0
    unverified: int = 0


@dataclass
class SelfcheckResult:
    format_version: str = "1.0"
    definition_version: str = "v2"
    run_id: str = ""
    fingerprint: str = ""
    generated_at: str = ""
    scope: list[str] = field(default_factory=list)
    baseline_id: Optional[str] = None
    overall: str = "未完成"
    exit_code: int = 3
    readonly_ok: bool = True
    checks: list[CheckResult] = field(default_factory=list)
    dimensions: list[DimensionSummary] = field(default_factory=list)
    claims: list[ClaimRecord] = field(default_factory=list)
    evidence: list[EvidenceEntry] = field(default_factory=list)
    consistency: list[ConsistencyRow] = field(default_factory=list)
    delivery: list[DeliveryRow] = field(default_factory=list)
    weakest_link: str = ""
    top_questions: list[str] = field(default_factory=list)
    fix_priority: list[str] = field(default_factory=list)
    self_digest: Optional[str] = None


@dataclass
class WriteOutcome:
    run_id: str
    archive_dir: str
    report_path: str
    json_path: str
    index_updated: bool
    entry_updated: bool
    self_digest: str


def build_result(
    spec: CheckSpec,
    status: Status,
    *,
    sub_reason: Optional[str] = None,
    command: Optional[str] = None,
    exit_code: Optional[int] = None,
    output_digest: Optional[str] = None,
    output_summary: str = "",
    evidence_refs: Optional[list[str]] = None,
    duration_seconds: float = 0.0,
) -> CheckResult:
    return CheckResult(
        check_id=spec.check_id,
        dimension=spec.dimension,
        mode=spec.mode,
        question=spec.question,
        status=status,
        sub_reason=sub_reason,
        command=command,
        exit_code=exit_code,
        output_digest=output_digest,
        output_summary=output_summary,
        evidence_refs=list(evidence_refs or []),
        duration_seconds=duration_seconds,
    )


def summarize_dimensions(checks: list[CheckResult]) -> list[DimensionSummary]:
    summaries: list[DimensionSummary] = []
    for dimension in DIMENSION_ORDER:
        summary = DimensionSummary(dimension=dimension)
        for check in checks:
            if check.dimension is not dimension:
                continue
            if check.status is Status.PASS:
                summary.passed += 1
            elif check.status is Status.WARNING:
                summary.warning += 1
            elif check.status is Status.BLOCKED:
                summary.blocked += 1
            elif check.status is Status.MANUAL_PENDING:
                summary.manual_pending += 1
            elif check.status is Status.UNVERIFIED:
                summary.unverified += 1
        summaries.append(summary)
    return summaries


def derive_overall(checks: list[CheckResult], *, readonly_ok: bool) -> tuple[str, int]:
    """按设计 §2.4.4 顺序判定，命中即停，不以通过项数量参与判定。"""

    if not readonly_ok:
        return "不通过", 3
    statuses = {check.status for check in checks}
    if Status.BLOCKED in statuses:
        return "不通过", 3
    if Status.MANUAL_PENDING in statuses:
        return "未完成", 3
    if Status.WARNING in statuses:
        return "通过（附警告）", 2
    if Status.UNVERIFIED in statuses:
        return "未完成", 2
    return "通过", 0