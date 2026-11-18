from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

ENV_PREFIX = "VERIFIX_"
DEFAULT_CONFIG_FILE = "config.yaml"
MAX_RUN_DEADLINE_SECONDS = 900
MAX_SANDBOX_MEMORY_MB = 1024
MAX_SANDBOX_SECONDS = 60
MAX_SANDBOX_CPU = 1.0
MAX_MODEL_CALLS_PER_ISSUE = 5
FROZEN_BRANCH_NAMESPACE = "verifix/"
FROZEN_RELEASE_AUTO_BRANCH = "release/auto"
FROZEN_PATCH_MAX_LINES = 30
FROZEN_PATCH_MAX_FILES = 3
FROZEN_PATCH_STRENGTH_MIN = 0.60
PROTECTED_BRANCHES = frozenset({"main", "master"})

_MEMORY_PATTERN = re.compile(r"^\s*(\d+)\s*(m|g|mb|gb)?\s*$", re.IGNORECASE)


class ConfigValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("invalid configuration: " + "; ".join(errors))


def parse_memory_mb(value: str) -> int:
    match = _MEMORY_PATTERN.match(str(value))
    if not match:
        raise ValueError(f"sandbox.mem has invalid format: {value!r}")
    amount = int(match.group(1))
    unit = (match.group(2) or "m").lower()
    return amount * 1024 if unit in {"g", "gb"} else amount


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProductConfig(_Strict):
    brand: str = Field(default="VeriFix", min_length=1)


class BranchConfig(_Strict):
    namespace: str = FROZEN_BRANCH_NAMESPACE


class ReleaseConfig(_Strict):
    auto_branch: str = FROZEN_RELEASE_AUTO_BRANCH


class RunConfig(_Strict):
    deadline_seconds: int = 900
    max_concurrency: int = 3


class StageTimeoutConfig(_Strict):
    triage_seconds: int = 30
    reproduce_seconds: int = 120
    patch_seconds: int = 120
    audit_seconds: int = 60
    gate_readback_seconds: int = 540

    def total_seconds(self) -> int:
        return (
            self.triage_seconds
            + self.reproduce_seconds
            + self.patch_seconds
            + self.audit_seconds
            + self.gate_readback_seconds
        )


class SandboxConfig(_Strict):
    cpu: float = 1.0
    mem: str = "1g"
    seconds: int = 60

    def memory_mb(self) -> int:
        return parse_memory_mb(self.mem)


class PatchConfig(_Strict):
    max_lines: int = FROZEN_PATCH_MAX_LINES
    max_files: int = FROZEN_PATCH_MAX_FILES
    strength_l0_l1_min: float = FROZEN_PATCH_STRENGTH_MIN


class SuspicionConfig(_Strict):
    threshold: float = 0.60


class CircuitConfig(_Strict):
    fail_streak: int = 3
    blacklist_ttl_hours: int = 72


class ModelConfig(_Strict):
    provider: str = "deepseek-v3"
    max_calls_per_issue: int = 5
    call_timeout_seconds: int = 60


class CodeArtsConfig(_Strict):
    ruleset: str = ""
    pipeline_id: str = ""


class EvalConfig(_Strict):
    cases_dir: str = "eval/cases"
    expected_dir: str = "eval/expected"
    legacy_set_path: str = "eval/eval_set.json"
    set_version: str = "1.0.0"
    isolation_probe_timeout_ms: int = 2000
    max_violations: int = 3
    leak_scan_budget_ms: int = 5000
    report_dir: str = "docs/devlog"


class MetricsConfig(_Strict):
    definition_version: str = "v2"
    exclusion_ratio_limit: float = 0.10
    coverage_delta_tolerance_pp: float = 0.5
    snapshot_dir: str = ".evidence"
    report_dir: str = "docs/devlog/metrics"
    eval_run_dir: str = "eval/runs"
    self_run_sample_path: str = ".evidence/self_run_samples.jsonl"
    scheduler_enabled: bool = False
    scheduler_tick_seconds: int = 300
    recalc_on_close_delay_seconds: int = 3600
    daily_recalc_seconds: int = 86400
    operator_token: str = ""
    capture_budget_ms: int = 200
    m9_min_continuous_seconds: int = 86400
    m9_min_sample_gap_seconds: int = 60
    m9_max_sample_gap_seconds: int = 120
    m9_max_sample_age_seconds: int = 150
    m9_max_tracker_skew_seconds: int = 60
    history_baseline: str = "docs/devlog/m5-eval-report.md=931d20442673b0922a32cfb42de1dcc9996925836607f6ddedbc5e8b1f165502"


