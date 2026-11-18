from __future__ import annotations

import json
import socket
import time
from datetime import datetime, timezone
from typing import Callable, Sequence

from app.realscan.models import CapabilityState, EnvironmentCapability
from app.realscan.policy import ImageResolver, runtime_facts_from_info
from app.realscan.probe_scripts import LOOPBACK_PROBE
from app.realscan.runtime import RuntimeTransport, RuntimeUnavailableError

EGRESS_ENDPOINT = ("1.1.1.1", 53)
PERMISSION_DENIED_MARKERS = ("permission denied", "access denied", "got permission denied")


class EnvironmentCapabilityProbe:
    def __init__(
        self,
        transport: RuntimeTransport,
        images: ImageResolver,
        budget_seconds: float = 15.0,
        required_images: Sequence[str] | None = None,
        probe_user: str = "root",
        egress_checker: Callable[[float], str] | None = None,
    ) -> None:
        self.transport = transport
        self.images = images
        self.budget_seconds = float(budget_seconds)
        self.required_images = tuple(required_images or images.candidates)
        self.probe_user = probe_user
        self.egress_checker = egress_checker or self._default_egress

    def probe(self, want_egress: bool = True, want_loopback: bool = True) -> EnvironmentCapability:
        started = time.perf_counter()
        deadline = started + self.budget_seconds
        details: list[str] = [f"transport={self.transport.name}", f"exec_domain={self.transport.exec_domain.value}"]
        if self.transport.privilege_route != "NONE":
            details.append(f"privilege_route={self.transport.privilege_route}")

        cli_state, client_version = self._probe_cli(deadline)
        daemon_state, server_version = self._probe_daemon(deadline)
        socket_state, socket_detail = self._probe_socket(deadline)
        if socket_detail:
            details.append(socket_detail)
        image_state, image_detail = self._probe_images(deadline)
        details.extend(image_detail)
        egress_state = self._probe_egress(deadline) if want_egress else CapabilityState.UNVERIFIED
        loopback_state = self._probe_loopback(deadline) if want_loopback else CapabilityState.UNVERIFIED

        info = self._safe_run(["docker", "info", "--format", "{{.Driver}}|{{.CgroupVersion}}"], deadline, 5.0)
        runtime = runtime_facts_from_info(info, self.probe_user, server_version or client_version)
        details.append(f"probe_elapsed_ms={int((time.perf_counter() - started) * 1000)}")
        return EnvironmentCapability(
            docker_cli=cli_state,
            daemon=daemon_state,
            socket_permission=socket_state,
            image_availability=image_state,
            egress_network=egress_state,
            loopback=loopback_state,
            detected_at=datetime.now(timezone.utc),
            exec_domain=self.transport.exec_domain,
            runtime=runtime,
            details=details,
        )

    def _remaining(self, deadline: float) -> float:
        return deadline - time.perf_counter()

    def _safe_run(self, argv: Sequence[str], deadline: float, timeout_seconds: float):
        remaining = self._remaining(deadline)
        if remaining <= 0:
            return None
        budget = min(timeout_seconds, remaining)
        try:
            return self.transport.run(argv, budget)
        except RuntimeUnavailableError:
            return None

    def _probe_cli(self, deadline: float) -> tuple[CapabilityState, str]:
        result = self._safe_run(["docker", "version", "--format", "{{.Client.Version}}"], deadline, 8.0)
        if result is None:
            return CapabilityState.UNAVAILABLE, ""
        if result.ok and result.stdout.strip():
            return CapabilityState.AVAILABLE, result.stdout.strip()
        if result.timed_out:
            return CapabilityState.UNVERIFIED, ""
        return CapabilityState.UNAVAILABLE, ""

    def _probe_daemon(self, deadline: float) -> tuple[CapabilityState, str]:
        result = self._safe_run(["docker", "version", "--format", "{{.Server.Version}}"], deadline, 4.0)
        if result is None:
            return CapabilityState.UNAVAILABLE, ""
        if result.ok and result.stdout.strip():
            return CapabilityState.AVAILABLE, result.stdout.strip()
        if result.timed_out:
            return CapabilityState.UNVERIFIED, ""
        return CapabilityState.UNAVAILABLE, ""

    def _probe_socket(self, deadline: float) -> tuple[CapabilityState, str]:
        result = self._safe_run(["docker", "ps", "--format", "{{.ID}}"], deadline, 4.0)
        if result is None:
            return CapabilityState.UNAVAILABLE, "socket probe unavailable"
        if result.ok:
            return CapabilityState.AVAILABLE, ""
        text = (result.stderr or "").lower()
        if any(marker in text for marker in PERMISSION_DENIED_MARKERS):
            return CapabilityState.UNAVAILABLE, f"HOST_USER: permission denied ({self.transport.name})"
        if result.timed_out:
            return CapabilityState.UNVERIFIED, "socket probe timeout"
        return CapabilityState.UNAVAILABLE, "socket probe failed"

    def _probe_images(self, deadline: float) -> tuple[CapabilityState, list[str]]:
        missing: list[str] = []
        for image in self.required_images:
            if self._remaining(deadline) <= 0:
                missing.append(f"image budget exhausted: {image}")
                continue
            try:
                resolution = self.images.resolve(image)
            except RuntimeUnavailableError:
                return CapabilityState.UNAVAILABLE, ["image probe unavailable: runtime"]
            if not resolution.image_id:
                missing.append(f"image missing: {image}")
        if missing:
            if all(item.startswith("image budget exhausted") for item in missing):
                return CapabilityState.UNVERIFIED, missing
            return CapabilityState.UNAVAILABLE, missing
        return CapabilityState.AVAILABLE, []

    def _default_egress(self, timeout: float) -> str:
        try:
            connection = socket.create_connection(EGRESS_ENDPOINT, timeout=timeout)
        except socket.timeout:
            return "TIMEOUT"
        except OSError:
            return "BLOCKED"
        connection.close()
        return "OPEN"

    def _probe_egress(self, deadline: float) -> CapabilityState:
        remaining = self._remaining(deadline)
        if remaining <= 0:
            return CapabilityState.UNVERIFIED
        try:
            outcome = self.egress_checker(min(2.0, remaining))
        except OSError:
            return CapabilityState.UNAVAILABLE
        if outcome == "OPEN":
            return CapabilityState.AVAILABLE
        if outcome == "TIMEOUT":
            return CapabilityState.UNVERIFIED
        return CapabilityState.UNAVAILABLE

    def _probe_loopback(self, deadline: float) -> CapabilityState:
        image = ""
        for candidate in self.required_images:
            try:
                resolution = self.images.resolve(candidate)
            except RuntimeUnavailableError:
                return CapabilityState.UNVERIFIED
            if resolution.image_id:
                image = resolution.resolved_image or candidate
                break
        if not image:
            return CapabilityState.UNVERIFIED
        remaining = self._remaining(deadline)
        if remaining <= 0:
            return CapabilityState.UNVERIFIED
        try:
            result = self.transport.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network=none",
                    "--entrypoint",
                    "python",
                    image,
                    "-c",
                    LOOPBACK_PROBE,
                ],
                min(8.0, remaining),
            )
        except RuntimeUnavailableError:
            return CapabilityState.UNVERIFIED
        if result.timed_out:
            return CapabilityState.UNVERIFIED
        if "LOOPBACK_OK" in result.stdout:
            return CapabilityState.AVAILABLE
        payload = None
        for line in reversed((result.stdout or "").splitlines()):
            text = line.strip()
            if text.startswith("{") and text.endswith("}"):
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    payload = None
                break
        if isinstance(payload, dict) and all(payload.get(key) is True for key in ("bind", "listen", "connect")):
            return CapabilityState.AVAILABLE
        return CapabilityState.UNAVAILABLE