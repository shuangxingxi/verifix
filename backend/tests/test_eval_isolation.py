from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.envelope import ApiError, ErrorCode
from app.eval.isolation import (
    AccessAuditLog,
    AnswerIsolationGuard,
    PermissionProbe,
    ViolationCounter,
)

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "eval" / "cases"
EXPECTED = ROOT / "eval" / "expected"


class StubProbe(PermissionProbe):
    def __init__(self, denied: list[str] | None = None, cases_readable: bool = True) -> None:
        self._denied = denied or []
        self._cases_readable = cases_readable

    def probe_denied(self) -> list[str]:
        return list(self._denied)

    def cases_readable(self) -> bool:
        return self._cases_readable


class PathWhitelistTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.audit = AccessAuditLog(Path(self.tmp.name) / "audit.jsonl")
        self.guard = AnswerIsolationGuard(CASES, EXPECTED, audit=self.audit, probe=StubProbe())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_allows_case_input(self) -> None:
        resolved = self.guard.assert_load_path(CASES / "EVAL-0001.json", actor="exec")
        self.assertTrue(str(resolved).endswith("EVAL-0001.json"))

    def test_rejects_expected_directory(self) -> None:
        with self.assertRaises(ApiError) as raised:
            self.guard.assert_load_path(EXPECTED, actor="exec")
        self.assertIs(raised.exception.code, ErrorCode.EVAL_PATH_FORBIDDEN)

    def test_rejects_traversal_into_expected(self) -> None:
        with self.assertRaises(ApiError) as raised:
            self.guard.assert_load_path(CASES / ".." / "expected" / "EVAL-0001.answer.json", actor="exec")
        self.assertIs(raised.exception.code, ErrorCode.EVAL_PATH_FORBIDDEN)

    def test_rejects_outside_controlled_root(self) -> None:
        with self.assertRaises(ApiError) as raised:
            self.guard.assert_load_path(Path("C:/Windows/win.ini"), actor="exec")
        self.assertIs(raised.exception.code, ErrorCode.EVAL_PATH_FORBIDDEN)

    def test_denials_are_audited_and_exec_success_is_zero(self) -> None:
        with self.assertRaises(ApiError):
            self.guard.assert_load_path(EXPECTED, actor="exec")
        records = self.audit.search()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].actor, "exec")
        self.assertEqual(records[0].result, "拒绝")
        self.assertEqual(self.audit.exec_success_count(), 0)
        self.assertNotIn("expected_fix_kind", records[0].reason)

    def test_parent_child_directories_rejected(self) -> None:
        with self.assertRaises(ApiError) as raised:
            AnswerIsolationGuard(CASES, CASES / "expected", audit=self.audit, probe=StubProbe())
        self.assertIs(raised.exception.code, ErrorCode.EVAL_ISOLATION_UNMET)


class SelfCheckTest(unittest.TestCase):
    def test_passes_when_expected_unreadable_and_cases_readable(self) -> None:
        tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        guard = AnswerIsolationGuard(CASES, EXPECTED, audit=AccessAuditLog(), probe=StubProbe())
        verdict = guard.self_check()
        self.assertTrue(verdict.ok)
        self.assertLessEqual(verdict.elapsed_ms, 2000)
        tmp.cleanup()

    def test_fails_when_expected_readable(self) -> None:
        guard = AnswerIsolationGuard(CASES, EXPECTED, audit=AccessAuditLog(), probe=StubProbe(denied=["open", "traversal"]))
        with self.assertRaises(ApiError) as raised:
            guard.self_check()
        self.assertIs(raised.exception.code, ErrorCode.EVAL_ISOLATION_UNMET)

    def test_probe_invalidation_fails(self) -> None:
        guard = AnswerIsolationGuard(CASES, EXPECTED, audit=AccessAuditLog(), probe=StubProbe(cases_readable=False))
        with self.assertRaises(ApiError):
            guard.self_check()


class ViolationCounterTest(unittest.TestCase):
    def test_two_violations_continue_three_abort(self) -> None:
        counter = ViolationCounter(3)
        self.assertEqual(counter.record("RUN-1"), 1)
        self.assertFalse(counter.exceeded("RUN-1"))
        self.assertEqual(counter.record("RUN-1"), 2)
        self.assertFalse(counter.exceeded("RUN-1"))
        self.assertEqual(counter.record("RUN-1"), 3)
        self.assertTrue(counter.exceeded("RUN-1"))
        self.assertFalse(counter.exceeded("RUN-2"))


if __name__ == "__main__":
    unittest.main()