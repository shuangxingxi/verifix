from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.envelope import ApiError, ErrorCode
from app.eval.isolation import AccessAuditLog, AnswerIsolationGuard, AuditArchiveQuery, PermissionProbe
from app.realscan.boundary import CONFLICT_DISPOSITIONS
from app.realscan.isolation_bridge import ContainerIsolationVerifier
from app.realscan.models import DenialKind
from app.realscan.policy import PolicyFile
from app.realscan.runtime import CommandResult, RuntimeUnavailableError
from app.runtime.exec_domain import ExecDomain, FailureKind

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "sandbox" / "spec.json"
CASES = ROOT / "eval" / "cases"
ISO_ID = "ISO-20261114T120000+0800-abcd"


def probe_set(readable: bool = False, positive: bool = True, decoy_permission: bool = True) -> list[dict]:
    base = "READABLE" if readable else "DENIED"
    kind = "UNKNOWN" if readable else "PATH_NOT_EXIST"
    return [
        {"probe": "enumerate", "result": base, "denial_kind": kind},
        {"probe": "open", "result": base, "denial_kind": kind},
        {"probe": "relative", "result": base, "denial_kind": kind},
        {"probe": "traversal", "result": base, "denial_kind": kind},
        {"probe": "symlink", "result": base, "denial_kind": kind},
        {
            "probe": "decoy_expected",
            "result": "DENIED",
            "denial_kind": "PERMISSION_DENIED" if decoy_permission else "PATH_NOT_EXIST",
        },
        {
            "probe": "decoy_shadow",
            "result": "DENIED",
            "denial_kind": "PERMISSION_DENIED" if decoy_permission else "PATH_NOT_EXIST",
        },
    ]


class FakeTransport:
    name = "fake"
    exec_domain = ExecDomain.RUNTIME_ROOT
    privilege_route = "WSL_DISTRO_ROOT"

    def __init__(self, payload: dict | None = None, unavailable: bool = False) -> None:
        self.payload = payload
        self.unavailable = unavailable
        self.calls: list[tuple[str, ...]] = []

    def run(self, argv, timeout_seconds, cwd=None, stdin_text=None) -> CommandResult:
        self.calls.append(tuple(str(item) for item in argv))
        if self.unavailable:
            raise RuntimeUnavailableError("daemon")
        body = json.dumps(self.payload or {})
        return CommandResult(tuple(str(item) for item in argv), 0, body + "\n", "", 1, False)


class StubProbe(PermissionProbe):
    def __init__(self, denied=None, cases_readable: bool = True) -> None:
        self._denied = denied or []
        self._cases_readable = cases_readable

    def probe_denied(self):
        return list(self._denied)

    def cases_readable(self) -> bool:
        return self._cases_readable


def _guard(tmp: Path, denied=None, cases_readable: bool = True, timeout_ms: int = 2000) -> AnswerIsolationGuard:
    cases = tmp / "cases"
    expected = tmp / "expected"
    cases.mkdir(exist_ok=True)
    expected.mkdir(exist_ok=True)
    return AnswerIsolationGuard(
        cases,
        expected,
        audit=AccessAuditLog(tmp / "audit.jsonl"),
        timeout_ms=timeout_ms,
        probe=StubProbe(denied, cases_readable),
    )


