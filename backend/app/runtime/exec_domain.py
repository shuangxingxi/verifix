from __future__ import annotations

import os
from enum import Enum
from pathlib import Path

DOCKERENV_PATH = Path("/.dockerenv")


class ExecDomain(str, Enum):
    HOST_USER = "HOST_USER"
    RUNTIME_ROOT = "RUNTIME_ROOT"
    CONTAINER_EXEC = "CONTAINER_EXEC"


class FailureKind(str, Enum):
    ISOLATION_DEFECT = "ISOLATION_DEFECT"
    EXEC_DOMAIN_MISMATCH = "EXEC_DOMAIN_MISMATCH"
    PROBE_INVALID = "PROBE_INVALID"
    RUNTIME_UNAVAILABLE = "RUNTIME_UNAVAILABLE"


def _euid() -> int | None:
    getter = getattr(os, "geteuid", None)
    if getter is None:
        return None
    try:
        return int(getter())
    except OSError:
        return None


def in_container() -> bool:
    try:
        return DOCKERENV_PATH.exists()
    except OSError:
        return False


def detect_exec_domain(transport_name: str = "") -> ExecDomain:
    if in_container():
        if _euid() == 0:
            return ExecDomain.RUNTIME_ROOT
        return ExecDomain.CONTAINER_EXEC
    if transport_name == "wsl":
        return ExecDomain.RUNTIME_ROOT
    return ExecDomain.HOST_USER