from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(TESTS))

from app.selfcheck.checks import d4_consistency
from app.selfcheck.context import SelfcheckContext
from app.selfcheck.loaders import (
    build_consistency_rows,
    extract_field_hits,
    load_carriers,
    percent_hits_with_sample,
)
from app.selfcheck.models import Status
from support.selfcheck_fixtures import append_document, write_repo


class ConsistencyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        write_repo(self.root)
        self.ctx = SelfcheckContext(self.root)

    def test_field_extraction_has_locations(self) -> None:
        carriers = load_carriers(self.ctx)
        hits = extract_field_hits(carriers)
        self.assertTrue(hits["覆盖率"])
        self.assertTrue(hits["用例数"])
        self.assertTrue(hits["样本量"])
        for hit in hits["覆盖率"][:3]:
            self.assertIn(":", hit.location)

    def test_cross_carrier_values_are_consistent(self) -> None:
        rows = build_consistency_rows(load_carriers(self.ctx))
        coverage = next(row for row in rows if row.field == "覆盖率")
        self.assertEqual(set(coverage.values_by_carrier.values()), {"54.5%"})
        result = d4_consistency._d4_2(self.ctx)
        self.assertIs(result.status, Status.PASS)

    def test_conflict_is_blocked_and_lists_carriers(self) -> None:
        append_document(self.root, "README.md", "- 缺陷 12 类")
        result = d4_consistency._d4_2(self.ctx)
        self.assertIs(result.status, Status.BLOCKED)
        self.assertEqual(result.sub_reason, "VALUE_CONFLICT")
        self.assertIn("缺陷类别数", result.output_summary)

    def test_percentage_without_sample_is_blocked(self) -> None:
        append_document(self.root, "README.md", "- 覆盖率 88%")
        result = d4_consistency._d4_3(self.ctx)
        self.assertIs(result.status, Status.BLOCKED)
        self.assertEqual(result.sub_reason, "SAMPLE_MISSING")

    def test_vague_expression_is_blocked(self) -> None:
        append_document(self.root, "README.md", "- 覆盖率约 60%")
        result = d4_consistency._d4_3(self.ctx)
        self.assertIs(result.status, Status.BLOCKED)

    def test_small_sample_warns(self) -> None:
        for relative in (
            "README.md",
            "deliverables/CodeArts方案.md",

            "docs/devlog/m12-closure-and-blockers.md",
        ):
            path = self.root / relative
            text = path.read_text(encoding="utf-8").replace("n=6", "n=3")
            text = text.replace("覆盖率 54.5% |", "覆盖率 54.5%，n=3 |")
            path.write_text(text, encoding="utf-8")
        result = d4_consistency._d4_3(self.ctx)
        self.assertIs(result.status, Status.WARNING)
        self.assertEqual(result.sub_reason, "SMALL_SAMPLE")

    def test_text_carriers_constant_has_three_entries(self) -> None:
        from app.selfcheck.loaders import TEXT_CARRIERS

        self.assertEqual(len(TEXT_CARRIERS), 3)
        self.assertEqual(
            {item[1] for item in TEXT_CARRIERS},
            {"README.md", "docs/devlog/m12-closure-and-blockers.md", "deliverables/CodeArts方案.md"},
        )

    def test_d4_1_passes_without_demo_material(self) -> None:
        self.assertFalse((self.root / "deliverables" / "演示材料.md").exists())
        result = d4_consistency._d4_1(self.ctx)
        self.assertIs(result.status, Status.PASS)
        self.assertNotIn("演示材料", result.output_summary)

    def test_d4_1_blocks_when_text_carrier_missing(self) -> None:
        (self.root / "deliverables" / "CodeArts方案.md").unlink()
        result = d4_consistency._d4_1(self.ctx)
        self.assertIs(result.status, Status.BLOCKED)
        self.assertEqual(result.sub_reason, "MISSING")
        self.assertIn("CodeArts方案.md", result.output_summary)

    def test_d4_1_blocks_on_empty_body(self) -> None:
        (self.root / "README.md").write_text("# 仅标题\n", encoding="utf-8")
        result = d4_consistency._d4_1(self.ctx)
        self.assertIs(result.status, Status.BLOCKED)
        self.assertEqual(result.sub_reason, "MISSING")

    def test_dual_caliber_passes(self) -> None:
        result = d4_consistency._d4_4(self.ctx)
        self.assertIs(result.status, Status.PASS)

    def test_single_caliber_is_blocked(self) -> None:
        for relative in ("README.md", "deliverables/CodeArts方案.md"):
            path = self.root / relative
            path.write_text(
                path.read_text(encoding="utf-8").replace("判定函数口径 62.0%", ""),
                encoding="utf-8",
            )
        result = d4_consistency._d4_4(self.ctx)
        self.assertIs(result.status, Status.BLOCKED)
        self.assertEqual(result.sub_reason, "SINGLE_CALIBER")
        self.assertIn("判定函数口径", result.output_summary)

    def test_unverified_claim_as_done_is_blocked(self) -> None:
        append_document(self.root, "README.md", "- 云上已验证，可直接发布")
        result = d4_consistency._d4_5(self.ctx)
        self.assertIs(result.status, Status.BLOCKED)
        self.assertEqual(result.sub_reason, "UNVERIFIED_CLAIMED_DONE")
        self.assertIn("未验证", result.output_summary)

    def test_branch_conflict_is_blocked(self) -> None:
        append_document(self.root, "README.md", "- 自动合并主干")
        result = d4_consistency._d4_6(self.ctx)
        self.assertIs(result.status, Status.BLOCKED)
        self.assertEqual(result.sub_reason, "BRANCH_CONFLICT")

    def test_percent_hits_ignore_non_metric_percentages(self) -> None:
        append_document(self.root, "README.md", "- 性能提升 10%")
        pairs = percent_hits_with_sample(load_carriers(self.ctx))
        self.assertFalse(any(hit.value == "10%" for hit, _sample in pairs))


if __name__ == "__main__":
    unittest.main()