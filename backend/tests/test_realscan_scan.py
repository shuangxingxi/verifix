from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import RealscanConfig
from app.realscan.capability import EnvironmentCapabilityProbe
from app.realscan.dynamic import discover_routes
from app.realscan.models import ScanVerdict
from app.realscan.pipeline import RealscanPipeline
from app.realscan.policy import ImageResolver
from app.realscan.reconcile import TruthReconciler
from app.realscan.rules import ADVISORIES
from app.realscan.runtime import CommandResult
from app.realscan.scan import (
    CLOUD_TEXT,
    FULL_CLASSES,
    RealScanOrchestrator,
    build_scope,
    check_locations,
    compare_runs,
    scope_text,
    to_detections,
    to_dynamic_checks,
)
from app.realscan.scanner import scan_tree
from app.realscan.target import TargetRuntime, TargetViewBuilder
from app.runtime.exec_domain import ExecDomain

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "verifix-target"
TRUTH = TARGET / "ground_truth.json"


def _result(argv, stdout="", exit_code=0, timed_out=False) -> CommandResult:
    return CommandResult(tuple(str(item) for item in argv), exit_code, stdout, "", 1, timed_out)


class ScanTransport:
    name = "fake"
    exec_domain = ExecDomain.RUNTIME_ROOT
    privilege_route = "WSL_DISTRO_ROOT"

    def run(self, argv, timeout_seconds, cwd=None, stdin_text=None) -> CommandResult:
        joined = " ".join(str(item) for item in argv)
        if "{{json .HostConfig}}" in joined:
            return _result(argv, stdout="{}")
        if "Client.Version" in joined or "Server.Version" in joined:
            return _result(argv, stdout="26.1.5\n")
        if "docker ps" in joined:
            return _result(argv, stdout="")
        if "docker info" in joined:
            return _result(argv, stdout="overlay2|2\n")
        if "image inspect" in joined:
            return _result(argv, stdout="sha256:" + "e" * 64 + "|[]|131\n")
        if "docker run" in joined:
            return _result(argv, stdout="LOOPBACK_OK\n")
        return _result(argv, stdout="")


class ScanLauncher:
    def __init__(self, view, health_ok: bool = True, diff: bool = True) -> None:
        self.view = view
        self.health_ok = health_ok
        self.diff = diff

    def launch(self, scan_id: str, payload: dict, timeout_seconds: float = 180.0) -> TargetRuntime:
        raw = scan_tree(Path(self.view.view_root), ADVISORIES)
        routes = discover_routes(self.view.view_root)
        dynamic = [
            {
                "endpoint": route["endpoint"],
                "method": route["method"],
                "kind": route["kind"],
                "file": route["file"],
                "line": route["line"],
                "normal_digest": "a" * 64,
                "injected_digest": "b" * 64,
                "behavior_diff": self.diff,
                "conclusion": "REPRODUCIBLE" if self.diff else "NOT_REPRODUCIBLE",
                "duration_ms": 1,
                "retries": 0,
            }
            for route in routes
        ]
        return TargetRuntime(
            container_name=f"vf-scan-{scan_id}",
            listen_port=54321 if self.health_ok else 0,
            port_source="DYNAMIC",
            health_ok=self.health_ok,
            health_elapsed_ms=120,
            db_path="/tmp/target.db",
            stdout=json.dumps({"event": "summary", "truth_reads": 0}) + "\n",
            stderr="",
            exit_code=0,
            timed_out=False,
            detections=raw,
            dynamic_checks=dynamic,
            truth_reads=0,
        )


