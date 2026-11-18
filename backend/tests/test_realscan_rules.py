from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.realscan.rules import ADVISORIES, RULES, verify_advisories, version_tuple
from app.realscan.scanner import scan_tree
from app.realscan.target import TargetViewBuilder

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "verifix-target"


def _view(tmp: Path):
    return TargetViewBuilder().build(TARGET, tmp)


class StaticRuleTest(unittest.TestCase):
    def test_rul01_c02_catches_six_sql_sinks(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            view = _view(Path(tmp_raw))
            findings = scan_tree(Path(view.view_root), ADVISORIES)
            sql = [item for item in findings if item["defect_class"] == "C02"]
            self.assertEqual([item["line"] for item in sql], [31, 41, 50, 58, 66, 74])

    def test_rul02_c03_catches_four_command_sinks_and_ignores_shell_false(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            root = Path(tmp_raw)
            view = _view(root)
            cmd = [item for item in scan_tree(Path(view.view_root), ADVISORIES) if item["defect_class"] == "C03"]
            self.assertEqual([item["line"] for item in cmd], [81, 87, 93, 99])
            sample = root / "sample"
            sample.mkdir()
            (sample / "safe.py").write_text(
                "import subprocess\nsubprocess.run(['echo', 'hi'], shell=False)\nsubprocess.run('echo hi')\n",
                encoding="utf-8",
            )
            self.assertEqual(scan_tree(sample, ADVISORIES), [])

    def test_rul03_c01_matches_three_pins_without_truth_file(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            view = _view(Path(tmp_raw))
            self.assertFalse((Path(view.view_root) / "ground_truth.json").exists())
            dep = [item for item in scan_tree(Path(view.view_root), ADVISORIES) if item["defect_class"] == "C01"]
            self.assertEqual([item["snippet_masked"] for item in dep], ["requests==2.19.1", "PyYAML==5.1", "Jinja2==2.10.1"])
            self.assertEqual([item["line"] for item in dep], [2, 3, 4])

    def test_rul04_c05_masks_credentials(self) -> None:
        with TemporaryDirectory() as tmp_raw:
            view = _view(Path(tmp_raw))
            cred = [item for item in scan_tree(Path(view.view_root), ADVISORIES) if item["defect_class"] == "C05"]
            self.assertEqual(len(cred), 2)
            self.assertEqual([item["line"] for item in cred], [1, 2])
            for item in cred:
                self.assertIn("***", item["snippet_masked"])
            dumped = str(cred)
            self.assertNotIn("vf-target-secret", dumped)
            self.assertNotIn("Target#Passw0rd2026", dumped)

    def test_rul05_advisory_table_is_consistent_and_decoupled(self) -> None:
        self.assertEqual(verify_advisories(), [])
        self.assertEqual(len(RULES), 4)
        self.assertEqual({rule.defect_class for rule in RULES}, {"C01", "C02", "C03", "C05"})
        for advisory in ADVISORIES:
            self.assertLess(version_tuple(advisory.affected), version_tuple(advisory.fixed))
            self.assertTrue(advisory.source_ref.startswith("NVD:"))
        errors = verify_advisories([type(ADVISORIES[0])("x", "2.0", "1.0", "bad", "")])
        self.assertEqual(len(errors), 3)


if __name__ == "__main__":
    unittest.main()