from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.envelope import ApiError, ErrorCode
from app.selfcheck.context import SelfcheckContext, mask
from app.selfcheck.probes import EnvMode, SubprocessProbe


class ProbeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.ctx = SelfcheckContext(self.root)
        self.probe = SubprocessProbe(self.ctx)

    def test_exit_code_and_stdout_captured(self) -> None:
        output = self.probe.run(
            [sys.executable, "-c", "print('hello'); raise SystemExit(3)"],
            timeout=60,
            cwd=self.root,
        )
        self.assertEqual(output.exit_code, 3)
        self.assertIn("hello", output.stdout_tail)
        self.assertFalse(output.timed_out)
        self.assertFalse(output.unavailable)

    def test_output_truncated_with_marker(self) -> None:
        output = self.probe.run(
            [sys.executable, "-c", "print('x' * 5000)"],
            timeout=60,
            cwd=self.root,
            summary_limit=100,
        )
        self.assertIn("truncated", output.stdout_tail)
        self.assertLess(len(output.stdout_tail), 200)

    def test_stderr_has_independent_limit(self) -> None:
        output = self.probe.run(
            [sys.executable, "-c", "import sys; sys.stderr.write('y' * 5000)"],
            timeout=60,
            cwd=self.root,
        )
        self.assertIn("truncated", output.stderr_tail)

    def test_clean_mode_drops_python_env(self) -> None:
        with mock.patch.dict(os.environ, {"PYTHONUTF8": "1", "PYTHONPATH": "leak"}, clear=False):
            output = self.probe.run(
                [
                    sys.executable,
                    "-c",
                    "import os; print(os.environ.get('PYTHONUTF8'), os.environ.get('PYTHONPATH'))",
                ],
                timeout=60,
                cwd=self.root,
                env_mode=EnvMode.CLEAN,
            )
        self.assertEqual(output.exit_code, 0)
        self.assertIn("None None", output.stdout_tail)

    def test_timeout_marks_and_terminates(self) -> None:
        output = self.probe.run(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=0.5,
            cwd=self.root,
        )
        self.assertTrue(output.timed_out)
        self.assertLess(output.duration_seconds, 20)

    def test_missing_executable_is_unavailable(self) -> None:
        output = self.probe.run(
            ["definitely-not-a-real-binary-xyz"],
            timeout=5,
            cwd=self.root,
        )
        self.assertTrue(output.unavailable)
        self.assertIsNone(output.exit_code)

    def test_cwd_outside_roots_rejected(self) -> None:
        with self.assertRaises(ApiError) as caught:
            self.probe.run(
                [sys.executable, "-c", "print('x')"],
                timeout=5,
                cwd=self.root.parent,
            )
        self.assertIs(caught.exception.code, ErrorCode.SELFCHECK_READONLY_VIOLATION)

    def test_mask_replaces_credentials(self) -> None:
        text = "password=supersecretvalue"
        masked = mask(text)
        self.assertNotIn("supersecretvalue", masked)
        self.assertIn("***MASKED***", masked)
        self.assertEqual(mask("plain text"), "plain text")


if __name__ == "__main__":
    unittest.main()