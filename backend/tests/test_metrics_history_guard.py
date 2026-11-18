from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.envelope import ApiError, ErrorCode
from app.metrics.history_guard import HistoryDigestGuard

ROOT = Path(__file__).resolve().parents[2]


class HistoryDigestGuardTest(unittest.TestCase):
    def test_unchanged_report_passes(self) -> None:
        guard = HistoryDigestGuard(ROOT / "docs" / "devlog" / "m5-eval-report.md")
        self.assertEqual(guard.verify(), "931d20442673b0922a32cfb42de1dcc9996925836607f6ddedbc5e8b1f165502")

    def test_single_character_change_blocks(self) -> None:
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "m5-eval-report.md"
            target.write_text("baseline content", encoding="utf-8")
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            guard = HistoryDigestGuard(
                target,
                baseline=f"{target}={digest}",
                evidence_dir=Path(tmp) / "evidence",
            )
            self.assertEqual(guard.verify(), digest)
            target.write_text("baseline content ", encoding="utf-8")
            with self.assertRaises(ApiError) as raised:
                guard.verify()
            self.assertIs(raised.exception.code, ErrorCode.HISTORY_TAMPERED)

    def test_baseline_record_is_not_rewritten(self) -> None:
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "report.md"
            target.write_text("content", encoding="utf-8")
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            evidence = Path(tmp) / "evidence"
            guard = HistoryDigestGuard(target, baseline=f"{target}={digest}", evidence_dir=evidence)
            guard.verify()
            baseline_file = evidence / "history-baseline.json"
            before = baseline_file.read_text(encoding="utf-8")
            guard.verify()
            self.assertEqual(baseline_file.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()