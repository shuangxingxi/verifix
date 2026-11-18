"""子进程探针：全项目唯一的子进程出口。

统一负责环境净化、超时终止（含进程树）、输出截断与脱敏、越界 cwd 拒绝。
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, Sequence, runtime_checkable

from app.api.envelope import ApiError, ErrorCode

from .context import mask
from .models import ProbeOutput


class EnvMode(str, Enum):
    INHERIT = "INHERIT"
    CLEAN = "CLEAN"


_CLEAN_ENV_KEYS = frozenset(
    {
        "PATH",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "HOME",
        "USERPROFILE",
        "TEMP",
        "TMP",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "TZ",
    }
)


@runtime_checkable
class Probe(Protocol):
    def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float,
        cwd: str | Path | None = None,
        env_mode: EnvMode = EnvMode.INHERIT,
        summary_limit: int = 2000,
    ) -> ProbeOutput: ...


class SubprocessProbe:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    def run(
        self,
        argv: Sequence[str],
        *,
        timeout: float,
        cwd: str | Path | None = None,
        env_mode: EnvMode = EnvMode.INHERIT,
        summary_limit: int = 2000,
    ) -> ProbeOutput:
        command = [str(item) for item in argv]
        workdir = Path(cwd) if cwd is not None else Path(self.ctx.root)
        if not workdir.is_absolute():
            workdir = Path(self.ctx.root) / workdir
        if not self.ctx.is_within(workdir):
            raise ApiError(
                ErrorCode.SELFCHECK_READONLY_VIOLATION,
                f"probe cwd outside allowed roots: {workdir}",
            )
        env = _build_env(env_mode)
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                command,
                cwd=str(workdir),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError:
            return ProbeOutput(
                exit_code=None,
                stderr_tail=f"command not found: {command[0]}",
                duration_seconds=time.monotonic() - started,
                unavailable=True,
            )
        except OSError as exc:
            return ProbeOutput(
                exit_code=None,
                stderr_tail=f"{type(exc).__name__}: {exc}",
                duration_seconds=time.monotonic() - started,
                unavailable=True,
            )
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_tree(process)
            try:
                stdout, stderr = process.communicate(timeout=30)
            except subprocess.TimeoutExpired:
                stdout, stderr = "", ""
        duration = time.monotonic() - started
        return ProbeOutput(
            exit_code=process.returncode,
            stdout_tail=_tail(stdout or "", summary_limit),
            stderr_tail=_tail(stderr or "", 1000),
            duration_seconds=duration,
            timed_out=timed_out,
            unavailable=False,
        )


def _build_env(mode: EnvMode) -> dict[str, str] | None:
    if mode is EnvMode.INHERIT:
        return None
    return {
        key: value
        for key, value in os.environ.items()
        if key.upper() in _CLEAN_ENV_KEYS
    }


def _tail(text: str, limit: int) -> str:
    cleaned = mask(text)
    if len(cleaned) <= limit:
        return cleaned
    dropped = len(cleaned) - limit
    return f"...[truncated {dropped} chars]\n" + cleaned[-limit:]


def _terminate_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass