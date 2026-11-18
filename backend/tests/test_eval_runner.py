from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.envelope import ApiError, ErrorCode
from app.config import load_config
from app.eval.isolation import PermissionProbe
from app.eval.models import EvalObservation
from app.eval.runner import EvalRunner
from app.eval.splitter import EvalSetSplitter

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "eval"


class StubProbe(PermissionProbe):
    def __init__(self, denied: list[str] | None = None, cases_readable: bool = True) -> None:
        self._denied = denied or []
        self._cases_readable = cases_readable

    def probe_denied(self) -> list[str]:
        return list(self._denied)

    def cases_readable(self) -> bool:
        return self._cases_readable


class EvalRunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config()
        self.tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.runner = EvalRunner(
            self.config,
            ROOT / "verifix-target",
            Path(self.tmp.name),
            probe=StubProbe(),
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_legacy_single_file_is_retired(self) -> None:
        with self.assertRaises(ApiError) as raised:
            self.runner.start(EVAL_DIR / "eval_set.json")
        self.assertIs(raised.exception.code, ErrorCode.EVAL_LEGACY_RETIRED)

    def test_positive_only_set_rejected_before_writing(self) -> None:
        with TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "legacy.json"
            cases = [
                {
                    "case_id": f"EVAL-{index:04d}",
                    "category": "POSITIVE",
                    "location": {"file": "app/main.py", "line": 31},
                    "rule_id": "py/sql-injection",
                    "severity": "HIGH",
                    "ground_truth": {
                        "reachable": True,
                        "fixable": True,
                        "expected_fix_kind": "PARAMETERIZED_QUERY",
                        "should_reject": False,
                    },
                    "proof_test_path": "tests/security/test_eval.py",
                    "proof_pre_patch": "FAIL",
                    "proof_post_patch": "PASS",
                    "content_digest": f"{index:064d}",
                }
                for index in range(1, 51)
            ]
            legacy.write_text(json.dumps({"cases": cases}), encoding="utf-8")
            splitter = EvalSetSplitter(
                legacy,
                Path(tmp) / "cases",
                Path(tmp) / "expected",
                "1.0.0",
            )
            with self.assertRaises(ApiError) as raised:
                splitter.apply()
            self.assertIs(raised.exception.code, ErrorCode.EVAL_INVALID)
            self.assertFalse((Path(tmp) / "cases").exists())

    def test_step_and_resume(self) -> None:
        run = self.runner.start(EVAL_DIR / "cases", "1.0.0", "exec")
        self.assertEqual(run.total, 50)
        self.assertEqual(run.completed, 0)
        binding = run.binding_digest

        self.runner.step(run.eval_run_id, limit=1)
        self.assertEqual(run.completed, 1)

        self.runner.interrupt(run.eval_run_id, "sandbox unavailable")
        self.assertEqual(run.status, "INTERRUPTED")

        self.runner.resume(run.eval_run_id, limit=1)
        self.assertEqual(run.status, "RUNNING")
        self.assertEqual(run.completed, 2)
        self.assertEqual(len(run.results), 2)
        self.assertEqual(run.binding_digest, binding)

    def test_observation_has_no_adjudication_fields(self) -> None:
        run = self.runner.start(EVAL_DIR / "cases", "1.0.0", "exec")
        self.runner.step(run.eval_run_id, limit=1)
        payload = json.loads((Path(self.tmp.name) / f"{run.eval_run_id}.json").read_text(encoding="utf-8"))
        observation = payload["observations"][0]
        forbidden = {"status", "category", "verdict_agrees", "shallow_fix_rejected", "ground_truth"}
        self.assertFalse(forbidden.intersection(observation))
        self.assertFalse({"verdict_agrees", "shallow_fix_rejected", "category"}.intersection(payload))
        self.assertEqual(set(observation), set(EvalObservation.model_fields))

    def test_negative_case_is_not_detected(self) -> None:
        run = self.runner.start(EVAL_DIR / "cases", "1.0.0", "exec")
        self.runner.step(run.eval_run_id, limit=25)
        negative_path = EVAL_DIR / "expected" / "EVAL-0021.answer.json"
        if not negative_path.is_file():
            self.skipTest("negative answer fixture missing")
        answer = json.loads(negative_path.read_text(encoding="utf-8"))
        observation = next(item for item in run.results if item.case_id == answer["case_id"])
        self.assertFalse(observation.detected)

    def test_loader_rejects_expected_directory(self) -> None:
        with self.assertRaises(ApiError) as raised:
            self.runner.guard.assert_load_path(EVAL_DIR / "expected", actor="exec")
        self.assertIs(raised.exception.code, ErrorCode.EVAL_PATH_FORBIDDEN)

    def test_isolation_failure_blocks_start(self) -> None:
        runner = EvalRunner(
            self.config,
            ROOT / "verifix-target",
            Path(self.tmp.name) / "blocked",
            probe=StubProbe(denied=["open"]),
        )
        with self.assertRaises(ApiError) as raised:
            runner.start(EVAL_DIR / "cases", "1.0.0", "exec")
        self.assertIs(raised.exception.code, ErrorCode.EVAL_ISOLATION_UNMET)

    def test_manifest_binding_mismatch_rejected(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            cases_dir = Path(tmp) / "cases"
            expected_dir = Path(tmp) / "expected"
            cases_dir.mkdir()
            expected_dir.mkdir()
            for path in (EVAL_DIR / "cases").glob("*.json"):
                (cases_dir / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            manifest_path = cases_dir / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["binding_digest"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            config = self.config.model_copy(
                update={
                    "eval": self.config.eval.model_copy(
                        update={"cases_dir": str(cases_dir), "expected_dir": str(expected_dir)}
                    )
                }
            )
            runner = EvalRunner(config, ROOT / "verifix-target", Path(tmp) / "runs", probe=StubProbe())
            with self.assertRaises(ApiError) as raised:
                runner.start(cases_dir, "1.0.0", "exec")
            self.assertIs(raised.exception.code, ErrorCode.EVAL_DIGEST_MISMATCH)

    def test_exec_success_audit_count_is_zero(self) -> None:
        self.runner.start(EVAL_DIR / "cases", "1.0.0", "exec")
        self.assertEqual(self.runner.audit.exec_success_count(), 0)


if __name__ == "__main__":
    unittest.main()