from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.eval.models import EvalCaseInput, EvalObservation

ROOT = Path(__file__).resolve().parents[2]
APP_DIR = ROOT / "backend" / "app"
FORBIDDEN = {"status", "category", "verdict_agrees", "shallow_fix_rejected"}


class StaticIsolationTest(unittest.TestCase):
    def test_eval_case_only_used_by_splitter_and_legacy_service(self) -> None:
        allowed = {
            str(APP_DIR / "eval" / "splitter.py"),
            str(APP_DIR / "eval" / "service.py"),
            str(APP_DIR / "domain" / "models.py"),
        }
        offenders = []
        for path in APP_DIR.rglob("*.py"):
            if str(path) in allowed:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "EvalCase(" in text:
                offenders.append(str(path))
        self.assertEqual(offenders, [])

    def test_observation_fields_exclude_adjudication(self) -> None:
        self.assertFalse(FORBIDDEN.intersection(EvalObservation.model_fields))
        self.assertIn("binding_digest", EvalObservation.model_fields)

    def test_case_input_fields_exclude_answer(self) -> None:
        self.assertFalse(FORBIDDEN.intersection(EvalCaseInput.model_fields))
        self.assertIn("public_exec_params", EvalCaseInput.model_fields)


if __name__ == "__main__":
    unittest.main()
