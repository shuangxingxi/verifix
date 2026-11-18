from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import ValidationError

from app.api.envelope import ApiError, ErrorCode
from app.realscan.evidence import EvidenceInput, EvidencePackWriter
from app.realscan.models import (
    BoundaryKind,
    Detection,
    EvidencePack,
    IsolationBridgeRecord,
    Judgement,
    ScanScope,
    ScanVerdict,
    VerificationSource,
)
from app.runtime.exec_domain import ExecDomain, detect_exec_domain
from app.tools.redactor import SecretRedactor

ROOT = Path(__file__).resolve().parents[2]


class _LeakStub:
    def __init__(self, hits=None) -> None:
        self.hits = hits or []

    def scan(self, text: str) -> list[str]:
        return list(self.hits)


def _payload(**overrides) -> EvidenceInput:
    base = dict(
        commands=["cd E:/shuangxingxi/ICT_agent && wsl.exe -d Debian -u root -- docker version"],
        runtime_facts={"network_mode": "NONE_LOOPBACK"},
        reuse_conditions={"image_id": "sha256:" + "a" * 64},
        boundary_tags=[BoundaryKind.REAL_CONTAINER],
        verification_source=VerificationSource.REAL_EXECUTION,
        files={"records/verification.json": "{}"},
        raw_output="probe output",
    )
    base.update(overrides)
    return EvidenceInput(**base)


