from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_permissions.py"


def _run(*extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *extra],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(ROOT),
        timeout=120,
        check=False,
    )


class PermissionBaselineTest(unittest.TestCase):
    def test_repository_passes_baseline(self) -> None:
        result = _run()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("结论：通过", result.stdout)
        self.assertIn("main 禁写", result.stdout)

    def test_plaintext_secret_in_extra_root_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sample = Path(tmp) / "bad.py"
            sample.write_text('SECRET_KEY = "vf-target-secret-9f3a"\n', encoding="utf-8")
            result = _run("--scan-root", tmp)
            self.assertEqual(result.returncode, 2)
            self.assertIn("明文凭据扫描", result.stdout)
            self.assertIn("bad.py", result.stdout)
            self.assertIn("secret_key_assignment", result.stdout)

    def test_json_output_has_three_checks(self) -> None:
        result = _run("--json")
        import json

        payload = json.loads(result.stdout)
        self.assertEqual(set(payload), {"branch_guard", "secret_scan", "env_example", "blocking_total", "passed"})
        self.assertTrue(payload["branch_guard"]["ok"])

    def test_env_example_is_present(self) -> None:
        self.assertTrue((ROOT / ".env.example").is_file())


if __name__ == "__main__":
    unittest.main()