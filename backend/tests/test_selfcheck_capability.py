from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(TESTS))

from app.selfcheck.checks import d2_capability
from app.selfcheck.context import SelfcheckContext
from app.selfcheck.models import Status
from support.selfcheck_fixtures import write_repo

_BASE = """# 自检人工输入

### CLM-001
- 声称：示例声称
- 载体：README.md
- 真实来源：python -m unittest
- 级别：{level}
- 证据：无
- 样本量：6
- 确认：{confirm}
"""


class CapabilityLevelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        write_repo(self.root)
        self.ctx = SelfcheckContext(self.root)

    def _write_manual(self, level: str, confirm: str) -> None:
        (self.root / "docs" / "devlog" / "selfcheck-manual.md").write_text(
            _BASE.format(level=level, confirm=confirm), encoding="utf-8"
        )

    def test_missing_level_is_manual_pending(self) -> None:
        self._write_manual("", "待确认")
        result = d2_capability._d2_2(self.ctx)
        self.assertIs(result.status, Status.MANUAL_PENDING)
        self.assertNotEqual(result.sub_reason, "LEVEL_INVALID")

    def test_missing_level_but_confirmed_is_still_pending_not_blocked(self) -> None:
        self._write_manual("", "是")
        result = d2_capability._d2_2(self.ctx)
        self.assertIs(result.status, Status.MANUAL_PENDING)
        self.assertNotEqual(result.sub_reason, "LEVEL_INVALID")

    def test_illegal_level_is_blocked(self) -> None:
        self._write_manual("L9", "是")
        result = d2_capability._d2_2(self.ctx)
        self.assertIs(result.status, Status.BLOCKED)
        self.assertEqual(result.sub_reason, "LEVEL_INVALID")

    def test_valid_level_and_confirmed_passes(self) -> None:
        self._write_manual("L3", "是")
        result = d2_capability._d2_2(self.ctx)
        self.assertIs(result.status, Status.PASS)


if __name__ == "__main__":
    unittest.main()