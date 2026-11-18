from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from app.runtime.exec_domain import ExecDomain, detect_exec_domain

TIMEOUT_EXIT_CODE = 124


class RuntimeUnavailableError(RuntimeError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"runtime unavailable: {reason}")


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


class RuntimeTransport(Protocol):
    name: str
    exec_domain: ExecDomain
    privilege_route: str

    def run(
        self,
        argv: Sequence[str],
        timeout_seconds: float,
        cwd: Path | None = None,
        stdin_text: str | None = None,
    ) -> CommandResult: ...


def _execute(
    full_argv: list[str],
    timeout_seconds: float,
    cwd: Path | None,
    env: dict[str, str] | None = None,
    stdin_text: str | None = None,
) -> CommandResult:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            full_argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            cwd=str(cwd) if cwd is not None else None,
            input=stdin_text,
            stdin=subprocess.DEVNULL if stdin_text is None else None,
            env=env,
            check=False,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        return CommandResult(
            argv=tuple(full_argv),
            exit_code=int(completed.returncode),
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            duration_ms=duration_ms,
            timed_out=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        return CommandResult(
            argv=tuple(full_argv),
            exit_code=TIMEOUT_EXIT_CODE,
            stdout=str(stdout),
            stderr=str(stderr),
            duration_ms=duration_ms,
            timed_out=True,
        )
    except (FileNotFoundError, PermissionError) as exc:
        raise RuntimeUnavailableError(type(exc).__name__) from exc


@dataclass
class HostDockerTransport:
    name: str = "host"
    exec_domain: ExecDomain = ExecDomain.HOST_USER
    privilege_route: str = "NONE"

    def run(
        self,
        argv: Sequence[str],
        timeout_seconds: float,
        cwd: Path | None = None,
        stdin_text: str | None = None,
    ) -> CommandResult:
        command = list(argv)
        if not command:
            raise ValueError("argv must not be empty")
        if command[0] != "docker":
            command = ["docker", *command]
        return _execute(command, timeout_seconds, cwd, stdin_text=stdin_text)


@dataclass
class WslDockerTransport:
    distro: str = "Debian"
    user: str = "root"
    name: str = "wsl"

    def __post_init__(self) -> None:
        if not self.distro or not self.user:
            raise ValueError("wsl distro and user must not be empty")
        self.exec_domain = detect_exec_domain("wsl") if self.user == "root" else ExecDomain.HOST_USER
        self.privilege_route = "WSL_DISTRO_ROOT" if self.user == "root" else "NONE"

    def run(
        self,
        argv: Sequence[str],
        timeout_seconds: float,
        cwd: Path | None = None,
        stdin_text: str | None = None,
    ) -> CommandResult:
        command = list(argv)
        if not command:
            raise ValueError("argv must not be empty")
        prefix = ["wsl.exe", "-d", self.distro, "-u", self.user, "--", "docker"]
        if command[0] != "docker":
            command = prefix + command
        else:
            command = prefix + command[1:]
        env = dict(os.environ)
        env["WSL_UTF8"] = "1"
        translated = None
        if cwd is not None:
            translated = wsl_path(Path(cwd))
        return (
            _execute(command, timeout_seconds, None, env=env, stdin_text=stdin_text)
            if translated is None
            else _execute_on_wsl_dir(command, timeout_seconds, translated, env, stdin_text)
        )


def _execute_on_wsl_dir(
    command: list[str],
    timeout_seconds: float,
    wsl_cwd: str,
    env: dict[str, str],
    stdin_text: str | None = None,
) -> CommandResult:
    wrapped = command[:6] + ["sh", "-lc", f"cd '{wsl_cwd}' && " + " ".join(_quote(part) for part in command[6:])] if len(command) > 6 else command
    return _execute(wrapped, timeout_seconds, None, env=env, stdin_text=stdin_text)


def _quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def wsl_path(path: Path) -> str:
    raw = str(path.resolve())
    match = None
    if len(raw) >= 2 and raw[1] == ":":
        match = raw
    if match is None:
        return raw.replace("\\", "/")
    drive = match[0].lower()
    rest = match[2:].replace("\\", "/").lstrip("/")
    return f"/mnt/{drive}/{rest}"


@dataclass
class UnavailableTransport:
    reason: str = "docker_cli"
    name: str = "unavailable"
    exec_domain: ExecDomain = ExecDomain.HOST_USER
    privilege_route: str = "NONE"

    def run(
        self,
        argv: Sequence[str],
        timeout_seconds: float,
        cwd: Path | None = None,
        stdin_text: str | None = None,
    ) -> CommandResult:
        raise RuntimeUnavailableError(self.reason)


def select_transport(config: object) -> RuntimeTransport:
    mode = str(getattr(config, "runtime_transport", "auto")).lower()
    distro = str(getattr(config, "wsl_distro", "Debian"))
    user = str(getattr(config, "wsl_user", "root"))
    if mode == "host":
        return HostDockerTransport() if shutil.which("docker") else UnavailableTransport("host_docker_cli")
    if mode == "wsl":
        return WslDockerTransport(distro=distro, user=user) if _wsl_available() else UnavailableTransport("wsl_cli")
    if shutil.which("docker"):
        return HostDockerTransport()
    if _wsl_available():
        return WslDockerTransport(distro=distro, user=user)
    return UnavailableTransport("docker_cli")


def _wsl_available() -> bool:
    return bool(shutil.which("wsl.exe") or shutil.which("wsl"))