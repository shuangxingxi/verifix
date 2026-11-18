from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app.realscan.boundary import default_adoptions
from app.realscan.models import (
    ConstraintCheck,
    ConstraintVerificationRecord,
    EnvironmentCapability,
    ImageResolution,
    Judgement,
)
from app.realscan.policy import JUDGEMENT_CLASSES, PolicyFile, RunSpecBuilder, sanitize_name
from app.realscan.probe_scripts import (
    EGRESS_PROBE,
    FILESYSTEM_PROBE,
    IDENTITY_PROBE,
    LOOPBACK_PROBE,
    P4_01_PROBE,
    P4_05_PROBE,
)
from app.realscan.runtime import RuntimeTransport

P4_05_MIN_MS = 55_000
P4_05_MAX_MS = 75_000
EXPECTED_MEMORY_BYTES = 1024 * 1024 * 1024
EXPECTED_NANO_CPUS = 1_000_000_000
EXPECTED_PIDS_LIMIT = 128
EXPECTED_UID = 10001
EXPECTED_GID = 10001
NETWORK_ERROR_TYPES = frozenset({"OSError", "TimeoutError", "Timeout", "ConnectionError", "ConnectionRefusedError"})
DEFAULT_RETEST_HINT = "补齐容器运行时后重跑 python scripts/run_sandbox_verify.py --p4-05 on"


@dataclass
class ProbeOutcome:
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    timed_out: bool = False
    duration_ms: int = 0
    payload: dict | None = None

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def parse_payload(stdout: str) -> dict | None:
    for line in reversed(stdout.splitlines()):
        text = line.strip()
        if text.startswith("{") and text.endswith("}"):
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    return None


def aggregate_judgement(checks: list[ConstraintCheck]) -> Judgement:
    if any(check.judgement is Judgement.FAIL for check in checks):
        return Judgement.FAIL
    if any(check.judgement is Judgement.UNVERIFIED for check in checks):
        return Judgement.UNVERIFIED
    return Judgement.PASS


