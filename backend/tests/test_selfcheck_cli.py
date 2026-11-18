from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(TESTS))

from app.selfcheck.context import SelfcheckContext
from support.selfcheck_fixtures import write_repo

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "selfcheck.py"


def _run(*arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(cwd or ROOT),
        timeout=240,
    )


class CliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        fixture = write_repo(self.root)
        self.evidence_id = str(fixture["evidence_id"])
        self.ctx = SelfcheckContext(self.root)

    def test_dry_run_outputs_thirty_items_and_writes_nothing(self) -> None:
        before = self.ctx.tree_digest()
        completed = _run("--dry-run", "--json", "--root", str(self.root))
        self.assertIn(completed.returncode, (2, 3), completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(len(payload["checks"]), 30)
        self.assertEqual(before, self.ctx.tree_digest())
        self.assertFalse((self.root / "docs" / "devlog" / "selfcheck" / "index.json").exists())
        self.assertFalse((self.root / "docs" / "devlog" / "selfcheck" / ".lock").exists())

    def test_scope_d4_exit_code_is_two_even_when_passing(self) -> None:
        completed = _run("--dry-run", "--json", "--scope", "D4", "--root", str(self.root))
        self.assertEqual(completed.returncode, 2, completed.stderr)
        payload = json.loads(completed.stdout)
        in_scope = [item for item in payload["checks"] if item["check_id"].startswith("D4")]
        self.assertTrue(all(item["status"] != "阻塞" for item in in_scope))
        excluded = [item for item in payload["checks"] if not item["check_id"].startswith("D4")]
        self.assertTrue(all(item["status"] == "未验证" for item in excluded))

    def test_full_scope_with_manual_items_returns_three(self) -> None:
        completed = _run("--dry-run", "--json", "--scope", "D4,D5", "--root", str(self.root))
        self.assertEqual(completed.returncode, 3, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["overall"], "未完成")

    def test_invalid_scope_returns_two_without_artifacts(self) -> None:
        completed = _run("--dry-run", "--json", "--scope", "D9", "--root", str(self.root))
        self.assertEqual(completed.returncode, 2)
        self.assertIn("invalid --scope", completed.stderr)
        self.assertFalse((self.root / "docs" / "devlog" / "selfcheck" / "index.json").exists())

    def test_lock_conflict_returns_three(self) -> None:
        lock = self.root / "docs" / "devlog" / "selfcheck" / ".lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "run_id": "SC-TEST-v1",
                    "scope": ["D4"],
                }
            ),
            encoding="utf-8",
        )
        completed = _run("--dry-run", "--json", "--scope", "D4", "--root", str(self.root))
        self.assertEqual(completed.returncode, 3)
        self.assertIn("自检进行中", completed.stderr)

    def test_no_report_writes_archive(self) -> None:
        completed = _run("--no-report", "--scope", "D4", "--root", str(self.root))
        self.assertEqual(completed.returncode, 2, completed.stderr)
        payload = json.loads(completed.stdout)
        run_id = payload["run_id"]
        archive = self.root / "docs" / "devlog" / "selfcheck" / run_id
        self.assertTrue((archive / "report.md").is_file())
        self.assertTrue((archive / "selfcheck.json").is_file())
        index = json.loads(
            (self.root / "docs" / "devlog" / "selfcheck" / "index.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(index["entries"]), 1)
        self.assertTrue((self.root / "docs" / "devlog" / "m13-selfcheck-report.md").is_file())

    def test_json_stdout_is_parseable_and_only_json(self) -> None:
        completed = _run("--dry-run", "--json", "--scope", "D4", "--root", str(self.root))
        payload = json.loads(completed.stdout)
        self.assertIn("fingerprint", payload)

    def test_draft_not_written_in_dry_run(self) -> None:
        _run("--dry-run", "--json", "--scope", "D4", "--root", str(self.root))
        self.assertFalse((self.root / "docs" / "devlog" / "selfcheck-manual-draft.md").exists())


if __name__ == "__main__":
    unittest.main()