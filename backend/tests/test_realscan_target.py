from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.realscan.models import ImageResolution
from app.realscan.policy import PolicyFile
from app.realscan.runtime import CommandResult
from app.realscan.target import (
    EXCLUDED_PATHS,
    LAUNCH_FAILURE_REASONS,
    TargetLauncher,
    TargetLaunchError,
    TargetViewBuilder,
)
from app.realscan.worker import build_worker_bundle, parse_events, worker_payload

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "verifix-target"
POLICY = ROOT / "sandbox" / "spec.json"

IMAGE = ImageResolution(
    policy_image="verifix-target:1.0.0",
    resolved_image="realscan-probe:local",
    image_id="sha256:" + "d" * 64,
    repo_digests=[],
    local_build=True,
    alias_used=True,
    source="LOCAL_ALIAS",
)


class FakeTransport:
    name = "fake"
    exec_domain = __import__("app.runtime.exec_domain", fromlist=["ExecDomain"]).ExecDomain.RUNTIME_ROOT
    privilege_route = "WSL_DISTRO_ROOT"

    def __init__(self, stdout: str, timed_out: bool = False) -> None:
        self.stdout = stdout
        self.timed_out = timed_out
        self.calls: list[tuple[str, ...]] = []
        self.stdin_seen: str | None = None

    def run(self, argv, timeout_seconds, cwd=None, stdin_text=None) -> CommandResult:
        self.calls.append(tuple(str(item) for item in argv))
        self.stdin_seen = stdin_text
        return CommandResult(tuple(str(item) for item in argv), 0, self.stdout, "", 1, self.timed_out)


class TargetViewTest(unittest.TestCase):
    def test_tgt01_view_excludes_truth_tests_tools_and_git(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            view = TargetViewBuilder().build(TARGET, Path(tmp_raw))
            view_root = Path(view.view_root)
            self.assertEqual(sorted(view.included_paths), ["app/__init__.py", "app/config.py", "app/main.py", "init_db.py", "requirements.txt"])
            self.assertFalse((view_root / "ground_truth.json").exists())
            self.assertFalse((view_root / "tests").exists())
            self.assertFalse((view_root / "tools").exists())
            self.assertFalse(any(item.name == "__pycache__" for item in view_root.rglob("*")))
            self.assertFalse(view.truth_present)
            self.assertEqual(len(view.view_digest), 64)
            self.assertEqual(set(EXCLUDED_PATHS), {"ground_truth.json", "tests", "tools", "__pycache__", ".git", "target.db"})
            again = TargetViewBuilder().build(TARGET, Path(tmp_raw))
            self.assertEqual(again.view_digest, view.view_digest)


class TargetLauncherTest(unittest.TestCase):
    def _launcher(self, tmp: Path, transport: FakeTransport) -> TargetLauncher:
        view = TargetViewBuilder().build(TARGET, tmp)
        return TargetLauncher(transport, view, IMAGE, PolicyFile.load(POLICY))

    def test_tgt02_dynamic_port_is_recorded(self) -> None:
        ready = {"event": "target_ready", "ok": True, "port": 54321, "port_source": "DYNAMIC", "db_path": "/tmp/target.db", "health_elapsed_ms": 120}
        summary = {"event": "summary", "detections": 15, "dynamic": 10, "truth_reads": 0}
        stdout = json.dumps(ready) + "\n" + json.dumps(summary) + "\n"
        with TemporaryDirectory() as tmp_raw:
            transport = FakeTransport(stdout)
            runtime = self._launcher(Path(tmp_raw), transport).launch("SCAN-20261114T120000+0800-abcd", worker_payload())
            self.assertEqual(runtime.listen_port, 54321)
            self.assertEqual(runtime.port_source, "DYNAMIC")
            self.assertTrue(runtime.health_ok)
            self.assertEqual(runtime.truth_reads, 0)
            joined = " ".join(transport.calls[0])
            self.assertIn("docker run -i", joined)
            self.assertIn("--network=none", joined)
            self.assertIn("--read-only", joined)
            self.assertIn("--volume=", joined)
            self.assertIn(":/src:ro", joined)
            self.assertIsNotNone(transport.stdin_seen)
            self.assertIn("VF_WORKER_PAYLOAD", transport.stdin_seen or "")

    def test_tgt03_health_timeout_raises(self) -> None:
        ready = {"event": "target_ready", "ok": False, "reason": "HEALTH_TIMEOUT"}
        with TemporaryDirectory() as tmp_raw:
            launcher = self._launcher(Path(tmp_raw), FakeTransport(json.dumps(ready) + "\n"))
            with self.assertRaises(TargetLaunchError) as raised:
                launcher.launch("SCAN-20261114T120000+0800-abcd", worker_payload())
            self.assertEqual(raised.exception.reason, "HEALTH_TIMEOUT")

    def test_tgt04_db_unwritable_is_reported(self) -> None:
        ready = {"event": "target_ready", "ok": False, "reason": "DB_NOT_WRITABLE", "detail": "PermissionError"}
        with TemporaryDirectory() as tmp_raw:
            launcher = self._launcher(Path(tmp_raw), FakeTransport(json.dumps(ready) + "\n"))
            with self.assertRaises(TargetLaunchError) as raised:
                launcher.launch("SCAN-20261114T120000+0800-abcd", worker_payload())
            self.assertEqual(raised.exception.reason, "DB_NOT_WRITABLE")

    def test_tgt05_missing_image_blocks_launch(self) -> None:
        missing = ImageResolution(policy_image="verifix-target:1.0.0", source="MISSING")
        with TemporaryDirectory() as tmp_raw:
            view = TargetViewBuilder().build(TARGET, Path(tmp_raw))
            launcher = TargetLauncher(FakeTransport(""), view, missing, PolicyFile.load(POLICY))
            with self.assertRaises(TargetLaunchError) as raised:
                launcher.prepare()
            self.assertEqual(raised.exception.reason, "IMAGE_UNAVAILABLE")

    def test_tgt06_worker_bundle_is_self_contained(self) -> None:
        bundle = build_worker_bundle(worker_payload())
        self.assertIn("def scan_tree_safe", bundle)
        self.assertIn("def discover_routes", bundle)
        self.assertIn("def run_plan", bundle)
        self.assertNotIn("from app.realscan", bundle)
        self.assertNotIn("from app.eval", bundle)
        self.assertNotIn("import app.", bundle)
        events = parse_events('{"event":"detection","line":1}\nnot json\n{"event":"summary"}\n')
        self.assertEqual(len(events), 2)

    def test_tgt07_failure_reasons_are_enumerated(self) -> None:
        self.assertEqual(
            set(LAUNCH_FAILURE_REASONS),
            {"MISSING_DEPENDENCY", "PORT_UNAVAILABLE", "DB_NOT_WRITABLE", "HEALTH_TIMEOUT", "IMAGE_UNAVAILABLE"},
        )
        with self.assertRaises(ValueError):
            TargetLaunchError("UNKNOWN")


if __name__ == "__main__":
    unittest.main()