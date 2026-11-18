from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.eval.service import EvalCaseSet, EvalSetError

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "eval"


def base_case(index: int, category: str, digest_suffix: str = "") -> dict:
    return {
        "case_id": f"EVAL-{index:04d}",
        "category": category,
        "location": {"file": "app/main.py", "line": 31, "component": None, "component_version": None},
        "rule_id": "py/sql-injection",
        "severity": "HIGH",
        "ground_truth": {
            "reachable": category != "NEGATIVE",
            "fixable": category != "NEGATIVE",
            "expected_fix_kind": "PARAMETERIZED_QUERY",
            "should_reject": category == "ADVERSARIAL",
        },
        "proof_test_path": "tests/security/test_eval.py" if category == "POSITIVE" else None,
        "proof_pre_patch": "FAIL" if category == "POSITIVE" else None,
        "proof_post_patch": "PASS" if category == "POSITIVE" else None,
        "content_digest": hashlib.sha256(f"{index}-{category}-{digest_suffix}".encode()).hexdigest(),
    }


def write_set(path: Path, cases: list[dict]) -> str:
    path.write_text(json.dumps({"cases": cases}, ensure_ascii=False), encoding="utf-8")
    return hashlib.sha256(
        json.dumps(cases, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


class EvalSetTest(unittest.TestCase):
    def test_seeded_set_is_valid(self) -> None:
        if not (EVAL_DIR / "eval_set.json").is_file():
            self.skipTest("run scripts/seed_eval.py first")
        expected = json.loads((EVAL_DIR / "eval_set.sha256").read_text(encoding="utf-8"))["sha256"]
        case_set = EvalCaseSet.load(EVAL_DIR / "eval_set.json", expected_digest=expected)
        validation = case_set.validate()
        self.assertTrue(validation.ok, validation.issues)
        self.assertAlmostEqual(validation.ratio["POSITIVE"], 0.40, places=2)
        self.assertAlmostEqual(validation.ratio["NEGATIVE"], 0.30, places=2)
        self.assertEqual(len(case_set.cases), 50)

    def test_positive_only_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "set.json"
            cases = [base_case(index, "POSITIVE") for index in range(1, 51)]
            write_set(path, cases)
            case_set = EvalCaseSet.load(path)
            with self.assertRaises(EvalSetError) as raised:
                case_set.assert_valid()
            self.assertTrue(any("负例" in issue for issue in raised.exception.issues))

    def test_negative_ratio_too_low_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "set.json"
            cases = [base_case(index, "POSITIVE") for index in range(1, 41)]
            cases += [base_case(index, "NEGATIVE") for index in range(41, 46)]
            cases += [base_case(index, "BOUNDARY") for index in range(46, 50)]
            cases += [base_case(50, "ADVERSARIAL")]
            write_set(path, cases)
            case_set = EvalCaseSet.load(path)
            with self.assertRaises(EvalSetError) as raised:
                case_set.assert_valid()
            self.assertTrue(any("负例占比" in issue for issue in raised.exception.issues))

    def test_digest_mismatch_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "set.json"
            write_set(path, [base_case(index, "POSITIVE") for index in range(1, 51)])
            with self.assertRaises(EvalSetError) as raised:
                EvalCaseSet.load(path, expected_digest="0" * 64)
            self.assertTrue(any("摘要不符" in issue for issue in raised.exception.issues))

    def test_too_few_cases_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "set.json"
            cases = [base_case(index, "POSITIVE") for index in range(1, 11)]
            cases += [base_case(index, "NEGATIVE") for index in range(11, 21)]
            write_set(path, cases)
            case_set = EvalCaseSet.load(path)
            with self.assertRaises(EvalSetError) as raised:
                case_set.assert_valid()
            self.assertTrue(any("少于 50" in issue for issue in raised.exception.issues))


if __name__ == "__main__":
    unittest.main()