from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.envelope import ApiError, ErrorCode
from app.config import load_config
from app.eval.leak_scan import LeakScanner
from app.eval.runner import EvalRun, EvalRunner

ROOT = Path(__file__).resolve().parents[2]


class LeakScannerTest(unittest.TestCase):
    def test_detects_field_token(self) -> None:
        report = LeakScanner().scan_text('{"case_id": "EVAL-0001", "verdict_agrees": true}')
        self.assertGreater(report.hits, 0)
        self.assertIn("verdict_agrees", report.hit_fields)

    def test_detects_value_token(self) -> None:
        report = LeakScanner().scan_text("category=POSITIVE")
        self.assertGreater(report.hits, 0)
        self.assertIn("POSITIVE", report.hit_fields)

    def test_clean_observation_is_zero(self) -> None:
        payload = {
            "case_id": "EVAL-0001",
            "detected": True,
            "verdict": "REACHABLE",
            "repro_status": "PROVEN",
            "patch_status": "PATCHED",
            "binding_digest": "a" * 64,
        }
        self.assertEqual(LeakScanner().scan_text(json.dumps(payload)).hits, 0)

    def test_does_not_store_hit_content(self) -> None:
        report = LeakScanner().scan_text("proof_post_patch=PASS")
        self.assertTrue(report.hit_fields)
        self.assertNotIn("PASS", report.artifacts)


class QuarantineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.run_dir = Path(self.tmp.name)
        self.config = load_config()
        self.runner = EvalRunner(self.config, ROOT / "verifix-target", self.run_dir)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_leak_marks_run_quarantined(self) -> None:
        run = EvalRun(
            eval_run_id="EVALRUN-LEAK",
            set_version="1.0.0",
            total=1,
            cases_digest="a" * 64,
            expected_digest="b" * 64,
            binding_digest="c" * 64,
        )
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "EVALRUN-LEAK.json").write_text(
            json.dumps({"eval_run_id": "EVALRUN-LEAK", "verdict_agrees": True}), encoding="utf-8"
        )
        with self.assertRaises(ApiError) as raised:
            self.runner._leak_check(run)
        self.assertIs(raised.exception.code, ErrorCode.EVAL_LEAK_DETECTED)
        self.assertEqual(run.status, "QUARANTINED")

    def test_quarantined_run_cannot_continue(self) -> None:
        run = EvalRun(
            eval_run_id="EVALRUN-Q",
            set_version="1.0.0",
            total=1,
            cases_digest="a" * 64,
            expected_digest="b" * 64,
            binding_digest="c" * 64,
            status="QUARANTINED",
        )
        with self.assertRaises(ApiError):
            self.runner._ensure_runnable(run)


class CasesDirectoryScanTest(unittest.TestCase):
    def test_cases_and_manifest_are_clean(self) -> None:
        scanner = LeakScanner()
        report = scanner.scan_directory(ROOT / "eval" / "cases")
        self.assertEqual(report.hits, 0, report.hit_fields)


if __name__ == "__main__":
    unittest.main()