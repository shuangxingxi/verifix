from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from app.config import MAX_SANDBOX_MEMORY_MB, MAX_SANDBOX_SECONDS, AppConfig, SandboxConfig


class SandboxInfraError(Exception):
    pass


@dataclass(frozen=True)
class SandboxPolicy:
    cpu: float = 1.0
    memory_mb: int = 1024
    timeout_seconds: int = 60
    uid: int = 10001
    gid: int = 10001
    pids_limit: int = 128
    image: str = "verifix-sandbox:1.0.0"
    docker_bin: str = "docker"

    @classmethod
    def from_config(cls, config: AppConfig) -> "SandboxPolicy":
        sandbox: SandboxConfig = config.sandbox
        return cls(cpu=sandbox.cpu, memory_mb=sandbox.memory_mb(), timeout_seconds=sandbox.seconds)

    def digest(self) -> str:
        payload = json.dumps(
            {
                "cpu": self.cpu,
                "memory_mb": self.memory_mb,
                "timeout_seconds": self.timeout_seconds,
                "uid": self.uid,
                "gid": self.gid,
                "pids_limit": self.pids_limit,
                "image": self.image,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IsolationReport:
    checks: dict[str, bool]

    @property
    def satisfied(self) -> bool:
        return all(self.checks.values())

    def failures(self) -> list[str]:
        return [name for name, ok in self.checks.items() if not ok]


@dataclass(frozen=True)
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool
    policy_digest: str
    argv: tuple[str, ...] = field(default_factory=tuple)


class SandboxRunner:
    def __init__(self, policy: SandboxPolicy):
        self.policy = policy

    def build_argv(self, source_dir: Path, test_path: str) -> list[str]:
        source = Path(source_dir).resolve()
        argv: list[str] = [
            self.policy.docker_bin,
            "run",
            "--rm",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            f"--user={self.policy.uid}:{self.policy.gid}",
            f"--memory={self.policy.memory_mb}m",
            f"--memory-swap={self.policy.memory_mb}m",
            f"--cpus={self.policy.cpu}",
            f"--pids-limit={self.policy.pids_limit}",
            "--tmpfs=/tmp:rw,noexec,nosuid,size=64m",
            "--tmpfs=/workspace:rw,noexec,nosuid,size=256m",
            f"--volume={source}:/src:ro",
            "--workdir=/workspace",
            self.policy.image,
            "python",
            "-m",
            "unittest",
            "-v",
            test_path,
        ]
        return argv

    def isolation_report(self, argv: Sequence[str] | None = None) -> IsolationReport:
        rendered = " ".join(argv or self.build_argv(Path("."), "tests"))
        checks = {
            "network_disabled": "--network=none" in rendered,
            "source_read_only": ":/src:ro" in rendered,
            "timeout_within_60s": 0 < self.policy.timeout_seconds <= MAX_SANDBOX_SECONDS,
            "memory_within_1g": 0 < self.policy.memory_mb <= MAX_SANDBOX_MEMORY_MB,
            "non_root": f"--user={self.policy.uid}:{self.policy.gid}" in rendered,
            "cap_drop_all": "--cap-drop=ALL" in rendered,
        }
        return IsolationReport(checks=checks)

    def preflight(self) -> IsolationReport:
        report = self.isolation_report()
        if not report.satisfied:
            raise SandboxInfraError(f"isolation policy violated: {', '.join(report.failures())}")
        binary = shutil.which(self.policy.docker_bin)
        if binary is None:
            raise SandboxInfraError(f"sandbox backend unavailable: {self.policy.docker_bin} not found")
        return report

    def run_tests(self, source_dir: Path, test_path: str) -> SandboxResult:
        argv = self.build_argv(source_dir, test_path)
        report = self.isolation_report(argv)
        if not report.satisfied:
            raise SandboxInfraError(f"isolation policy violated: {', '.join(report.failures())}")
        if shutil.which(self.policy.docker_bin) is None:
            raise SandboxInfraError(f"sandbox backend unavailable: {self.policy.docker_bin} not found")
        started = time.monotonic()
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.policy.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", "replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", "replace")
            return SandboxResult(
                exit_code=124,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
                timed_out=True,
                policy_digest=self.policy.digest(),
                argv=tuple(argv),
            )
        duration_ms = int((time.monotonic() - started) * 1000)
        return SandboxResult(
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_ms=duration_ms,
            timed_out=False,
            policy_digest=self.policy.digest(),
            argv=tuple(argv),
        )