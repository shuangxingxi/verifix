from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.realscan.constraints import ConstraintVerifier, aggregate_judgement, parse_payload
from app.realscan.models import (
    CapabilityState,
    ConstraintCheck,
    EnvironmentCapability,
    ImageResolution,
    Judgement,
    RuntimeFacts,
)
from app.realscan.policy import JUDGEMENT_CLASSES, KEY_TO_CLASS, PolicyFile
from app.realscan.probe_scripts import (
    EGRESS_PROBE,
    FILESYSTEM_PROBE,
    IDENTITY_PROBE,
    LOOPBACK_PROBE,
    P4_01_PROBE,
    P4_05_PROBE,
)
from app.realscan.runtime import CommandResult
from app.realscan.target import TargetViewBuilder
from app.runtime.exec_domain import ExecDomain

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "sandbox" / "spec.json"

HOST_CONFIG = {
    "Memory": 1024 * 1024 * 1024,
    "NanoCpus": 1_000_000_000,
    "PidsLimit": 128,
    "CapDrop": ["ALL"],
    "SecurityOpt": ["no-new-privileges"],
    "NetworkMode": "none",
    "ReadonlyRootfs": True,
    "User": "10001:10001",
    "Tmpfs": {"/tmp": "rw,noexec,nosuid,size=64m", "/workspace": "rw,noexec,nosuid,size=256m"},
}


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _result(argv, exit_code=0, stdout="", stderr="", timed_out=False) -> CommandResult:
    return CommandResult(tuple(argv), exit_code, stdout, stderr, 1, timed_out)


