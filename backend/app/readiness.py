from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

from app.config import AppConfig

PROBE_TIMEOUT_SECONDS = 0.5


@dataclass(frozen=True)
class DependencyStatus:
    name: str
    status: str
    detail: str


def _probe_tcp(name: str, host: str | None, port: int) -> DependencyStatus:
    if not host:
        return DependencyStatus(name, "not_configured", "环境变量未配置")
    try:
        with socket.create_connection((host, port), timeout=PROBE_TIMEOUT_SECONDS):
            return DependencyStatus(name, "ok", f"{host}:{port}")
    except OSError as exc:
        return DependencyStatus(name, "unavailable", f"{host}:{port} ({exc.__class__.__name__})")


def _endpoint_host(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return parsed.hostname


def readiness_snapshot(config: AppConfig) -> dict:
    del config
    dependencies = [
        _probe_tcp("RDS", os.environ.get("VERIFIX_RDS_HOST"), int(os.environ.get("VERIFIX_RDS_PORT", "3306"))),
        _probe_tcp("Redis", os.environ.get("VERIFIX_REDIS_HOST"), int(os.environ.get("VERIFIX_REDIS_PORT", "6379"))),
        _probe_tcp("OBS", _endpoint_host(os.environ.get("VERIFIX_OBS_ENDPOINT")), 443),
        _probe_tcp("MaaS", os.environ.get("VERIFIX_MAAS_HOST"), 443),
        _probe_tcp("CodeArts", os.environ.get("VERIFIX_CODEARTS_HOST"), 443),
    ]
    unavailable = [item for item in dependencies if item.status == "unavailable"]
    status = "ok" if not unavailable else "degraded"
    return {
        "status": status,
        "checked_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "dependencies": [item.__dict__ for item in dependencies],
    }