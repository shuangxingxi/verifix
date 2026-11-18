from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Sequence

from app.api.envelope import ApiError, ErrorCode
from app.realscan.capability import EnvironmentCapabilityProbe
from app.realscan.models import EnvironmentCapability
from app.realscan.policy import ImageResolver, RunSpec
from app.realscan.runtime import CommandResult, RuntimeTransport, select_transport


IMMUTABLE_RELATIVE = (
    "sandbox/spec.json",
    "verifix-target/app/main.py",
    "verifix-target/app/config.py",
    "verifix-target/requirements.txt",
    "verifix-target/ground_truth.json",
    "verifix-target/init_db.py",
)

MISSING = "MISSING"


class RealscanPipeline:
    def __init__(
        self,
        config: object,
        transport: RuntimeTransport | None = None,
        resolver: ImageResolver | None = None,
        probe: EnvironmentCapabilityProbe | None = None,
        project_root: Path | None = None,
    ) -> None:
        self.config = config
        self.project_root = Path(project_root) if project_root is not None else Path.cwd()
        self.transport = transport or select_transport(config)
        images = list(getattr(config, "sandbox_images", ()) or [])
        targets = list(getattr(config, "target_images", ()) or [])
        required = images + [item for item in targets if item not in images]
        self.resolver = resolver or ImageResolver(self.transport, required)
        self.probe = probe or EnvironmentCapabilityProbe(
            self.transport,
            self.resolver,
            budget_seconds=float(getattr(config, "probe_budget_seconds", 10)),
            required_images=required,
            probe_user=str(getattr(config, "wsl_user", "root")),
        )
        self.container_run_count = 0

    def immutable_snapshot(self) -> dict[str, str]:
        digests: dict[str, str] = {}
        for relative in IMMUTABLE_RELATIVE:
            path = self.project_root / relative
            digests[relative] = (
                hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else MISSING
            )
        return digests

    def assert_immutable(self, before: dict[str, str]) -> None:
        after = self.immutable_snapshot()
        changed = sorted(relative for relative in set(before) | set(after) if before.get(relative) != after.get(relative))
        if changed:
            raise ApiError(ErrorCode.EVIDENCE_INTEGRITY, "policy_or_target_mutated: " + ",".join(changed))

    def capability(self) -> EnvironmentCapability:
        return self.probe.probe()

    def ensure_ready(self) -> EnvironmentCapability:
        capability = self.probe.probe()
        missing = capability.blocking_missing()
        if missing:
            raise ApiError(ErrorCode.SANDBOX_UNVERIFIABLE, "missing capabilities: " + ",".join(missing))
        return capability

    def run_container(
        self,
        spec: RunSpec,
        command: Sequence[str],
        timeout_seconds: float,
    ) -> CommandResult:
        self.container_run_count += 1
        created = self.transport.run(spec.argv, timeout_seconds)
        if not created.ok:
            return created
        argv = ["docker", "start", "-a", spec.container_name]
        started = self.transport.run(argv, timeout_seconds)
        self.transport.run(["docker", "rm", "-f", spec.container_name], 30.0)
        return started