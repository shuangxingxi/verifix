from __future__ import annotations

from enum import Enum


class DefectClass(str, Enum):
    DEPENDENCY_CVE = "C01"
    SQL_INJECTION = "C02"
    COMMAND_INJECTION = "C03"
    HARDCODED_SECRET = "C05"


class OutOfScopeClass(str, Enum):
    PATH_TRAVERSAL = "C04"
    WEAK_CRYPTO = "C06"
    LOG_LEAK = "C07"
    SSRF = "C08"
    DESERIALIZATION = "C09"
    CONFIG_BASELINE = "C10"
    INSECURE_RANDOM = "C11"
    RACE_CONDITION = "C12"


class IssueStatus(str, Enum):
    RECEIVED = "RECEIVED"
    TRIAGING = "TRIAGING"
    REACHABLE = "REACHABLE"
    SUSPECTED = "SUSPECTED"
    ARCHIVED = "ARCHIVED"
    REPRODUCING = "REPRODUCING"
    PROVEN = "PROVEN"
    REPRO_FAILED = "REPRO_FAILED"
    PATCHING = "PATCHING"
    AUDITING = "AUDITING"
    GATING = "GATING"
    ROLLING_BACK = "ROLLING_BACK"
    DISPOSED_L0 = "DISPOSED_L0"
    DISPOSED_L1 = "DISPOSED_L1"
    DISPOSED_L2 = "DISPOSED_L2"
    DISPOSED_L3 = "DISPOSED_L3"


TERMINAL_STATUSES = frozenset(
    {
        IssueStatus.ARCHIVED,
        IssueStatus.REPRO_FAILED,
        IssueStatus.DISPOSED_L0,
        IssueStatus.DISPOSED_L1,
        IssueStatus.DISPOSED_L2,
        IssueStatus.DISPOSED_L3,
    }
)


class RunTerminalState(str, Enum):
    DISPOSED = "DISPOSED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    CIRCUIT_SKIPPED = "CIRCUIT_SKIPPED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class VerdictConclusion(str, Enum):
    REACHABLE = "REACHABLE"
    UNREACHABLE = "UNREACHABLE"
    SUSPECTED = "SUSPECTED"


class DispositionLevel(str, Enum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class SourceKind(str, Enum):
    CHECK = "CHECK"
    GOVERNANCE = "GOVERNANCE"
    OSV = "OSV"
    CNVD = "CNVD"
    RUNTIME_ALERT = "RUNTIME_ALERT"
    MANUAL = "MANUAL"


class EventType(str, Enum):
    INGEST = "INGEST"
    VERDICT = "VERDICT"
    PROOF = "PROOF"
    PATCH = "PATCH"
    AUDIT = "AUDIT"
    GATE = "GATE"
    DISPOSITION = "DISPOSITION"
    ROLLBACK = "ROLLBACK"
    CIRCUIT = "CIRCUIT"
    ALERT = "ALERT"
    REDACTION = "REDACTION"
    CONTROL = "CONTROL"


class StepKind(str, Enum):
    INGEST = "INGEST"
    VERDICT = "VERDICT"
    PROOF = "PROOF"
    PATCH = "PATCH"
    AUDIT = "AUDIT"
    GATE = "GATE"
    DISPOSITION = "DISPOSITION"


class StepStatus(str, Enum):
    NOT_RUN = "NOT_RUN"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


class ProofResult(str, Enum):
    FAIL = "FAIL"
    PASS = "PASS"
    NOT_RUN = "NOT_RUN"


class FixParadigm(str, Enum):
    VERSION_UPGRADE = "VERSION_UPGRADE"
    PARAMETERIZED_QUERY = "PARAMETERIZED_QUERY"
    PARAMETERIZED_COMMAND = "PARAMETERIZED_COMMAND"
    CREDENTIAL_EXTERNALIZATION = "CREDENTIAL_EXTERNALIZATION"


class AuditRuleId(str, Enum):
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"
    R5 = "R5"
    R6 = "R6"


BACKDOOR_RULES = frozenset({AuditRuleId.R2, AuditRuleId.R3, AuditRuleId.R4, AuditRuleId.R5})


class AuditVerdict(str, Enum):
    PASS = "PASS"
    REJECT = "REJECT"


class GateOutcome(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    NOT_EXECUTED = "NOT_EXECUTED"


class CircuitStatus(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"


class EvalCategory(str, Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    BOUNDARY = "BOUNDARY"
    ADVERSARIAL = "ADVERSARIAL"


class StageTier(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    FINALS = "FINALS"


class MetricChannel(str, Enum):
    MAIN = "MAIN"
    EVAL = "EVAL"
    UNKNOWN = "UNKNOWN"


class ReproductionAttemptStatus(str, Enum):
    PROVEN = "PROVEN"
    REPRO_FAILED = "REPRO_FAILED"
    INVALID_TEST = "INVALID_TEST"
    INFRA_ERROR = "INFRA_ERROR"


class MetricId(str, Enum):
    M1 = "M1"
    M2 = "M2"
    M3 = "M3"
    M4 = "M4"
    M5 = "M5"
    M6 = "M6"
    M7 = "M7"
    M8 = "M8"
    M9 = "M9"