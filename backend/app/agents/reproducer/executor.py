from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.domain.models import EnvSnapshot
from app.tools.sandbox import SandboxInfraError, SandboxRunner


@dataclass(frozen=True)
class TestExecution:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool
    backend: str
    env_snapshot: EnvSnapshot
    infra_error: str | None = None

    @property
    def assertion_failed(self) -> bool:
        combined = f"{self.stdout}\n{self.stderr}"
        return ("AssertionError" in combined) or ("FAILED (failures" in combined) or ("FAILED (errors" in combined)


class TestExecutorPort(Protocol):
    def run_tests(self, workspace: Path, test_path: str) -> TestExecution: ...


class LocalTestExecutor:
    def __init__(self, timeout_seconds: int = 60, python: str | None = None):
        self.timeout_seconds = min(max(1, timeout_seconds), 60)
        self.python = python or sys.executable

    def env_snapshot(self) -> EnvSnapshot:
        return EnvSnapshot(
            network_disabled=False,
            read_only=False,
            timeout_seconds=self.timeout_seconds,
            memory_mb=1024,
            uid=10001,
        )

    def run_tests(self, workspace: Path, test_path: str) -> TestExecution:
        started = time.monotonic()
        try:
            completed = subprocess.run(
                [self.python, test_path],
                cwd=str(workspace),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
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
            return TestExecution(
                exit_code=124,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
                timed_out=True,
                backend="local-dev",
                env_snapshot=self.env_snapshot(),
            )
        duration_ms = int((time.monotonic() - started) * 1000)
        return TestExecution(
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_ms=duration_ms,
            timed_out=False,
            backend="local-dev",
            env_snapshot=self.env_snapshot(),
        )


class SandboxTestExecutor:
    def __init__(self, runner: SandboxRunner):
        self.runner = runner

    def env_snapshot(self) -> EnvSnapshot:
        policy = self.runner.policy
        return EnvSnapshot(
            network_disabled=True,
            read_only=True,
            timeout_seconds=min(max(1, policy.timeout_seconds), 60),
            memory_mb=min(max(1, policy.memory_mb), 1024),
            uid=policy.uid,
        )

    def run_tests(self, workspace: Path, test_path: str) -> TestExecution:
        try:
            result = self.runner.run_tests(workspace, test_path)
        except SandboxInfraError as exc:
            return TestExecution(
                exit_code=-1,
                stdout="",
                stderr=str(exc),
                duration_ms=0,
                timed_out=False,
                backend="sandbox",
                env_snapshot=self.env_snapshot(),
                infra_error=str(exc),
            )
        return TestExecution(
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=result.duration_ms,
            timed_out=result.timed_out,
            backend="sandbox",
            env_snapshot=self.env_snapshot(),
            infra_error="sandbox timeout" if result.timed_out else None,
        )