def _orchestrator(tmp: Path, launcher: ScanLauncher | None = None, health_ok: bool = True, diff: bool = True):
    config = RealscanConfig(
        target_root=str(TARGET),
        evidence_root=str(tmp / "evidence"),
        runtime_transport="host",
    )
    transport = ScanTransport()
    resolver = ImageResolver(transport, ["verifix-target:1.0.0", "realscan-probe:local"])
    probe = EnvironmentCapabilityProbe(
        transport,
        resolver,
        budget_seconds=10.0,
        required_images=["verifix-target:1.0.0"],
        egress_checker=lambda _timeout: "BLOCKED",
    )
    pipeline = RealscanPipeline(config, transport=transport, resolver=resolver, probe=probe)
    factory = lambda view, image: launcher or ScanLauncher(view, health_ok=health_ok, diff=diff)
    return RealScanOrchestrator(
        config,
        pipeline=pipeline,
        work_root=tmp / "work",
        launcher_factory=factory,
        truth_path=TRUTH,
    )


class ScopeTest(unittest.TestCase):
    def test_scn01_full_and_subset_scopes(self) -> None:
        full = build_scope("full")
        self.assertEqual(full.item_count, 15)
        self.assertEqual(full.uncovered_classes, [])
        self.assertEqual(scope_text(full), "15/15")
        subset = build_scope("sql-cmd")
        self.assertEqual(subset.item_count, 10)
        self.assertEqual(subset.uncovered_classes, ["C01", "C05"])
        self.assertEqual(scope_text(subset), "10/15，未覆盖 C01、C05")
        self.assertEqual(set(FULL_CLASSES), {"C01", "C02", "C03", "C05"})


