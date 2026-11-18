from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.envelope import ApiError, ErrorCode
from app.config import RealscanConfig
from app.realscan.capability import EnvironmentCapabilityProbe
from app.realscan.models import CapabilityState
from app.realscan.pipeline import RealscanPipeline
from app.realscan.policy import ImageResolver
from app.realscan.runtime import CommandResult, HostDockerTransport, RuntimeUnavailableError, UnavailableTransport
from app.runtime.exec_domain import ExecDomain

ROOT = Path(__file__).resolve().parents[2]


def _result(argv: list[str], exit_code: int = 0, stdout: str = "", stderr: str = "", timed_out: bool = False) -> CommandResult:
    return CommandResult(
        argv=tuple(argv),
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=1,
        timed_out=timed_out,
    )


class FakeTransport:
    name = "fake"
    exec_domain = ExecDomain.HOST_USER
    privilege_route = "NONE"

    def __init__(self, overrides: dict[str, CommandResult] | None = None, unavailable: bool = False) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.overrides = overrides or {}
        self.unavailable = unavailable

    def run(self, argv, timeout_seconds, cwd=None) -> CommandResult:
        joined = " ".join(argv)
        self.calls.append(tuple(argv))
        if self.unavailable:
            raise RuntimeUnavailableError("docker_cli")
        for marker, result in self.overrides.items():
            if marker in joined:
                return result
        if "Client.Version" in joined:
            return _result(list(argv), stdout="26.1.5\n")
        if "Server.Version" in joined:
            return _result(list(argv), stdout="26.1.5\n")
        if "docker ps" in joined:
            return _result(list(argv), stdout="abc\n")
        if "info" in joined:
            return _result(list(argv), stdout="overlay2|2\n")
        if "image inspect" in joined:
            return _result(list(argv), stdout="sha256:" + "a" * 64 + '|["repo@sha256:' + "b" * 64 + '"]|100\n')
        if "LOOPBACK_OK" in joined or "LOOPBACK_PROBE" in joined or "docker run" in joined:
            return _result(list(argv), stdout="LOOPBACK_OK\n")
        return _result(list(argv), stdout="")


def _probe(transport: FakeTransport, egress: str = "BLOCKED", images: list[str] | None = None) -> EnvironmentCapabilityProbe:
    resolver = ImageResolver(transport, images or ["verifix-sandbox:1.0.0", "verifix-runner:latest"])
    return EnvironmentCapabilityProbe(transport, resolver, budget_seconds=10.0, egress_checker=lambda _t: egress)


class CapabilityProbeTest(unittest.TestCase):
    def test_cap01_all_six_states_available(self) -> None:
        transport = FakeTransport()
        capability = _probe(transport, egress="OPEN").probe()
        self.assertIs(capability.docker_cli, CapabilityState.AVAILABLE)
        self.assertIs(capability.daemon, CapabilityState.AVAILABLE)
        self.assertIs(capability.socket_permission, CapabilityState.AVAILABLE)
        self.assertIs(capability.image_availability, CapabilityState.AVAILABLE)
        self.assertIs(capability.egress_network, CapabilityState.AVAILABLE)
        self.assertIs(capability.loopback, CapabilityState.AVAILABLE)
        self.assertTrue(capability.all_available())

    def test_cap02_transport_selection_prefers_host_then_wsl(self) -> None:
        with mock.patch("app.realscan.runtime.shutil.which", side_effect=lambda name: "/usr/bin/docker" if name == "docker" else None):
            from app.realscan.runtime import select_transport

            self.assertIsInstance(select_transport(RealscanConfig(runtime_transport="auto")), HostDockerTransport)
        with mock.patch("app.realscan.runtime.shutil.which", side_effect=lambda name: "wsl.exe" if name.startswith("wsl") else None):
            from app.realscan.runtime import select_transport, WslDockerTransport

            transport = select_transport(RealscanConfig(runtime_transport="auto"))
            self.assertIsInstance(transport, WslDockerTransport)
            self.assertIs(transport.exec_domain, ExecDomain.RUNTIME_ROOT)
            self.assertEqual(transport.privilege_route, "WSL_DISTRO_ROOT")
        with mock.patch("app.realscan.runtime.shutil.which", return_value=None):
            from app.realscan.runtime import select_transport

            self.assertIsInstance(select_transport(RealscanConfig()), UnavailableTransport)

    def test_cap03_daemon_failure_degrades_only_that_item(self) -> None:
        transport = FakeTransport({"Server.Version": _result(["docker", "version"], exit_code=1)})
        capability = _probe(transport).probe()
        self.assertIs(capability.daemon, CapabilityState.UNAVAILABLE)
        self.assertIs(capability.docker_cli, CapabilityState.AVAILABLE)
        self.assertIn("daemon", capability.blocking_missing())

    def test_cap04_image_alias_is_registered_with_image_id(self) -> None:
        transport = FakeTransport(
            {
                "verifix-sandbox:1.0.0": _result(["docker", "image", "inspect"], exit_code=1, stderr="No such image"),
                "verifix-runner:latest": _result(
                    ["docker", "image", "inspect"],
                    stdout="sha256:" + "c" * 64 + "|[]|131\n",
                ),
            }
        )
        resolution = ImageResolver(transport, ["verifix-sandbox:1.0.0", "verifix-runner:latest"]).resolve("verifix-sandbox:1.0.0")
        self.assertEqual(resolution.source, "LOCAL_ALIAS")
        self.assertTrue(resolution.alias_used)
        self.assertTrue(resolution.local_build)
        self.assertEqual(resolution.image_id, "sha256:" + "c" * 64)
        self.assertEqual(resolution.policy_image, "verifix-sandbox:1.0.0")

    def test_cap05_socket_denial_records_host_user_fact(self) -> None:
        transport = FakeTransport({"docker ps": _result(["docker", "ps"], exit_code=1, stderr="permission denied")})
        capability = _probe(transport).probe()
        self.assertIs(capability.socket_permission, CapabilityState.UNAVAILABLE)
        self.assertTrue(any("HOST_USER: permission denied" in item for item in capability.details))

    def test_cap06_budget_exhausted_is_unverified(self) -> None:
        transport = FakeTransport({"Client.Version": _result(["docker", "version"], timed_out=True)})
        capability = _probe(transport).probe()
        self.assertIs(capability.docker_cli, CapabilityState.UNVERIFIED)


class PipelineGateTest(unittest.TestCase):
    def test_cap07_unavailable_runtime_raises_vf8010_without_container_run(self) -> None:
        config = RealscanConfig(runtime_transport="host")
        pipeline = RealscanPipeline(config, transport=FakeTransport(unavailable=True))
        with self.assertRaises(ApiError) as raised:
            pipeline.ensure_ready()
        self.assertIs(raised.exception.code, ErrorCode.SANDBOX_UNVERIFIABLE)
        self.assertEqual(pipeline.container_run_count, 0)

    def test_cap08_missing_image_blocks_before_container_commands(self) -> None:
        config = RealscanConfig(runtime_transport="host")
        transport = FakeTransport(
            {"image inspect": _result(["docker", "image", "inspect"], exit_code=1, stderr="No such image")}
        )
        pipeline = RealscanPipeline(config, transport=transport)
        with self.assertRaises(ApiError) as raised:
            pipeline.ensure_ready()
        self.assertIs(raised.exception.code, ErrorCode.SANDBOX_UNVERIFIABLE)
        self.assertEqual(pipeline.container_run_count, 0)


if __name__ == "__main__":
    unittest.main()