DEFAULT_Q_DEFAULTS: dict[str, str] = {
    "Q-01": "A",
    "Q-02": "A",
    "Q-03": "A",
    "Q-04": "C",
    "Q-05": "A",
    "Q-06": "A",
    "Q-07": "A",
    "Q-08": "A",
    "Q-09": "A",
    "Q-10": "A",
}

REALSCAN_MAX_PROBE_BUDGET = 10
REALSCAN_MAX_CONSTRAINT_BUDGET = 180
REALSCAN_MAX_SCAN_BUDGET = 180
REALSCAN_MAX_EVIDENCE_BUDGET = 3


class RealscanConfig(_Strict):
    policy_path: str = "sandbox/spec.json"
    target_root: str = "verifix-target"
    cases_dir: str = "eval/cases"
    expected_dir: str = "eval/expected"
    evidence_root: str = ".evidence/sandbox-realscan"
    runtime_transport: str = "auto"
    wsl_distro: str = "Debian"
    wsl_user: str = "root"
    sandbox_images: list[str] = Field(default_factory=lambda: ["verifix-sandbox:1.0.0", "verifix-runner:latest"])
    target_images: list[str] = Field(default_factory=lambda: ["verifix-target:1.0.0", "realscan-probe:local"])
    listen_port: int = 0
    port_retries: int = 3
    health_timeout_seconds: int = 15
    request_timeout_seconds: int = 5
    request_retries: int = 3
    scan_scope: str = "full"
    allow_host_fallback: bool = True
    p4_05_enabled: bool = True
    probe_budget_seconds: int = 10
    constraint_budget_seconds: int = 180
    scan_budget_seconds: int = 180
    evidence_budget_seconds: int = 3
    q_defaults: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_Q_DEFAULTS))


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product: ProductConfig = Field(default_factory=ProductConfig)
    branch: BranchConfig = Field(default_factory=BranchConfig)
    release: ReleaseConfig = Field(default_factory=ReleaseConfig)
    run: RunConfig = Field(default_factory=RunConfig)
    stage: StageTimeoutConfig = Field(default_factory=StageTimeoutConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    patch: PatchConfig = Field(default_factory=PatchConfig)
    suspicion: SuspicionConfig = Field(default_factory=SuspicionConfig)
    circuit: CircuitConfig = Field(default_factory=CircuitConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    codearts: CodeArtsConfig = Field(default_factory=CodeArtsConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    eval: EvalConfig = Field(default_factory=EvalConfig)
    realscan: RealscanConfig = Field(default_factory=RealscanConfig)
    frozen_overrides: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_ranges(self) -> "AppConfig":
        errors: list[str] = []
        if not 0 < self.run.deadline_seconds <= MAX_RUN_DEADLINE_SECONDS:
            errors.append(
                f"run.deadline_seconds must be within (0, {MAX_RUN_DEADLINE_SECONDS}], got {self.run.deadline_seconds}"
            )
        if self.stage.total_seconds() >= self.run.deadline_seconds:
            errors.append(
                "stage.timeout.* sum "
                f"({self.stage.total_seconds()}s) must be less than run.deadline_seconds "
                f"({self.run.deadline_seconds}s)"
            )
        for name in ("triage_seconds", "reproduce_seconds", "patch_seconds", "audit_seconds", "gate_readback_seconds"):
            if getattr(self.stage, name) <= 0:
                errors.append(f"stage.{name} must be positive")
        if self.stage.gate_readback_seconds > 600:
            errors.append(
                f"stage.gate_readback_seconds must not exceed 600, got {self.stage.gate_readback_seconds}"
            )
        if not 1 <= self.run.max_concurrency <= 8:
            errors.append(f"run.max_concurrency must be within [1, 8], got {self.run.max_concurrency}")
        try:
            memory_mb = self.sandbox.memory_mb()
        except ValueError as exc:
            errors.append(str(exc))
            memory_mb = MAX_SANDBOX_MEMORY_MB
        if memory_mb > MAX_SANDBOX_MEMORY_MB:
            errors.append(f"sandbox.mem must not exceed 1g, got {self.sandbox.mem}")
        if not 0 < self.sandbox.cpu <= MAX_SANDBOX_CPU:
            errors.append(f"sandbox.cpu must be within (0, {MAX_SANDBOX_CPU}], got {self.sandbox.cpu}")
        if not 0 < self.sandbox.seconds <= MAX_SANDBOX_SECONDS:
            errors.append(f"sandbox.seconds must be within (0, {MAX_SANDBOX_SECONDS}], got {self.sandbox.seconds}")
        if not 0 < self.suspicion.threshold < 1:
            errors.append(f"suspicion.threshold must be within (0, 1), got {self.suspicion.threshold}")
        if self.circuit.fail_streak < 1:
            errors.append("circuit.fail_streak must be at least 1")
        if self.circuit.blacklist_ttl_hours < 1:
            errors.append("circuit.blacklist_ttl_hours must be at least 1")
        if not 0 < self.model.call_timeout_seconds <= 60:
            errors.append("model.call_timeout_seconds must be within (0, 60]")
        if not 1 <= self.model.max_calls_per_issue <= MAX_MODEL_CALLS_PER_ISSUE:
            errors.append(
                f"model.max_calls_per_issue must be within [1, {MAX_MODEL_CALLS_PER_ISSUE}], "
                f"got {self.model.max_calls_per_issue}"
            )
        if self.branch.namespace in PROTECTED_BRANCHES or not self.branch.namespace:
            errors.append("branch.namespace must be a non-protected branch namespace")
        if self.release.auto_branch in PROTECTED_BRANCHES:
            errors.append("release.auto_branch must never point to main/master")
        if not 0 <= self.patch.strength_l0_l1_min <= 1:
            errors.append("patch.strength_l0_l1_min must be within [0, 1]")
        if not 0 < self.metrics.exclusion_ratio_limit <= 1:
            errors.append("metrics.exclusion_ratio_limit must be within (0, 1]")
        if self.metrics.coverage_delta_tolerance_pp < 0:
            errors.append("metrics.coverage_delta_tolerance_pp must be non-negative")
        if self.metrics.scheduler_tick_seconds < 1:
            errors.append("metrics.scheduler_tick_seconds must be at least 1")
        if self.metrics.recalc_on_close_delay_seconds < 0:
            errors.append("metrics.recalc_on_close_delay_seconds must be non-negative")
        if self.metrics.daily_recalc_seconds < 1:
            errors.append("metrics.daily_recalc_seconds must be at least 1")
        if self.metrics.capture_budget_ms < 1:
            errors.append("metrics.capture_budget_ms must be at least 1")
        if self.metrics.m9_min_continuous_seconds < 86400:
            errors.append("metrics.m9_min_continuous_seconds must be at least 86400")
        if not 1 <= self.metrics.m9_min_sample_gap_seconds <= self.metrics.m9_max_sample_gap_seconds:
            errors.append("metrics.m9_min_sample_gap_seconds must be within [1, m9_max_sample_gap_seconds]")
        if self.metrics.m9_max_sample_gap_seconds > 120:
            errors.append("metrics.m9_max_sample_gap_seconds must not exceed 120")
        if self.metrics.m9_max_sample_age_seconds > 150:
            errors.append("metrics.m9_max_sample_age_seconds must not exceed 150")
        if self.metrics.m9_max_tracker_skew_seconds > 60:
            errors.append("metrics.m9_max_tracker_skew_seconds must not exceed 60")
        if not 1 <= self.eval.isolation_probe_timeout_ms <= 2000:
            errors.append("eval.isolation_probe_timeout_ms must be within [1, 2000]")
        if not 1 <= self.eval.leak_scan_budget_ms <= 5000:
            errors.append("eval.leak_scan_budget_ms must be within [1, 5000]")
        if self.eval.max_violations < 1:
            errors.append("eval.max_violations must be at least 1")
        if not self.eval.set_version:
            errors.append("eval.set_version must not be empty")
        cases_dir = Path(self.eval.cases_dir).resolve()
        expected_dir = Path(self.eval.expected_dir).resolve()
        if cases_dir == expected_dir:
            errors.append("eval.cases_dir and eval.expected_dir must differ")
        elif cases_dir in expected_dir.parents or expected_dir in cases_dir.parents:
            errors.append("eval.cases_dir and eval.expected_dir must not be parent/child directories")
        realscan = self.realscan
        if realscan.runtime_transport not in {"auto", "host", "wsl"}:
            errors.append("realscan.runtime_transport must be one of auto/host/wsl")
        if not 0 <= realscan.listen_port <= 65535 or 0 < realscan.listen_port < 1024:
            errors.append("realscan.listen_port must be 0 or within [1024, 65535]")
        if not 1 <= realscan.port_retries <= 5:
            errors.append("realscan.port_retries must be within [1, 5]")
        if not 1 <= realscan.health_timeout_seconds <= 15:
            errors.append("realscan.health_timeout_seconds must be within [1, 15]")
        if not 1 <= realscan.request_timeout_seconds <= 5:
            errors.append("realscan.request_timeout_seconds must be within [1, 5]")
        if not 1 <= realscan.request_retries <= 5:
            errors.append("realscan.request_retries must be within [1, 5]")
        if realscan.scan_scope not in {"full", "sql-cmd"}:
            errors.append("realscan.scan_scope must be full or sql-cmd")
        if not 1 <= realscan.probe_budget_seconds <= REALSCAN_MAX_PROBE_BUDGET:
            errors.append(f"realscan.probe_budget_seconds must be within [1, {REALSCAN_MAX_PROBE_BUDGET}]")
        if not 0 < realscan.constraint_budget_seconds <= REALSCAN_MAX_CONSTRAINT_BUDGET:
            errors.append(f"realscan.constraint_budget_seconds must be within (0, {REALSCAN_MAX_CONSTRAINT_BUDGET}]")
        if not 0 < realscan.scan_budget_seconds <= REALSCAN_MAX_SCAN_BUDGET:
            errors.append(f"realscan.scan_budget_seconds must be within (0, {REALSCAN_MAX_SCAN_BUDGET}]")
        if not 1 <= realscan.evidence_budget_seconds <= REALSCAN_MAX_EVIDENCE_BUDGET:
            errors.append(f"realscan.evidence_budget_seconds must be within [1, {REALSCAN_MAX_EVIDENCE_BUDGET}]")
        if not realscan.sandbox_images:
            errors.append("realscan.sandbox_images must not be empty")
        if not realscan.target_images:
            errors.append("realscan.target_images must not be empty")
        if not realscan.wsl_distro or not realscan.wsl_user:
            errors.append("realscan.wsl_distro and realscan.wsl_user must not be empty")
        if not realscan.policy_path:
            errors.append("realscan.policy_path must not be empty")
        policy_path = Path(realscan.policy_path)
        if policy_path.is_absolute() and not policy_path.exists():
            errors.append("realscan.policy_path must exist when absolute")
        rc_cases = Path(realscan.cases_dir).resolve()
        rc_expected = Path(realscan.expected_dir).resolve()
        if rc_cases == rc_expected or rc_cases in rc_expected.parents or rc_expected in rc_cases.parents:
            errors.append("realscan.cases_dir and realscan.expected_dir must not be parent/child directories")
        evidence_root = Path(realscan.evidence_root).resolve()
        forbidden_roots = [
            Path(self.eval.expected_dir).resolve(),
            Path(self.metrics.eval_run_dir).resolve(),
            Path("eval/verdicts").resolve(),
        ]
        if any(evidence_root == root or root in evidence_root.parents for root in forbidden_roots):
            errors.append("realscan.evidence_root must not be inside eval/expected, eval/runs or eval/verdicts")
        try:
            home = Path.home().resolve()
        except (RuntimeError, OSError):
            home = None
        if home is not None and (evidence_root == home or home in evidence_root.parents):
            errors.append("realscan.evidence_root must not be inside the user home directory")
        if errors:
            raise ValueError("\n".join(errors))
        return self


def _merge(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = value
    return target


def _env_overrides() -> dict[str, Any]:
    mapping = {
        f"{ENV_PREFIX}PRODUCT_BRAND": ("product", "brand"),
        f"{ENV_PREFIX}BRANCH_NAMESPACE": ("branch", "namespace"),
        f"{ENV_PREFIX}RELEASE_AUTO_BRANCH": ("release", "auto_branch"),
        f"{ENV_PREFIX}RUN_DEADLINE_SECONDS": ("run", "deadline_seconds"),
        f"{ENV_PREFIX}RUN_MAX_CONCURRENCY": ("run", "max_concurrency"),
        f"{ENV_PREFIX}STAGE_TRIAGE_SECONDS": ("stage", "triage_seconds"),
        f"{ENV_PREFIX}STAGE_REPRODUCE_SECONDS": ("stage", "reproduce_seconds"),
        f"{ENV_PREFIX}STAGE_PATCH_SECONDS": ("stage", "patch_seconds"),
        f"{ENV_PREFIX}STAGE_AUDIT_SECONDS": ("stage", "audit_seconds"),
        f"{ENV_PREFIX}STAGE_GATE_READBACK_SECONDS": ("stage", "gate_readback_seconds"),
        f"{ENV_PREFIX}SANDBOX_CPU": ("sandbox", "cpu"),
        f"{ENV_PREFIX}SANDBOX_MEM": ("sandbox", "mem"),
        f"{ENV_PREFIX}SANDBOX_SECONDS": ("sandbox", "seconds"),
        f"{ENV_PREFIX}PATCH_MAX_LINES": ("patch", "max_lines"),
        f"{ENV_PREFIX}PATCH_MAX_FILES": ("patch", "max_files"),
        f"{ENV_PREFIX}PATCH_STRENGTH_L0_L1_MIN": ("patch", "strength_l0_l1_min"),
        f"{ENV_PREFIX}SUSPICION_THRESHOLD": ("suspicion", "threshold"),
        f"{ENV_PREFIX}CIRCUIT_FAIL_STREAK": ("circuit", "fail_streak"),
        f"{ENV_PREFIX}BLACKLIST_TTL_HOURS": ("circuit", "blacklist_ttl_hours"),
        f"{ENV_PREFIX}MODEL_PROVIDER": ("model", "provider"),
        f"{ENV_PREFIX}MODEL_MAX_CALLS_PER_ISSUE": ("model", "max_calls_per_issue"),
        f"{ENV_PREFIX}MODEL_CALL_TIMEOUT_SECONDS": ("model", "call_timeout_seconds"),
        f"{ENV_PREFIX}CHECK_RULESET": ("codearts", "ruleset"),
        f"{ENV_PREFIX}GATE_PIPELINE_ID": ("codearts", "pipeline_id"),
    }
    numeric = {
        "deadline_seconds",
        "max_concurrency",
        "triage_seconds",
        "reproduce_seconds",
        "patch_seconds",
        "audit_seconds",
        "gate_readback_seconds",
        "seconds",
        "max_lines",
        "max_files",
        "threshold",
        "strength_l0_l1_min",
        "fail_streak",
        "blacklist_ttl_hours",
        "max_calls_per_issue",
        "call_timeout_seconds",
    }
    floats = {"cpu", "threshold", "strength_l0_l1_min"}
    result: dict[str, Any] = {}
    for env_key, path in mapping.items():
        raw = os.environ.get(env_key)
        if raw is None:
            continue
        value: Any = raw
        if path[-1] in floats:
            value = float(raw)
        elif path[-1] in numeric:
            value = int(raw)
        node = result
        for part in path[:-1]:
            node = node.setdefault(part, {})
        node[path[-1]] = value
    return result


def _frozen_violations(config: AppConfig, defaults: AppConfig) -> list[str]:
    checks = [
        ("branch.namespace", config.branch.namespace, FROZEN_BRANCH_NAMESPACE),
        ("release.auto_branch", config.release.auto_branch, FROZEN_RELEASE_AUTO_BRANCH),
        ("patch.max_lines", config.patch.max_lines, FROZEN_PATCH_MAX_LINES),
        ("patch.max_files", config.patch.max_files, FROZEN_PATCH_MAX_FILES),
        ("patch.strength_l0_l1_min", config.patch.strength_l0_l1_min, FROZEN_PATCH_STRENGTH_MIN),
    ]
    del defaults
    return [f"frozen configuration key {name} must remain {expected!r}, got {actual!r}" for name, actual, expected in checks if actual != expected]


def load_config(path: str | Path | None = None, allow_frozen_overrides: bool = False) -> AppConfig:
    data: dict[str, Any] = {}
    candidate = Path(path) if path is not None else Path(os.environ.get(f"{ENV_PREFIX}CONFIG", DEFAULT_CONFIG_FILE))
    if candidate.exists():
        loaded = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ConfigValidationError([f"configuration file {candidate} must contain a mapping"])
        _merge(data, loaded)
    _merge(data, _env_overrides())

    try:
        config = AppConfig(**data)
    except ValidationError as exc:
        details = []
        for item in exc.errors():
            loc = ".".join(str(part) for part in item["loc"])
            details.append(f"{loc}: {item['msg']}")
        raise ConfigValidationError(details) from exc
    except ValueError as exc:
        raise ConfigValidationError([line for line in str(exc).splitlines() if line]) from exc

    violations = _frozen_violations(config, AppConfig())
    if violations and not allow_frozen_overrides:
        raise ConfigValidationError(violations)
    if violations:
        config = config.model_copy(update={"frozen_overrides": tuple(v.split()[2] for v in violations)})
    return config