class FakeTransport:
    name = "fake"
    exec_domain = ExecDomain.RUNTIME_ROOT
    privilege_route = "WSL_DISTRO_ROOT"

    def __init__(self, host_config: dict | None = None, payloads: dict[str, dict] | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.host_config = dict(host_config or HOST_CONFIG)
        self.payloads = {
            "identity": {"uid": 10001, "gid": 10001, "cap_eff": "0000000000000000", "no_new_privs": "1", "setuid_blocked": True},
            "egress": {"target": "1.1.1.1:53", "ok": False, "error_type": "OSError", "detail": "blocked"},
            "loopback": {"bind": True, "listen": True, "connect": True},
            "filesystem": {
                "root_write": False,
                "tmp_writable": True,
                "workspace_writable": True,
                "src_write": False,
                "src_read": True,
            },
            "p4-01": {"dot_git_visible": False, "git_config_readable": False, "positive_control": True},
        }
        self.payloads.update(payloads or {})

    def run(self, argv, timeout_seconds, cwd=None) -> CommandResult:
        joined = " ".join(str(item) for item in argv)
        self.calls.append(tuple(str(item) for item in argv))
        if "{{json .HostConfig}}" in joined:
            return _result(argv, stdout=json.dumps(self.host_config))
        if "{{.State.Running}}" in joined:
            return _result(argv, stdout="true")
        if "docker ps -a" in joined:
            return _result(argv, stdout="")
        if "docker inspect --format" in joined:
            return _result(argv, stdout="")
        if "docker create" in joined or "docker rm -f" in joined or "docker kill" in joined:
            return _result(argv, stdout="")
        if "docker run" in joined:
            for key, payload in self.payloads.items():
                if _script_marker(key) in joined:
                    return _result(argv, stdout=json.dumps(payload))
            if "while True" in joined:
                return _result(argv, stdout="")
            return _result(argv, stdout="")
        return _result(argv, stdout="")


def _script_marker(key: str) -> str:
    return {"identity": IDENTITY_PROBE, "egress": EGRESS_PROBE, "loopback": LOOPBACK_PROBE, "filesystem": FILESYSTEM_PROBE, "p4-01": P4_01_PROBE, "p4-05": P4_05_PROBE}[key]


def _capability(blocking: bool = False) -> EnvironmentCapability:
    state = CapabilityState.UNAVAILABLE if blocking else CapabilityState.AVAILABLE
    return EnvironmentCapability(
        docker_cli=state,
        daemon=state,
        socket_permission=state,
        image_availability=state,
        egress_network=CapabilityState.AVAILABLE,
        loopback=CapabilityState.AVAILABLE,
        exec_domain=ExecDomain.RUNTIME_ROOT,
        runtime=RuntimeFacts(
            network_mode="NONE_LOOPBACK",
            read_only_rootfs=True,
            cap_drop=["ALL"],
            security_opts=["no-new-privileges"],
            user="10001:10001",
            memory_bytes=1024 * 1024 * 1024,
            nano_cpus=1_000_000_000,
            pids_limit=128,
            tmpfs_mounts=["/tmp", "/workspace"],
            docker_version="26.1.5",
            runtime_driver="overlay2",
            cgroup_version="2",
        ),
        details=[],
    )


IMAGE = ImageResolution(
    policy_image="verifix-sandbox:1.0.0",
    resolved_image="verifix-runner:latest",
    image_id="sha256:" + "b" * 64,
    repo_digests=[],
    local_build=True,
    alias_used=True,
    source="LOCAL_ALIAS",
)


def _verifier(tmp: Path, transport: FakeTransport, capability: EnvironmentCapability | None = None, p4_05: float = 60.0):
    policy = PolicyFile.load(POLICY_PATH)
    view = TargetViewBuilder().build_p4_fixture(tmp)
    clock = FakeClock()
    verifier = ConstraintVerifier(
        policy=policy,
        capability=capability or _capability(),
        transport=transport,
        image=IMAGE,
        view_dir=Path(view.view_root),
        evidence_dir=tmp / "evidence",
        probe_timeout_seconds=10.0,
        p4_05_seconds=p4_05,
        sleeper=clock.sleep,
        clock=clock,
    )
    return verifier, view


class PolicyClassMappingTest(unittest.TestCase):
    def test_cst01_eleven_keys_map_to_ten_classes(self) -> None:
        policy = PolicyFile.load(POLICY_PATH)
        self.assertEqual(len(policy.isolation), 11)
        self.assertEqual(len(set(KEY_TO_CLASS.values())), 10)
        self.assertEqual(len(JUDGEMENT_CLASSES), 10)
        self.assertEqual(KEY_TO_CLASS["root_filesystem"], KEY_TO_CLASS["tmpfs"])
        self.assertEqual(set(KEY_TO_CLASS), set(policy.isolation))


class ConstraintJudgementTest(unittest.TestCase):
    def test_cst02_network_blocked_passes_open_fails(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            verifier, _ = _verifier(tmp, FakeTransport())
            record = verifier.verify("VER-20261114T120000+0800-abcd", run_p4_05=True)
            network = next(check for check in record.checks if check.check_id.startswith("network"))
            self.assertIs(network.judgement, Judgement.PASS)
            self.assertIs(record.verdict, Judgement.PASS)

            open_transport = FakeTransport(payloads={"egress": {"ok": True, "error_type": "", "target": "1.1.1.1:53"}})
            verifier2, _ = _verifier(tmp / "b", open_transport)
            record2 = verifier2.verify("VER-20261114T120000+0800-abce", run_p4_05=True)
            network2 = next(check for check in record2.checks if check.check_id.startswith("network"))
            self.assertIs(network2.judgement, Judgement.FAIL)
            self.assertIs(record2.verdict, Judgement.FAIL)

    def test_cst03_filesystem_and_source_mount(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            broken = {"root_write": True, "tmp_writable": True, "workspace_writable": True, "src_write": True, "src_read": True}
            verifier, _ = _verifier(tmp, FakeTransport(payloads={"filesystem": broken}))
            record = verifier.verify("VER-20261114T120000+0800-abcd")
            fs = next(check for check in record.checks if check.policy_key == "filesystem_writable_surface")
            mount = next(check for check in record.checks if check.policy_key == "source_mount")
            self.assertIs(fs.judgement, Judgement.FAIL)
            self.assertIs(mount.judgement, Judgement.FAIL)

    def test_cst04_identity_and_privilege_checks(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            bad_identity = {"uid": 0, "gid": 0, "cap_eff": "000000001fffffff", "no_new_privs": "0", "setuid_blocked": False}
            verifier, _ = _verifier(tmp, FakeTransport(payloads={"identity": bad_identity}))
            record = verifier.verify("VER-20261114T120000+0800-abcd")
            user = next(check for check in record.checks if check.policy_key == "exec_user")
            caps = next(check for check in record.checks if check.policy_key == "capability_set")
            nnp = next(check for check in record.checks if check.policy_key == "no_new_privileges")
            self.assertIs(user.judgement, Judgement.FAIL)
            self.assertIs(caps.judgement, Judgement.FAIL)
            self.assertIs(nnp.judgement, Judgement.FAIL)

    def test_cst05_resource_limits_from_inspect(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            config = dict(HOST_CONFIG)
            config["Memory"] = 512 * 1024 * 1024
            verifier, _ = _verifier(tmp, FakeTransport(host_config=config))
            record = verifier.verify("VER-20261114T120000+0800-abcd")
            memory = next(check for check in record.checks if check.policy_key == "memory_limit")
            self.assertIs(memory.judgement, Judgement.FAIL)
            cpu = next(check for check in record.checks if check.policy_key == "cpu_limit")
            pids = next(check for check in record.checks if check.policy_key == "pids_limit")
            self.assertIs(cpu.judgement, Judgement.PASS)
            self.assertIs(pids.judgement, Judgement.PASS)

    def test_cst06_aggregation_rules(self) -> None:
        passed = ConstraintCheck(check_id="a", policy_key="network", judgement=Judgement.PASS)
        failed = ConstraintCheck(check_id="b", policy_key="memory_limit", judgement=Judgement.FAIL)
        unverified = ConstraintCheck(
            check_id="c",
            policy_key="timeout_termination",
            judgement=Judgement.UNVERIFIED,
            missing_reason="not_executed",
            retest_hint="retest",
        )
        self.assertIs(aggregate_judgement([passed]), Judgement.PASS)
        self.assertIs(aggregate_judgement([passed, unverified]), Judgement.UNVERIFIED)
        self.assertIs(aggregate_judgement([passed, unverified, failed]), Judgement.FAIL)
        self.assertIs(aggregate_judgement([failed]), Judgement.FAIL)

    def test_cst07_p4_fixture_view_has_no_git_and_probe_passes(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            view = TargetViewBuilder().build_p4_fixture(tmp)
            view_root = Path(view.view_root)
            self.assertTrue((view_root / "app" / "main.py").is_file())
            self.assertFalse((view_root / ".git").exists())
            self.assertTrue((Path(view.source_root) / ".git" / "config").is_file())
            self.assertFalse(view.truth_present)
            verifier, _ = _verifier(tmp, FakeTransport())
            record = verifier.verify("VER-20261114T120000+0800-abcd")
            p4 = next(check for check in record.checks if check.policy_key == "escape_case:P4-01")
            self.assertIs(p4.judgement, Judgement.PASS)

    def test_cst08_p4_05_window_and_cleanup(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            transport = FakeTransport()
            verifier, _ = _verifier(tmp, transport)
            record = verifier.verify("VER-20261114T120000+0800-abcd", run_p4_05=True)
            p4 = next(check for check in record.checks if check.policy_key == "escape_case:P4-05")
            self.assertIs(p4.judgement, Judgement.PASS)
            self.assertIn("terminated_ms=60000", p4.observed)
            self.assertTrue(any("docker kill" in " ".join(call) for call in transport.calls))
            self.assertTrue(any("docker rm -f" in " ".join(call) for call in transport.calls))
            self.assertIs(record.verdict, Judgement.PASS)

    def test_cst08b_p4_05_skipped_keeps_record_unverified(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            verifier, _ = _verifier(tmp, FakeTransport())
            record = verifier.verify("VER-20261114T120000+0800-abcd", run_p4_05=False)
            p4 = next(check for check in record.checks if check.policy_key == "escape_case:P4-05")
            self.assertIs(p4.judgement, Judgement.UNVERIFIED)
            self.assertEqual(p4.missing_reason, "not_executed")
            self.assertIsNot(record.verdict, Judgement.PASS)

    def test_cst09_privilege_route_is_category_only(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            verifier, _ = _verifier(tmp, FakeTransport())
            record = verifier.verify("VER-20261114T120000+0800-abcd")
            self.assertEqual(record.privilege_route, "WSL_DISTRO_ROOT")
            dumped = json.dumps(record.model_dump(mode="json"), ensure_ascii=False)
            for marker in ("sudo", "password=", "--password", "DOCKER_HOST", "SECRET_KEY="):
                self.assertNotIn(marker, dumped)

    def test_cst10_blocking_capability_marks_all_unverified(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            verifier, _ = _verifier(tmp, FakeTransport(), capability=_capability(blocking=True))
            record = verifier.verify("VER-20261114T120000+0800-abcd")
            self.assertIs(record.verdict, Judgement.UNVERIFIED)
            self.assertTrue(all(check.judgement is Judgement.UNVERIFIED for check in record.checks))
            self.assertTrue(all(check.missing_reason == "capability_unavailable" for check in record.checks))
            self.assertEqual(len(record.adopted_defaults), 16)
            self.assertTrue(all(item.pending for item in record.adopted_defaults))


class PayloadParseTest(unittest.TestCase):
    def test_parse_payload_uses_last_json_line(self) -> None:
        payload = parse_payload('noise\n{"ok": false}\ntrailing\n')
        self.assertEqual(payload, {"ok": False})
        self.assertIsNone(parse_payload("plain text"))


class IntegrityAndBoundaryTest(unittest.TestCase):
    def test_int01_immutable_files_are_guarded(self) -> None:
        from app.api.envelope import ApiError, ErrorCode
        from app.config import RealscanConfig
        from app.realscan.pipeline import IMMUTABLE_RELATIVE, RealscanPipeline

        with TemporaryDirectory() as tmp_raw:
            root = Path(tmp_raw)
            for relative in IMMUTABLE_RELATIVE:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("original", encoding="utf-8")
            pipeline = RealscanPipeline(RealscanConfig(runtime_transport="host"), project_root=root)
            before = pipeline.immutable_snapshot()
            pipeline.assert_immutable(before)
            (root / "sandbox" / "spec.json").write_text("mutated", encoding="utf-8")
            with self.assertRaises(ApiError) as raised:
                pipeline.assert_immutable(before)
            self.assertIs(raised.exception.code, ErrorCode.EVIDENCE_INTEGRITY)
            self.assertIn("policy_or_target_mutated", str(raised.exception))

    def test_int02_real_local_is_not_container_group(self) -> None:
        from app.realscan.boundary import is_container_conclusion

        self.assertFalse(is_container_conclusion(ExecDomain.HOST_USER, "REAL_LOCAL", "REAL_EXECUTION"))
        self.assertFalse(is_container_conclusion(ExecDomain.RUNTIME_ROOT, "REAL_CONTAINER", "RECORDED_STUB"))
        self.assertTrue(is_container_conclusion(ExecDomain.RUNTIME_ROOT, "REAL_CONTAINER", "REAL_EXECUTION"))
        self.assertTrue(is_container_conclusion(ExecDomain.CONTAINER_EXEC, "REAL_CONTAINER", "REAL_EXECUTION"))


if __name__ == "__main__":
    unittest.main()