class ConstraintVerifier:
    def __init__(
        self,
        policy: PolicyFile,
        capability: EnvironmentCapability,
        transport: RuntimeTransport,
        image: ImageResolution,
        view_dir: Path,
        evidence_dir: Path | None = None,
        path_mapper: Callable[[Path], str] | None = None,
        probe_timeout_seconds: float = 10.0,
        p4_05_seconds: float = 60.0,
        sleeper: Callable[[float], None] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.policy = policy
        self.capability = capability
        self.transport = transport
        self.image = image
        self.view_dir = Path(view_dir)
        self.evidence_dir = Path(evidence_dir) if evidence_dir is not None else None
        self.path_mapper = path_mapper
        self.probe_timeout_seconds = probe_timeout_seconds
        self.p4_05_seconds = p4_05_seconds
        self.sleeper = sleeper or time.sleep
        self.clock = clock or time.perf_counter

    def verify(self, verification_id: str, run_p4_05: bool = True) -> ConstraintVerificationRecord:
        if self.capability.blocking_missing():
            checks = self._blocked_checks("capability_unavailable")
            return self._record(verification_id, checks)

        inspect_payload = self._inspect_snapshot(verification_id)
        identity = self._probe(IDENTITY_PROBE, f"vf-verify-id-{verification_id}")
        egress = self._probe(EGRESS_PROBE, f"vf-verify-egress-{verification_id}")
        loopback = self._probe(LOOPBACK_PROBE, f"vf-verify-loop-{verification_id}")
        filesystem = self._probe(FILESYSTEM_PROBE, f"vf-verify-fs-{verification_id}")
        p4_01 = self._probe(P4_01_PROBE, f"vf-verify-p401-{verification_id}")
        p4_05 = self._p4_05(verification_id, run_p4_05)

        checks: list[ConstraintCheck] = []
        checks.append(self._class_check("network", egress, self._judge_network(egress, inspect_payload)))
        checks.append(self._class_check("source_mount", filesystem, self._judge_source_mount(filesystem)))
        checks.append(
            self._class_check("filesystem_writable_surface", filesystem, self._judge_filesystem(filesystem))
        )
        checks.append(self._rekey_timeout(p4_05, verification_id))
        checks.append(self._class_check("memory_limit", None, self._judge_memory(inspect_payload)))
        checks.append(self._class_check("cpu_limit", None, self._judge_cpu(inspect_payload)))
        checks.append(self._class_check("exec_user", identity, self._judge_user(identity)))
        checks.append(self._class_check("capability_set", identity, self._judge_caps(identity, inspect_payload)))
        checks.append(self._class_check("no_new_privileges", identity, self._judge_nnp(identity, inspect_payload)))
        checks.append(self._class_check("pids_limit", None, self._judge_pids(inspect_payload)))
        checks.append(self._extra_check("loopback_available", loopback, self._judge_loopback(loopback)))
        checks.append(self._escape_check("P4-01", p4_01, self._judge_p4_01(p4_01)))
        checks.append(self._escape_check("P4-02", filesystem, self._judge_p4_02(filesystem)))
        checks.append(self._escape_check("P4-03", egress, self._judge_network(egress, inspect_payload)))
        checks.append(self._escape_check("P4-04", identity, self._judge_p4_04(identity)))
        checks.append(p4_05)
        return self._record(verification_id, checks)

    def _record(self, verification_id: str, checks: list[ConstraintCheck]) -> ConstraintVerificationRecord:
        return ConstraintVerificationRecord(
            verification_id=verification_id,
            executed_at=datetime.now(timezone.utc),
            exec_domain=self.transport.exec_domain,
            policy_version=self.policy.policy_version,
            policy_sha256=self.policy.sha256,
            image=self.image,
            privilege_route=self.transport.privilege_route,
            capability=self.capability,
            checks=checks,
            verdict=aggregate_judgement(checks),
            evidence_ref=f"{verification_id}/manifest.json",
            adopted_defaults=default_adoptions(),
        )

    def _probe(self, script: str, name: str) -> ProbeOutcome:
        spec = RunSpecBuilder(self.policy, sanitize_name(name), self.path_mapper).build_run(self.view_dir, script)
        result = self.transport.run(spec.argv, self.probe_timeout_seconds)
        return ProbeOutcome(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            timed_out=result.timed_out,
            duration_ms=result.duration_ms,
            payload=parse_payload(result.stdout),
        )

    def _inspect_snapshot(self, verification_id: str) -> dict | None:
        name = sanitize_name(f"vf-verify-{verification_id}")
        spec = RunSpecBuilder(self.policy, name, self.path_mapper).build(self.view_dir, stdin_mode=False)
        created = self.transport.run(spec.argv, 30.0)
        try:
            if not created.ok:
                return None
            inspected = self.transport.run(
                ["docker", "inspect", "--format", "{{json .HostConfig}}", name],
                10.0,
            )
            return parse_payload(inspected.stdout)
        finally:
            self.transport.run(["docker", "rm", "-f", name], 30.0)

    def _p4_05(self, verification_id: str, run_p4_05: bool) -> ConstraintCheck:
        check_id = f"P4-05-{verification_id}"
        if not run_p4_05:
            return ConstraintCheck(
                check_id=check_id,
                policy_key="escape_case:P4-05",
                expected="killed_at_60s",
                observed="not_executed",
                judgement=Judgement.UNVERIFIED,
                evidence_ref=f"{verification_id}/raw/p4-05.log",
                basis="p4-05 disabled by configuration",
                missing_reason="not_executed",
                retest_hint=DEFAULT_RETEST_HINT,
            )
        name = sanitize_name(f"vf-loop-{verification_id}")
        spec = RunSpecBuilder(self.policy, name, self.path_mapper).build_run(self.view_dir, P4_05_PROBE)
        argv = [item for item in spec.argv if item != "--rm"]
        argv.insert(2, "-d")
        started = self.clock()
        launched = self.transport.run(argv, 30.0)
        terminated_ms = 0
        try:
            if not launched.ok:
                return ConstraintCheck(
                    check_id=check_id,
                    policy_key="escape_case:P4-05",
                    expected="killed_at_60s",
                    observed="launch_failed",
                    judgement=Judgement.UNVERIFIED,
                    evidence_ref=f"{verification_id}/raw/p4-05.log",
                    basis="container launch failed",
                    missing_reason="not_executed",
                    retest_hint=DEFAULT_RETEST_HINT,
                )
            elapsed = 0.0
            while elapsed < self.p4_05_seconds:
                self.sleeper(min(1.0, self.p4_05_seconds - elapsed))
                elapsed = self.clock() - started
            running = self.transport.run(
                ["docker", "inspect", "--format", "{{.State.Running}}", name],
                10.0,
            )
            if running.ok and running.stdout.strip().lower() == "true":
                self.transport.run(["docker", "kill", name], 10.0)
            terminated_ms = int((self.clock() - started) * 1000)
        finally:
            self.transport.run(["docker", "rm", "-f", name], 30.0)
        remains = self.transport.run(
            ["docker", "ps", "-a", "--filter", f"name=^{name}$", "--format", "{{.Names}}"],
            10.0,
        )
        leaked = name in (remains.stdout or "")
        observed = f"terminated_ms={terminated_ms},leaked={leaked}"
        if leaked:
            judgement = Judgement.FAIL
        elif terminated_ms < P4_05_MIN_MS:
            judgement = Judgement.UNVERIFIED
        elif terminated_ms > P4_05_MAX_MS:
            judgement = Judgement.FAIL
        else:
            judgement = Judgement.PASS
        return ConstraintCheck(
            check_id=check_id,
            policy_key="escape_case:P4-05",
            expected="killed_at_60s",
            observed=observed,
            judgement=judgement,
            duration_ms=terminated_ms,
            evidence_ref=f"{verification_id}/raw/p4-05.log",
            basis="synthetic infinite loop terminated by host budget with docker kill",
            missing_reason="terminated_early" if judgement is Judgement.UNVERIFIED else "",
            retest_hint=DEFAULT_RETEST_HINT if judgement is Judgement.UNVERIFIED else "",
        )

    def _blocked_checks(self, reason: str) -> list[ConstraintCheck]:
        checks = [
            ConstraintCheck(
                check_id=f"blocked-{name}",
                policy_key=name,
                expected="unknown",
                observed="capability_unavailable",
                judgement=Judgement.UNVERIFIED,
                missing_reason=reason,
                retest_hint=DEFAULT_RETEST_HINT,
                basis="blocking capability missing",
            )
            for name in JUDGEMENT_CLASSES
        ]
        for case_id in ("P4-01", "P4-02", "P4-03", "P4-04", "P4-05"):
            checks.append(
                ConstraintCheck(
                    check_id=f"blocked-{case_id}",
                    policy_key=f"escape_case:{case_id}",
                    expected="denied" if case_id != "P4-05" else "killed_at_60s",
                    observed="capability_unavailable",
                    judgement=Judgement.UNVERIFIED,
                    missing_reason=reason,
                    retest_hint=DEFAULT_RETEST_HINT,
                    basis="blocking capability missing",
                )
            )
        return checks

    def _rekey_timeout(self, check: ConstraintCheck, verification_id: str) -> ConstraintCheck:
        return check.model_copy(
            update={
                "check_id": f"timeout_termination-{verification_id}",
                "policy_key": "timeout_termination",
            }
        )

    def _class_check(self, policy_key: str, outcome: ProbeOutcome | None, judgement: Judgement) -> ConstraintCheck:
        return self._make_check(
            check_id=f"{policy_key}-{id(outcome) & 0xFFFF:x}" if outcome is not None else f"{policy_key}-inspect",
            policy_key=policy_key,
            outcome=outcome,
            judgement=judgement,
        )

    def _extra_check(self, policy_key: str, outcome: ProbeOutcome, judgement: Judgement) -> ConstraintCheck:
        return self._make_check(check_id=f"{policy_key}-probe", policy_key=policy_key, outcome=outcome, judgement=judgement)

    def _escape_check(self, case_id: str, outcome: ProbeOutcome, judgement: Judgement) -> ConstraintCheck:
        return self._make_check(
            check_id=f"{case_id}-probe",
            policy_key=f"escape_case:{case_id}",
            outcome=outcome,
            judgement=judgement,
        )

    def _make_check(self, check_id: str, policy_key: str, outcome: ProbeOutcome | None, judgement: Judgement) -> ConstraintCheck:
        expected = str(self.policy.isolation.get(policy_key, "policy"))
        observed = ""
        basis = ""
        duration = 0
        if outcome is not None:
            duration = outcome.duration_ms
            observed = (outcome.stdout or "").strip().splitlines()[-1] if (outcome.stdout or "").strip() else ""
            basis = f"exit={outcome.exit_code},timed_out={outcome.timed_out}"
        unverified = judgement is Judgement.UNVERIFIED
        reason = ""
        hint = ""
        if unverified:
            if outcome is not None and outcome.timed_out:
                reason = "probe_timeout"
            elif outcome is not None and not outcome.ok and outcome.payload is None:
                reason = "probe_timeout"
            else:
                reason = "not_executed"
            hint = DEFAULT_RETEST_HINT
        return ConstraintCheck(
            check_id=check_id,
            policy_key=policy_key,
            expected=expected,
            observed=observed,
            judgement=judgement,
            duration_ms=duration,
            evidence_ref=f"raw/{policy_key.replace(':', '-')}.json",
            basis=basis,
            missing_reason=reason,
            retest_hint=hint,
        )

    def _judge_network(self, outcome: ProbeOutcome, inspect_payload: dict | None) -> Judgement:
        if outcome.payload is None:
            return Judgement.UNVERIFIED
        ok = outcome.payload.get("ok")
        error_type = str(outcome.payload.get("error_type", ""))
        host_mode = "none"
        if inspect_payload is not None:
            host_mode = str(inspect_payload.get("NetworkMode", "none"))
        if ok is True:
            return Judgement.FAIL
        if ok is False and error_type in NETWORK_ERROR_TYPES and host_mode == "none":
            return Judgement.PASS
        if ok is False and error_type in NETWORK_ERROR_TYPES:
            return Judgement.FAIL
        return Judgement.UNVERIFIED

    def _judge_loopback(self, outcome: ProbeOutcome) -> Judgement:
        if outcome.payload is None:
            return Judgement.UNVERIFIED
        flags = [outcome.payload.get("bind"), outcome.payload.get("listen"), outcome.payload.get("connect")]
        return Judgement.PASS if all(flag is True for flag in flags) else Judgement.FAIL

    def _judge_source_mount(self, outcome: ProbeOutcome) -> Judgement:
        if outcome.payload is None:
            return Judgement.UNVERIFIED
        if outcome.payload.get("src_write") is True:
            return Judgement.FAIL
        return Judgement.PASS if outcome.payload.get("src_read") is True else Judgement.FAIL

    def _judge_filesystem(self, outcome: ProbeOutcome) -> Judgement:
        if outcome.payload is None:
            return Judgement.UNVERIFIED
        root_write = outcome.payload.get("root_write")
        tmp = outcome.payload.get("tmp_writable")
        workspace = outcome.payload.get("workspace_writable")
        if root_write is True:
            return Judgement.FAIL
        return Judgement.PASS if tmp is True and workspace is True else Judgement.FAIL

    def _judge_memory(self, inspect_payload: dict | None) -> Judgement:
        if inspect_payload is None:
            return Judgement.UNVERIFIED
        return Judgement.PASS if int(inspect_payload.get("Memory", 0)) == EXPECTED_MEMORY_BYTES else Judgement.FAIL

    def _judge_cpu(self, inspect_payload: dict | None) -> Judgement:
        if inspect_payload is None:
            return Judgement.UNVERIFIED
        return Judgement.PASS if int(inspect_payload.get("NanoCpus", 0)) == EXPECTED_NANO_CPUS else Judgement.FAIL

    def _judge_pids(self, inspect_payload: dict | None) -> Judgement:
        if inspect_payload is None:
            return Judgement.UNVERIFIED
        return Judgement.PASS if int(inspect_payload.get("PidsLimit", 0)) == EXPECTED_PIDS_LIMIT else Judgement.FAIL

    def _judge_user(self, outcome: ProbeOutcome) -> Judgement:
        if outcome.payload is None:
            return Judgement.UNVERIFIED
        uid = outcome.payload.get("uid")
        gid = outcome.payload.get("gid")
        return Judgement.PASS if uid == EXPECTED_UID and gid == EXPECTED_GID else Judgement.FAIL

    def _judge_caps(self, outcome: ProbeOutcome, inspect_payload: dict | None) -> Judgement:
        if outcome.payload is None:
            return Judgement.UNVERIFIED
        cap_eff = str(outcome.payload.get("cap_eff", "")).lower()
        drop = []
        if inspect_payload is not None:
            drop = [str(item).upper() for item in inspect_payload.get("CapDrop") or []]
        if cap_eff not in {"0", "0000000000000000"}:
            return Judgement.FAIL
        if inspect_payload is not None and "ALL" not in drop:
            return Judgement.FAIL
        return Judgement.PASS

    def _judge_nnp(self, outcome: ProbeOutcome, inspect_payload: dict | None) -> Judgement:
        if outcome.payload is None:
            return Judgement.UNVERIFIED
        nnp = str(outcome.payload.get("no_new_privs", ""))
        setuid_blocked = outcome.payload.get("setuid_blocked") is True
        security_opts = []
        if inspect_payload is not None:
            security_opts = [str(item) for item in inspect_payload.get("SecurityOpt") or []]
        if nnp != "1" or not setuid_blocked:
            return Judgement.FAIL
        if inspect_payload is not None and not any("no-new-privileges" in item for item in security_opts):
            return Judgement.FAIL
        return Judgement.PASS

    def _judge_p4_01(self, outcome: ProbeOutcome) -> Judgement:
        if outcome.payload is None:
            return Judgement.UNVERIFIED
        if outcome.payload.get("git_config_readable") is True or outcome.payload.get("dot_git_visible") is True:
            return Judgement.FAIL
        return Judgement.PASS if outcome.payload.get("positive_control") is True else Judgement.UNVERIFIED

    def _judge_p4_02(self, outcome: ProbeOutcome) -> Judgement:
        if outcome.payload is None:
            return Judgement.UNVERIFIED
        return Judgement.PASS if outcome.payload.get("src_write") is False else Judgement.FAIL

    def _judge_p4_04(self, outcome: ProbeOutcome) -> Judgement:
        if outcome.payload is None:
            return Judgement.UNVERIFIED
        cap_eff = str(outcome.payload.get("cap_eff", "")).lower()
        if outcome.payload.get("setuid_blocked") is not True:
            return Judgement.FAIL
        return Judgement.PASS if cap_eff in {"0", "0000000000000000"} else Judgement.FAIL