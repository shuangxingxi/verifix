from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.selfcheck.context import ReadOnlySnapshot, SelfcheckContext


class ReadOnlySnapshotTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "README.md").write_text("# fixture\n", encoding="utf-8")
        (self.root / "docs" / "devlog").mkdir(parents=True)
        (self.root / "docs" / "devlog" / "m12-closure-and-blockers.md").write_text(
            "内容\n", encoding="utf-8"
        )
        self.ctx = SelfcheckContext(self.root)
        self.snapshotter = ReadOnlySnapshot(self.ctx)

    def test_unchanged_snapshot_has_no_diff(self) -> None:
        before = self.snapshotter.capture()
        after = self.snapshotter.capture()
        self.assertFalse(self.snapshotter.has_diff(self.snapshotter.diff(before, after)))

    def test_changed_file_is_listed(self) -> None:
        before = self.snapshotter.capture()
        (self.root / "README.md").write_text("# changed\n", encoding="utf-8")
        after = self.snapshotter.capture()
        difference = self.snapshotter.diff(before, after)
        self.assertIn("README.md", difference["changed"])
        self.assertTrue(self.snapshotter.has_diff(difference))

    def test_added_and_removed_files_are_listed(self) -> None:
        before = self.snapshotter.capture()
        (self.root / "docs" / "devlog" / "m13-new.md").write_text("new\n", encoding="utf-8")
        (self.root / "README.md").unlink()
        difference = self.snapshotter.diff(before, self.snapshotter.capture())
        self.assertIn("docs/devlog/m13-new.md", difference["added"])
        self.assertIn("README.md", difference["removed"])

    def test_selfcheck_output_directory_excluded(self) -> None:
        output = self.root / "docs" / "devlog" / "selfcheck"
        output.mkdir(parents=True)
        (output / "index.json").write_text("{}", encoding="utf-8")
        (self.root / "docs" / "devlog" / "m13-selfcheck-report.md").write_text("# r\n", encoding="utf-8")
        (self.root / "docs" / "devlog" / "selfcheck.json").write_text("{}", encoding="utf-8")
        (self.root / "docs" / "devlog" / "selfcheck-manual-draft.md").write_text("# d\n", encoding="utf-8")
        snapshot = self.snapshotter.capture()
        self.assertNotIn("docs/devlog/selfcheck/index.json", snapshot)
        self.assertNotIn("docs/devlog/selfcheck-manual-draft.md", snapshot)
        self.assertNotIn("docs/devlog/m13-selfcheck-report.md", snapshot)
        self.assertNotIn("docs/devlog/selfcheck.json", snapshot)
        self.assertIn("docs/devlog/m12-closure-and-blockers.md", snapshot)

    def test_snapshot_has_no_restore_capability(self) -> None:
        self.assertFalse(hasattr(self.snapshotter, "restore"))
        self.assertFalse(hasattr(self.snapshotter, "rollback"))


if __name__ == "__main__":
    unittest.main()