class DetectionTest(unittest.TestCase):
    def test_scn02_location_alignment_is_zero_offset(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            view = TargetViewBuilder().build(TARGET, Path(tmp_raw))
            detections = to_detections(scan_tree(Path(view.view_root), ADVISORIES))
            self.assertEqual(len(detections), 15)
            self.assertEqual(check_locations(Path(view.view_root), detections), [])

    def test_scn03_dynamic_denominator_is_ten(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            view = TargetViewBuilder().build(TARGET, Path(tmp_raw))
            detections = to_detections(scan_tree(Path(view.view_root), ADVISORIES))
            routes = discover_routes(view.view_root)
            self.assertEqual(len(routes), 10)
            checks = to_dynamic_checks(
                [
                    {
                        "endpoint": route["endpoint"],
                        "method": route["method"],
                        "file": route["file"],
                        "line": route["line"],
                        "behavior_diff": True,
                        "conclusion": "REPRODUCIBLE",
                    }
                    for route in routes
                ],
                detections,
            )
            self.assertEqual(len(checks), 10)
            self.assertTrue(all(check.detection_id.startswith("D-") for check in checks))

    def test_scn04_truth_independence(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            first = TargetViewBuilder().build(TARGET, Path(tmp_raw) / "a")
            second = TargetViewBuilder().build(TARGET, Path(tmp_raw) / "b")
            self.assertFalse((Path(first.view_root) / "ground_truth.json").exists())
            left = {(item["file"], item["line"], item["rule_id"], item["defect_class"]) for item in scan_tree(Path(first.view_root), ADVISORIES)}
            right = {(item["file"], item["line"], item["rule_id"], item["defect_class"]) for item in scan_tree(Path(second.view_root), ADVISORIES)}
            self.assertEqual(left, right)
            self.assertEqual(len(left), 15)


class ReconcileTest(unittest.TestCase):
    def test_scn05_truth_reconcile_reads_once(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            view = TargetViewBuilder().build(TARGET, Path(tmp_raw))
            detections = to_detections(scan_tree(Path(view.view_root), ADVISORIES))
            record = TruthReconciler(TRUTH).reconcile("SCAN-20261114T120000+0800-abcd", detections, "1.0.0")
            self.assertEqual(record.truth_read_count, 1)
            self.assertEqual(record.read_phase, "POST_SCAN")
            self.assertEqual(record.matched, 15)
            self.assertEqual(record.missing, [])
            self.assertEqual(record.extra, [])
            self.assertEqual(record.coverage, "15/15")

    def test_scn05b_version_mismatch_is_rejected(self) -> None:
        from app.realscan.reconcile import ReconcileError

        with TemporaryDirectory() as tmp_raw:
            view = TargetViewBuilder().build(TARGET, Path(tmp_raw))
            detections = to_detections(scan_tree(Path(view.view_root), ADVISORIES))
            with self.assertRaises(ReconcileError):
                TruthReconciler(TRUTH).reconcile("SCAN-20261114T120000+0800-abcd", detections, "9.9.9")


class OrchestratorTest(unittest.TestCase):
    def test_scn06_stub_isolation_and_boundaries(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            record = _orchestrator(tmp).run("SCAN-20261114T120000+0800-abcd")
            self.assertEqual(record.stub_count, 10)
            self.assertEqual(record.boundary_summary["RECORDED_STUB"], 10)
            self.assertGreaterEqual(record.boundary_summary["REAL_CONTAINER"], 15)
            self.assertEqual(record.boundary_summary["CLOUD_CREDENTIAL_MISSING"], 1)
            self.assertEqual(record.boundary_summary["REAL_LOCAL"], 0)
            self.assertTrue(all(item.source_kind.value == "REAL_CONTAINER" for item in record.detections))
            self.assertEqual(record.scan_phase_truth_reads, 0)

    def test_scn07_four_conditions_gate_verdict(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            healthy = _orchestrator(tmp).run("SCAN-20261114T120000+0800-abcd")
            self.assertIs(healthy.scan_verdict, ScanVerdict.ESTABLISHED)
            self.assertEqual(healthy.verdict_missing, [])
            broken = _orchestrator(tmp, health_ok=False).run("SCAN-20261114T120000+0800-abce")
            self.assertIs(broken.scan_verdict, ScanVerdict.NOT_ESTABLISHED)
            self.assertIn("target_responded", broken.verdict_missing)
            no_diff = _orchestrator(tmp, diff=False).run("SCAN-20261114T120000+0800-abcf")
            self.assertIn("behavior_diff_reproducible", no_diff.verdict_missing)

    def test_scn08_repeat_runs_are_isomorphic(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            tmp = Path(tmp_raw)
            orchestrator = _orchestrator(tmp)
            first = orchestrator.run("SCAN-20261114T120000+0800-abcd")
            second = orchestrator.run("SCAN-20261114T120000+0800-abce")
            self.assertEqual(compare_runs(first, second), [])
            trimmed = second.model_copy(update={"detections": second.detections[:-1]})
            self.assertTrue(compare_runs(first, trimmed))

    def test_scn09_cloud_placeholder(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            record = _orchestrator(Path(tmp_raw)).run("SCAN-20261114T120000+0800-abcd")
            self.assertEqual(record.cloud_section, CLOUD_TEXT)
            dumped = json.dumps(record.model_dump(mode="json"), ensure_ascii=False)
            self.assertNotIn("云端通过", dumped)
            self.assertNotIn("云端已完成", dumped)

    def test_scn10_host_fallback_is_real_local(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            record = _orchestrator(Path(tmp_raw)).run("SCAN-20261114T120000+0800-abcd", exec_mode="HOST")
            self.assertFalse(record.sandbox_scope)
            self.assertIs(record.scan_verdict, ScanVerdict.NOT_ESTABLISHED)
            self.assertEqual(record.boundary_summary["REAL_CONTAINER"], 0)
            self.assertEqual(record.boundary_summary["REAL_LOCAL"], len(record.detections))
            self.assertIn("sandbox_scope", record.verdict_missing)

    def test_scn11_adopted_defaults_are_recorded(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            record = _orchestrator(Path(tmp_raw)).run("SCAN-20261114T120000+0800-abcd")
            self.assertEqual(len(record.adopted_defaults), 16)
            self.assertTrue(all(item.pending for item in record.adopted_defaults))

    def test_scn12_interruption_keeps_completed_items(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            record = _orchestrator(Path(tmp_raw)).run("SCAN-20261114T120000+0800-abcd", interrupted_after=8)
            self.assertIs(record.scan_verdict, ScanVerdict.UNVERIFIED)
            self.assertEqual(record.completed_count, 8)
            self.assertEqual(record.unverified_count, 7)
            self.assertEqual(len(record.detections), 8)


if __name__ == "__main__":
    unittest.main()