class EvidencePackTest(unittest.TestCase):
    def test_evd01_evidence_ids_are_unique(self) -> None:
        with TemporaryDirectory() as tmp:
            writer = EvidencePackWriter(Path(tmp))
            ids = {writer.new_evidence_id("VER") for _ in range(1000)}
            self.assertEqual(len(ids), 1000)

    def test_evd02_commands_are_mandatory(self) -> None:
        with TemporaryDirectory() as tmp:
            writer = EvidencePackWriter(Path(tmp))
            with self.assertRaises(ApiError) as raised:
                writer.write("VER", _payload(commands=[]))
            self.assertIs(raised.exception.code, ErrorCode.EVIDENCE_INTEGRITY)

    def test_evd03_manifest_is_written_last_and_published_atomically(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            writer = EvidencePackWriter(root)
            pack = writer.write("VER", _payload())
            self.assertFalse(writer.staging_path(pack.evidence_id).exists())
            final = writer.final_path(pack.evidence_id)
            self.assertTrue((final / "manifest.json").is_file())
            self.assertTrue((final / "EVIDENCE.sha256").is_file())
            self.assertTrue((final / "records" / "verification.json").is_file())
            self.assertTrue((root / "INDEX.json").is_file())
            digest_lines = (final / "EVIDENCE.sha256").read_text(encoding="utf-8")
            self.assertIn("manifest.json", digest_lines)

    def test_evd04_verify_detects_digest_consistency(self) -> None:
        with TemporaryDirectory() as tmp:
            writer = EvidencePackWriter(Path(tmp))
            pack = writer.write("SCAN", _payload())
            report = writer.verify(pack.evidence_id)
            self.assertTrue(report.ok)
            target = writer.final_path(pack.evidence_id) / "records" / "verification.json"
            target.write_text("tampered", encoding="utf-8")
            self.assertFalse(writer.verify(pack.evidence_id).ok)

    def test_evd05_path_traversal_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            writer = EvidencePackWriter(Path(tmp))
            with self.assertRaises(ApiError):
                writer.write("VER", _payload(files={"../escape.txt": "x"}))

    def test_evd06_exec_domain_has_three_values_and_is_stable(self) -> None:
        values = {item.value for item in ExecDomain}
        self.assertEqual(values, {"HOST_USER", "RUNTIME_ROOT", "CONTAINER_EXEC"})
        first = detect_exec_domain("wsl")
        for _ in range(10):
            self.assertIs(detect_exec_domain("wsl"), first)
        self.assertIs(detect_exec_domain("wsl"), ExecDomain.RUNTIME_ROOT)

    def test_evd07_answer_keys_are_rejected_by_models(self) -> None:
        with self.assertRaises(ValidationError):
            Detection(
                detection_id="D-1",
                file="app/main.py",
                line=10,
                rule_id="C02",
                defect_class="SQL_INJECTION",
                exec_location="STATIC",
                category="SQL",
            )

    def test_evd08_timestamps_must_be_timezone_aware(self) -> None:
        with self.assertRaises(ValidationError):
            EvidencePack(
                evidence_id="VER-20261114T120000+0800-abcd",
                path="VER-20261114T120000+0800-abcd",
                sha256="a" * 64,
                size_bytes=1,
                commands=["echo"],
                raw_output_digest="b" * 64,
                verification_source=VerificationSource.UNIT_TEST,
                created_at=datetime(2026, 11, 14, 12, 0, 0),
            )
        pack = EvidencePack(
            evidence_id="VER-20261114T120000+0800-abcd",
            path="VER-20261114T120000+0800-abcd",
            sha256="a" * 64,
            size_bytes=1,
            commands=["echo"],
            raw_output_digest="b" * 64,
            verification_source=VerificationSource.UNIT_TEST,
            created_at=datetime(2026, 11, 14, 12, 0, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(len(pack.sha256), 64)

    def test_evd09_evidence_hits_are_rejected_and_staging_is_removed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            writer = EvidencePackWriter(root, scrubber=SecretRedactor())
            with self.assertRaises(ApiError) as raised:
                writer.write("VER", _payload(files={"records/x.json": 'password = "supersecret123"'}))
            self.assertIs(raised.exception.code, ErrorCode.EVIDENCE_INTEGRITY)
            self.assertEqual([item for item in root.iterdir() if item.name.startswith(".staging-")], [])

    def test_evd10_leak_scanner_hits_are_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            writer = EvidencePackWriter(Path(tmp), leak_scanner=_LeakStub(["ground_truth"]))
            with self.assertRaises(ApiError) as raised:
                writer.write("ISO", _payload())
            self.assertIs(raised.exception.code, ErrorCode.EVIDENCE_INTEGRITY)


class ModelGuardTest(unittest.TestCase):
    def test_partial_scope_requires_uncovered_classes(self) -> None:
        with self.assertRaises(ValidationError):
            ScanScope(defect_classes=["C02"], item_count=6, full_count=15)
        scope = ScanScope(defect_classes=["C02"], item_count=6, full_count=15, uncovered_classes=["C01", "C03", "C05"])
        self.assertEqual(scope.item_count, 6)

    def test_isolation_bridge_forbids_expected_in_visible_roots(self) -> None:
        with self.assertRaises(ValidationError):
            IsolationBridgeRecord(
                iso_id="ISO-20261114T120000+0800-abcd",
                exec_identity="uid=10001,gid=10001",
                exec_domain=ExecDomain.CONTAINER_EXEC,
                visible_roots=["/src", "/eval/expected"],
            )

    def test_scan_verdict_established_requires_sandbox_scope(self) -> None:
        with self.assertRaises(ValidationError):
            from app.realscan.models import ScanRecord

            ScanRecord(
                scan_id="SCAN-20261114T120000+0800-abcd",
                target="verifix-target",
                target_version="1.0.0",
                target_view_digest="c" * 64,
                listen_port=8000,
                sandbox_scope=False,
                scope=ScanScope(defect_classes=["C02"], item_count=15, full_count=15),
                scan_verdict=ScanVerdict.ESTABLISHED,
                boundary_summary={"REAL_CONTAINER": 1},
                detections=[Detection(detection_id="D-1", file="a.py", line=1, rule_id="C02", defect_class="SQL_INJECTION", exec_location="STATIC")],
            )


class IsolationVerdictExtensionTest(unittest.TestCase):
    def test_failure_kind_is_classified_but_still_raised(self) -> None:
        from app.eval.isolation import AccessAuditLog, AnswerIsolationGuard
        from app.eval.isolation import PermissionProbe

        class StubProbe(PermissionProbe):
            def __init__(self) -> None:
                pass

            def probe_denied(self):
                return ["open"]

            def cases_readable(self) -> bool:
                return True

        with TemporaryDirectory() as tmp:
            cases = Path(tmp) / "cases"
            expected = Path(tmp) / "expected"
            cases.mkdir()
            expected.mkdir()
            guard = AnswerIsolationGuard(cases, expected, audit=AccessAuditLog(), probe=StubProbe())
            with self.assertRaises(ApiError) as raised:
                guard.self_check(exec_domain=ExecDomain.HOST_USER)
            self.assertIs(raised.exception.code, ErrorCode.EVAL_ISOLATION_UNMET)

    def test_success_on_container_domain_is_publishable(self) -> None:
        from app.eval.isolation import AccessAuditLog, AnswerIsolationGuard
        from app.eval.isolation import PermissionProbe

        class StubProbe(PermissionProbe):
            def __init__(self) -> None:
                pass

            def probe_denied(self):
                return []

            def cases_readable(self) -> bool:
                return True

        with TemporaryDirectory() as tmp:
            cases = Path(tmp) / "cases"
            expected = Path(tmp) / "expected"
            cases.mkdir()
            expected.mkdir()
            guard = AnswerIsolationGuard(cases, expected, audit=AccessAuditLog(), probe=StubProbe())
            verdict = guard.self_check(exec_domain=ExecDomain.CONTAINER_EXEC)
            self.assertTrue(verdict.ok)
            self.assertTrue(verdict.publishable)
            host = guard.self_check(exec_domain=ExecDomain.HOST_USER)
            self.assertFalse(host.publishable)


class EvidenceHardeningTest(unittest.TestCase):
    def test_commands_file_is_copyable(self) -> None:
        with TemporaryDirectory() as tmp:
            writer = EvidencePackWriter(Path(tmp))
            pack = writer.write("VER", _payload())
            text = (writer.final_path(pack.evidence_id) / "commands.txt").read_text(encoding="utf-8")
            self.assertIn("# cwd=", text)
            self.assertIn("docker version", text)
            self.assertNotIn("<", text.replace("{{", "").replace("}}", ""))

    def test_placeholder_and_secret_commands_are_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            writer = EvidencePackWriter(Path(tmp))
            for command in ("docker run <image>", "docker run ...", 'docker run --password abc image'):
                with self.assertRaises(ApiError) as raised:
                    writer.write("VER", _payload(commands=[command]))
                self.assertIs(raised.exception.code, ErrorCode.EVIDENCE_INTEGRITY)

    def test_idempotent_write_returns_existing_pack(self) -> None:
        with TemporaryDirectory() as tmp:
            writer = EvidencePackWriter(Path(tmp))
            evidence_id = "VER-20261114T120000+0800-abcd"
            first = writer.write("VER", _payload(), evidence_id=evidence_id)
            second = writer.write("VER", _payload(), evidence_id=evidence_id)
            self.assertEqual(first.evidence_id, second.evidence_id)
            self.assertEqual(first.sha256, second.sha256)
            self.assertEqual([item.name for item in Path(tmp).iterdir() if item.is_dir()], [evidence_id])

    def test_timestamp_backwards_is_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            writer = EvidencePackWriter(root)
            pack = writer.write("VER", _payload())
            index_path = root / "INDEX.json"
            payload = json.loads(index_path.read_text(encoding="utf-8"))
            payload["packs"][0]["created_at"] = "2999-01-01T00:00:00+00:00"
            index_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ApiError) as raised:
                writer.write("VER", _payload())
            self.assertIs(raised.exception.code, ErrorCode.EVIDENCE_INTEGRITY)
            self.assertEqual(len([item for item in root.iterdir() if item.name.startswith(".staging-")]), 0)

    def test_history_digests_are_intact(self) -> None:
        from app.realscan.evidence import HISTORY_BASELINE, verify_history_digests

        self.assertEqual(len(HISTORY_BASELINE), 9)
        self.assertEqual(verify_history_digests(ROOT), [])

    def test_reuse_drift_detection(self) -> None:
        from app.realscan.evidence import validate_reuse_conditions, verify_reuse

        recorded = {
            "image_id": "sha256:" + "a" * 64,
            "exec_domain": "RUNTIME_ROOT",
            "network_mode": "NONE_LOOPBACK",
            "dependency_versions": {"python": "3.12", "flask": "3.1.3", "docker": "26.1.5", "cgroup": "2"},
        }
        self.assertEqual(validate_reuse_conditions(recorded), [])
        self.assertEqual(verify_reuse(recorded, dict(recorded)), [])
        self.assertEqual(len(validate_reuse_conditions({"image_id": "x"})), 3)
        current = dict(recorded)
        current["image_id"] = "sha256:" + "b" * 64
        self.assertTrue(verify_reuse(recorded, current))

    def test_scrubber_report_counts_are_zero(self) -> None:
        with TemporaryDirectory() as tmp:
            writer = EvidencePackWriter(Path(tmp))
            pack = writer.write("ISO", _payload())
            report = json.loads((writer.final_path(pack.evidence_id) / "scrubber_report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["credential_hits"], 0)
            self.assertEqual(report["answer_hits"], 0)
            manifest = json.loads((writer.final_path(pack.evidence_id) / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn("evidence_ref", manifest)
            self.assertIn("verification_source", manifest)
            self.assertEqual(len(manifest["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()