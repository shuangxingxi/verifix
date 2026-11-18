from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.envelope import ApiError, ErrorCode
from app.eval.models import EvalCaseInput, ExpectedAnswer
from app.eval.splitter import EvalSetSplitter

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "eval"
ANSWER_FIELDS = {"category", "reachable", "fixable", "expected_fix_kind", "should_reject", "proof_pre_patch", "proof_post_patch"}


class SplitResultTest(unittest.TestCase):
    def test_split_directories_have_matching_case_ids(self) -> None:
        cases = sorted(path.stem for path in (EVAL_DIR / "cases").glob("EVAL-*.json"))
        answers = sorted(path.name.replace(".answer.json", "") for path in (EVAL_DIR / "expected").glob("EVAL-*.json"))
        self.assertEqual(len(cases), 50)
        self.assertEqual(len(answers), 50)
        self.assertEqual(cases, answers)

    def test_manifest_binding_matches_directories(self) -> None:
        manifest = json.loads((EVAL_DIR / "cases" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["case_count"], 50)
        self.assertEqual(manifest["category_distribution"], {"POSITIVE": 20, "NEGATIVE": 15, "BOUNDARY": 10, "ADVERSARIAL": 5})
        for key in ("cases_digest", "expected_digest", "binding_digest", "set_version", "created_at", "actor"):
            self.assertTrue(manifest[key])

    def test_case_inputs_carry_no_answer_fields(self) -> None:
        for path in (EVAL_DIR / "cases").glob("EVAL-*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(ANSWER_FIELDS.intersection(payload), path.name)
            EvalCaseInput(**payload)

    def test_expected_answers_are_isolated(self) -> None:
        answer = json.loads((EVAL_DIR / "expected" / "EVAL-0001.answer.json").read_text(encoding="utf-8"))
        self.assertIn("category", answer)
        self.assertIn("answer_digest", answer)
        ExpectedAnswer(**answer)

    def test_retired_registry_exists(self) -> None:
        retired = json.loads((EVAL_DIR / "expected" / "_retired" / "legacy.json").read_text(encoding="utf-8"))
        self.assertEqual(retired["sha256"][:8], "75079f7b")
        self.assertIn("replaced_by", retired)


class SplitIdempotencyTest(unittest.TestCase):
    def test_second_apply_is_skipped(self) -> None:
        with TemporaryDirectory() as tmp:
            splitter = EvalSetSplitter(
                EVAL_DIR / "eval_set.json",
                Path(tmp) / "cases",
                Path(tmp) / "expected",
                "1.0.0",
            )
            first = splitter.apply()
            second = splitter.apply()
            self.assertTrue(first.applied)
            self.assertTrue(second.skipped)
            self.assertEqual(first.binding_digest, second.binding_digest)

    def test_tampered_expected_blocks_reapply(self) -> None:
        with TemporaryDirectory() as tmp:
            cases_dir = Path(tmp) / "cases"
            expected_dir = Path(tmp) / "expected"
            splitter = EvalSetSplitter(EVAL_DIR / "eval_set.json", cases_dir, expected_dir, "1.0.0")
            splitter.apply()
            target = sorted(expected_dir.glob("EVAL-*.answer.json"))[0]
            payload = json.loads(target.read_text(encoding="utf-8"))
            payload["reachable"] = not payload["reachable"]
            target.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ApiError) as raised:
                splitter.apply()
            self.assertIs(raised.exception.code, ErrorCode.EVAL_INVALID)

    def test_dry_run_does_not_write(self) -> None:
        with TemporaryDirectory() as tmp:
            cases_dir = Path(tmp) / "cases"
            expected_dir = Path(tmp) / "expected"
            report = EvalSetSplitter(EVAL_DIR / "eval_set.json", cases_dir, expected_dir, "1.0.0").dry_run()
            self.assertFalse(report.applied)
            self.assertFalse(cases_dir.exists())
            self.assertFalse(expected_dir.exists())


if __name__ == "__main__":
    unittest.main()