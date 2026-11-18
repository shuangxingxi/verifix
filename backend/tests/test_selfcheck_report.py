from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.selfcheck.context import SelfcheckContext
from app.selfcheck.models import (
    CheckResult,
    Dimension,
    JudgmentMode,
    SelfcheckResult,
    Status,
    ThreeQuestion,
    summarize_dimensions,
)
from app.selfcheck.report import (
    SUMMARY_HEADING,
    ReportWriter,
    render_markdown,
    to_json,
    verify_report,
)


def _result() -> SelfcheckResult:
    checks = [
        CheckResult(
            check_id=f"D1-{index}",
            dimension=Dimension.REPRODUCIBLE,
            mode=JudgmentMode.AUTO,
            question=ThreeQuestion.REPRODUCE,
            status=Status.PASS,
            command="python scripts/smoke_m0.py",
            output_summary="通过",
        )
        for index in range(1, 7)
    ]
    checks.append(
        CheckResult(
            check_id="D2-1",
            dimension=Dimension.CAPABILITY,
            mode=JudgmentMode.MANUAL,
            question=ThreeQuestion.REAL,
            status=Status.MANUAL_PENDING,
        )
    )
    return SelfcheckResult(
        fingerprint="a" * 64,
        generated_at="2026-11-15T14:00:00+08:00",
        scope=["D1", "D2", "D3", "D4", "D5"],
        overall="未完成",
        exit_code=3,
        checks=checks,
        dimensions=summarize_dimensions(checks),
        fix_priority=["[D2-1] 待人工填写"],
    )


class ReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "docs" / "devlog").mkdir(parents=True)
        self.ctx = SelfcheckContext(self.root)
        self.writer = ReportWriter(self.ctx)

    def test_json_fields_present_and_digest_roundtrip(self) -> None:
        result = _result()
        payload = to_json(result)
        for key in (
            "format_version",
            "definition_version",
            "run_id",
            "fingerprint",
            "generated_at",
            "scope",
            "baseline_id",
            "overall",
            "exit_code",
            "readonly_ok",
            "checks",
            "dimensions",
            "claims",
            "evidence",
            "consistency",
            "delivery",
            "weakest_link",
            "top_questions",
            "fix_priority",
            "self_digest",
        ):
            self.assertIn(key, payload)
        self.assertIsNone(payload["baseline_id"])
        self.assertEqual(len(payload["self_digest"]), 64)

    def test_markdown_has_thirteen_sections_in_order(self) -> None:
        markdown = render_markdown(_result(), self.ctx)
        positions = [markdown.index(f"## {index}.") for index in range(1, 13)]
        self.assertEqual(positions, sorted(positions))
        self.assertIn(SUMMARY_HEADING, markdown)
        self.assertIn("- sha256：", markdown)

    def test_write_creates_archive_entry_and_digest(self) -> None:
        outcome = self.writer.write(_result())
        archive = Path(outcome.archive_dir)
        self.assertTrue((archive / "report.md").is_file())
        self.assertTrue((archive / "selfcheck.json").is_file())
        self.assertTrue(self.ctx.entry_report.is_file())
        self.assertTrue(self.ctx.entry_json.is_file())
        index = json.loads((self.ctx.output_dir / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(len(index["entries"]), 1)
        self.assertEqual(index["entries"][0]["run_id"], outcome.run_id)
        self.assertTrue(verify_report(archive / "report.md"))
        self.assertTrue(verify_report(archive / "selfcheck.json"))
        self.assertTrue(verify_report(self.ctx.entry_report))
        self.assertTrue(verify_report(self.ctx.entry_json))

    def test_second_run_increments_version_and_keeps_history(self) -> None:
        first = self.writer.write(_result())
        first_report = (Path(first.archive_dir) / "report.md").read_bytes()
        first_payload = (Path(first.archive_dir) / "selfcheck.json").read_bytes()
        second = self.writer.write(_result())
        self.assertTrue(second.run_id.endswith("-v2"))
        self.assertEqual((Path(first.archive_dir) / "report.md").read_bytes(), first_report)
        self.assertEqual((Path(first.archive_dir) / "selfcheck.json").read_bytes(), first_payload)
        index = json.loads((self.ctx.output_dir / "index.json").read_text(encoding="utf-8"))
        self.assertEqual([item["run_id"] for item in index["entries"]], [first.run_id, second.run_id])
        entry = self.ctx.entry_report.read_text(encoding="utf-8")
        self.assertIn(f"<!-- archive: {second.run_id} -->", entry)

    def test_repair_index_is_idempotent(self) -> None:
        self.writer.write(_result())
        self.assertEqual(self.writer.repair_index(), 0)
        index = json.loads((self.ctx.output_dir / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(len(index["entries"]), 1)

    def test_repair_index_recovers_missing_entry(self) -> None:
        outcome = self.writer.write(_result())
        index_path = self.ctx.output_dir / "index.json"
        index_path.write_text(json.dumps({"entries": []}), encoding="utf-8")
        added = self.writer.repair_index()
        self.assertEqual(added, 1)
        index = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertEqual(index["entries"][0]["run_id"], outcome.run_id)

    def test_report_contains_no_absolute_user_path(self) -> None:
        markdown = render_markdown(_result(), self.ctx)
        self.assertNotIn(str(self.root), markdown)
        self.assertNotIn("shuangxingxi", markdown)

    def test_vf7013_on_unwritable_output(self) -> None:
        from app.api.envelope import ApiError, ErrorCode

        blocker = self.root / "docs" / "devlog" / "selfcheck"
        blocker.parent.mkdir(parents=True, exist_ok=True)
        blocker.write_text("not a directory", encoding="utf-8")
        with self.assertRaises(ApiError) as caught:
            self.writer.write(_result())
        self.assertIs(caught.exception.code, ErrorCode.SELFCHECK_REPORT_WRITE_FAILED)


if __name__ == "__main__":
    unittest.main()