class IsolationBridgeTest(unittest.TestCase):
    def test_iso01_five_probes_denied_and_positive_control(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            transport = FakeTransport({"probes": probe_set(), "positive_control": True, "uid": 10001, "gid": 10001})
            verifier = ContainerIsolationVerifier(
                transport, CASES, tmp, policy=PolicyFile.load(POLICY)
            )
            record = verifier.verify(ISO_ID)
            self.assertEqual(len(record.probes), 7)
            self.assertEqual(record.exec_identity, "uid=10001,gid=10001")
            self.assertIs(record.exec_domain, ExecDomain.CONTAINER_EXEC)
            self.assertEqual(record.exec_success_count, 0)
            self.assertTrue(record.publishable)
            self.assertEqual(record.visible_roots, ["/cases"])
            joined = " ".join(transport.calls[0])
            self.assertIn(":/cases:ro", joined)
            volumes = [item for item in transport.calls[0] if str(item).startswith("--volume=")]
            self.assertEqual(len(volumes), 1)
            self.assertNotIn("expected", volumes[0])

    def test_iso02_readable_answer_raises(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            transport = FakeTransport({"probes": probe_set(readable=True), "positive_control": True, "uid": 10001, "gid": 10001})
            verifier = ContainerIsolationVerifier(transport, CASES, Path(tmp_raw), policy=PolicyFile.load(POLICY))
            with self.assertRaises(ApiError) as raised:
                verifier.verify(ISO_ID)
            self.assertIs(raised.exception.code, ErrorCode.EVAL_ISOLATION_UNMET)
            self.assertIn("隔离缺陷", str(raised.exception))

    def test_iso03_permission_denied_is_observable(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            transport = FakeTransport(
                {"probes": probe_set(decoy_permission=False), "positive_control": True, "uid": 10001, "gid": 10001}
            )
            verifier = ContainerIsolationVerifier(transport, CASES, Path(tmp_raw), policy=PolicyFile.load(POLICY))
            with self.assertRaises(ApiError):
                verifier.verify(ISO_ID)

    def test_iso04_positive_control_failure_is_probe_invalid(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            transport = FakeTransport({"probes": probe_set(), "positive_control": False, "uid": 10001, "gid": 10001})
            verifier = ContainerIsolationVerifier(transport, CASES, Path(tmp_raw), policy=PolicyFile.load(POLICY))
            with self.assertRaises(ApiError) as raised:
                verifier.verify(ISO_ID)
            self.assertIn("正例", str(raised.exception))

    def test_iso05_runtime_unavailable_is_vf8003(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            transport = FakeTransport(unavailable=True)
            verifier = ContainerIsolationVerifier(transport, CASES, tmp, policy=PolicyFile.load(POLICY))
            with self.assertRaises(ApiError) as raised:
                verifier.verify(ISO_ID)
            self.assertIs(raised.exception.code, ErrorCode.EVAL_ISOLATION_UNMET)
            entries = AuditArchiveQuery(tmp / "audit" / "access.jsonl").search(ISO_ID)
            self.assertTrue(any(entry.reason == "RUNTIME_UNAVAILABLE" for entry in entries))

    def test_iso06_audit_archive_query_keeps_both_domains(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            transport = FakeTransport({"probes": probe_set(), "positive_control": True, "uid": 10001, "gid": 10001})
            verifier = ContainerIsolationVerifier(transport, CASES, tmp, policy=PolicyFile.load(POLICY))
            verifier.verify(ISO_ID)
            query = AuditArchiveQuery(tmp / "audit" / "access.jsonl")
            entries = query.search(ISO_ID)
            self.assertTrue(entries)
            self.assertEqual(query.exec_success_count(), 0)
            actors = {entry.actor for entry in entries}
            self.assertIn("exec", actors)
            self.assertIn("control", actors)

    def test_iso07_failure_kinds_are_classified(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            guard = _guard(tmp, denied=["open"])
            with self.assertRaises(ApiError):
                guard.self_check(exec_domain=ExecDomain.HOST_USER)
            with self.assertRaises(ApiError):
                guard.self_check(exec_domain=ExecDomain.CONTAINER_EXEC)
            with self.assertRaises(ApiError):
                _guard(tmp, denied=[], cases_readable=False).self_check(exec_domain=ExecDomain.CONTAINER_EXEC)
            with self.assertRaises(ApiError):
                guard.self_check(exec_domain=ExecDomain.CONTAINER_EXEC, runtime_available=False)
            with self.assertRaises(ApiError):
                _guard(tmp, denied=[], timeout_ms=-1).self_check(exec_domain=ExecDomain.CONTAINER_EXEC)

    def test_iso08_publishable_only_in_container_domain(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            host = _guard(tmp).self_check(exec_domain=ExecDomain.HOST_USER)
            self.assertTrue(host.ok)
            self.assertFalse(host.publishable)
            container = _guard(tmp).self_check(exec_domain=ExecDomain.CONTAINER_EXEC)
            self.assertTrue(container.publishable)
            self.assertIsNone(container.failure_kind)

    def test_iso09_conflict_dispositions_are_complete(self) -> None:
        self.assertEqual(len(CONFLICT_DISPOSITIONS), 10)
        self.assertEqual([item.k_id for item in CONFLICT_DISPOSITIONS], [f"K-{index:02d}" for index in range(1, 11)])
        for item in CONFLICT_DISPOSITIONS:
            self.assertTrue(item.disposition)
            self.assertTrue(item.landing)
            self.assertTrue(item.evidence_hint)
        self.assertIn("EXEC_DOMAIN_MISMATCH", CONFLICT_DISPOSITIONS[1].disposition)
        self.assertIn("挂载面裁剪", CONFLICT_DISPOSITIONS[2].disposition)



class AutoExecDomainTest(unittest.TestCase):
    def test_iso10_auto_detects_host_domain(self) -> None:
        from unittest import mock

        with TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            guard = _guard(tmp, denied=["open"])
            with mock.patch("app.runtime.exec_domain.detect_exec_domain", return_value=ExecDomain.HOST_USER):
                with self.assertRaises(ApiError) as raised:
                    guard.self_check()
            self.assertIn("HOST_USER", str(raised.exception))
            self.assertIn("执行域不匹配", str(raised.exception))


if __name__ == "__main__":
    unittest.main()