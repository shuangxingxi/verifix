from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(TESTS))

from app.api.envelope import ApiError, ErrorCode
from app.selfcheck.context import SelfcheckContext
from app.selfcheck.manual import ensure_manual_template, load_manual_claims, render_draft, parse_manual_text
from support.selfcheck_fixtures import MANUAL, write_repo


class ManualTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        write_repo(self.root)

    def test_parse_confirmed_and_pending(self) -> None:
        records = parse_manual_text(MANUAL)
        self.assertEqual(len(records), 2)
        confirmed = [item for item in records if item.confirmed is True]
        pending = [item for item in records if item.confirmed is not True]
        self.assertEqual(len(confirmed), 1)
        self.assertEqual(len(pending), 1)
        self.assertEqual(confirmed[0].level, "L3")
        self.assertEqual(confirmed[0].sample_size, 6)

    def test_missing_manual_raises_vf7015(self) -> None:
        with self.assertRaises(ApiError) as caught:
            load_manual_claims(self.root / "docs" / "devlog" / "nope.md")
        self.assertIs(caught.exception.code, ErrorCode.SELFCHECK_MANUAL_PENDING)

    def test_html_comment_block_is_ignored(self) -> None:
        text = (
            "<!--\n### CLM-000\n- 声称：示例\n- 确认：是\n-->\n"
            "### CLM-001\n- 声称：真实条目\n- 级别：L3\n- 确认：是\n"
        )
        records = parse_manual_text(text)
        self.assertEqual([item.claim_id for item in records], ["CLM-001"])

    def test_unclosed_block_is_pending(self) -> None:
        records = parse_manual_text(
            "### CLM-001\n- 声称：示例\n- 级别：L3\n- 确认：\n### CLM-002\n- 声称：第二条\n- 级别：L4\n- 确认：是\n"
        )
        self.assertEqual([item.confirmed for item in records], [False, True])

    def test_render_draft_leaves_decision_columns_empty(self) -> None:
        ctx = SelfcheckContext(self.root)
        text, count = render_draft(ctx)
        self.assertGreaterEqual(count, 1)
        self.assertIn("### CLM-001", text)
        self.assertIn("- 级别：\n", text)
        self.assertIn("- 确认：\n", text)
        self.assertNotIn("- 级别：L", text)

    def test_ensure_manual_template_respects_dry_run(self) -> None:
        target = self.root / "docs" / "devlog" / "selfcheck-manual.md"
        target.unlink()
        self.assertFalse(ensure_manual_template(target, dry_run=True))
        self.assertFalse(target.exists())
        self.assertTrue(ensure_manual_template(target, dry_run=False))
        self.assertTrue(target.is_file())


if __name__ == "__main__":
    unittest.main()