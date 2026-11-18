from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(TESTS))

from app.selfcheck.checks import d4_consistency, d5_delivery
from app.selfcheck.context import SelfcheckContext
from app.selfcheck.models import Status
from support.selfcheck_fixtures import write_repo


class DeliveryRevisionTest(unittest.TestCase):
    """v1.1-R1/R2 核心回归：D4-1 三类载体 + D5-1 去依赖。"""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        write_repo(self.root)
        self.ctx = SelfcheckContext(self.root)

    def test_d5_1_stays_manual_pending_when_d4_1_blocked(self) -> None:
        (self.root / "deliverables" / "CodeArts方案.md").unlink()
        d4_result = d4_consistency._d4_1(self.ctx)
        self.assertIs(d4_result.status, Status.BLOCKED)
        d5_result = d5_delivery._d5_1(self.ctx)
        self.assertIs(d5_result.status, Status.MANUAL_PENDING)
        self.assertNotEqual(d5_result.sub_reason, "DEPENDENCY_FAILED")
        self.assertIn("独立判定", d5_result.output_summary)

    def test_d5_1_manual_pending_when_carriers_present(self) -> None:
        d4_result = d4_consistency._d4_1(self.ctx)
        self.assertIs(d4_result.status, Status.PASS)
        d5_result = d5_delivery._d5_1(self.ctx)
        self.assertIs(d5_result.status, Status.MANUAL_PENDING)
        self.assertNotEqual(d5_result.sub_reason, "DEPENDENCY_FAILED")

    def test_d5_2_passes_with_all_three_deliverables(self) -> None:
        result = d5_delivery._d5_2(self.ctx)
        self.assertIs(result.status, Status.PASS)

    def test_d5_2_blocks_when_presentation_and_video_missing(self) -> None:
        (self.root / "deliverables" / "演示材料.pptx").unlink()
        (self.root / "deliverables" / "demo.mp4").unlink()
        result = d5_delivery._d5_2(self.ctx)
        self.assertIs(result.status, Status.BLOCKED)
        self.assertEqual(result.sub_reason, "DELIVERY_GAP")
        self.assertIn("演示文稿缺失", result.output_summary)
        self.assertIn("演示视频缺失", result.output_summary)

    def test_d5_2_blocks_when_public_entry_missing(self) -> None:
        readme = self.root / "README.md"
        readme.write_text(
            readme.read_text(encoding="utf-8").replace("- 演示入口：https://demo.example.com/verifix", ""),
            encoding="utf-8",
        )
        result = d5_delivery._d5_2(self.ctx)
        self.assertIs(result.status, Status.BLOCKED)
        self.assertIn("可访问演示入口缺失", result.output_summary)

    def test_d4_1_criterion_does_not_mention_demo_material(self) -> None:
        from app.selfcheck.registry import default_registry

        criterion = default_registry.get("D4-1").criterion
        self.assertIn("三类文字载体", criterion)
        self.assertNotIn("演示材料", criterion)
        self.assertEqual(default_registry.get("D5-1").depends_on, ())

    def test_d5_4_accepts_long_non_placeholder_material(self) -> None:
        result = d5_delivery._d5_4(self.ctx)
        self.assertIs(result.status, Status.PASS)


if __name__ == "__main__":
    unittest.main()