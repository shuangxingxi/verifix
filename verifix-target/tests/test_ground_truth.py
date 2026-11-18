from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import verify_ground_truth


class GroundTruthTest(unittest.TestCase):
    def test_ground_truth_matches_code(self) -> None:
        self.assertEqual(verify_ground_truth.verify(), [])

    def test_distribution(self) -> None:
        data = json.loads((ROOT / "ground_truth.json").read_text(encoding="utf-8"))
        classes = [item["defect_class"] for item in data["items"]]
        self.assertEqual(classes.count("C02"), 6)
        self.assertEqual(classes.count("C03"), 4)
        self.assertEqual(classes.count("C01"), 3)
        self.assertEqual(classes.count("C05"), 2)


if __name__ == "__main__":
    unittest.main()