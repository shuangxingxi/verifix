from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.selfcheck.context import SelfcheckContext
from app.selfcheck.models import (
    CheckResult,
    CheckSpec,
    Dimension,
    JudgmentMode,
    ProbeOutput,
    Status,
    ThreeQuestion,
    build_result,
)
from app.selfcheck.registry import CheckRegistry
from app.selfcheck.runner import SelfcheckRunner


class FakeProbe:
    def __init__(self, *, timed_out: bool = False) -> None:
        self.timed_out = timed_out
        self.calls: list[tuple] = []

    def run(self, argv, *, timeout, cwd=None, env_mode=None, summary_limit=2000) -> ProbeOutput:
        self.calls.append((tuple(argv), timeout, str(cwd)))
        return ProbeOutput(
            exit_code=None if self.timed_out else 0,
            stdout_tail="ok",
            timed_out=self.timed_out,
        )


def _spec(check_id: str, handler, *, depends_on: tuple[str, ...] = (), question=ThreeQuestion.REPRODUCE):
    return CheckSpec(
        check_id=check_id,
        title=f"检查 {check_id}",
        dimension=Dimension.REPRODUCIBLE,
        mode=JudgmentMode.AUTO,
        question=question,
        criterion="示例标准",
        depends_on=depends_on,
        handler=handler,
    )


def _passing(spec):
    def handler(ctx):
        return build_result(spec, Status.PASS, output_summary="通过")

    return handler


def _raising(spec):
    def handler(ctx):
        raise RuntimeError("boom")

    return handler


def _wrong_id(spec):
    def handler(ctx):
        return CheckResult(
            check_id="D1-99",
            dimension=spec.dimension,
            mode=spec.mode,
            question=spec.question,
            status=Status.PASS,
        )

    return handler


class RunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "README.md").write_text("# fixture\n", encoding="utf-8")
        self.ctx = SelfcheckContext(self.root, probe=FakeProbe())
        self.registry = CheckRegistry()

    def test_exception_is_isolated_and_reported(self) -> None:
        pass_spec = _spec("D1-1", None)
        self.registry.register(pass_spec)
        pass_spec.handler = _passing(pass_spec)
        fail_spec = _spec("D1-2", None)
        self.registry.register(fail_spec)
        fail_spec.handler = _raising(fail_spec)
        tail_spec = _spec("D1-3", None)
        self.registry.register(tail_spec)
        tail_spec.handler = _passing(tail_spec)

        result = SelfcheckRunner(self.ctx, self.registry).run(None)
        statuses = {item.check_id: item for item in result.checks}
        self.assertIs(statuses["D1-1"].status, Status.PASS)
        self.assertIs(statuses["D1-2"].status, Status.BLOCKED)
        self.assertEqual(statuses["D1-2"].sub_reason, "EXCEPTION")
        self.assertIs(statuses["D1-3"].status, Status.PASS)
        self.assertEqual(result.overall, "不通过")
        self.assertEqual(result.exit_code, 3)

    def test_dependency_failure_is_propagated(self) -> None:
        base = _spec("D1-1", None)
        self.registry.register(base)
        base.handler = _raising(base)
        dependent = _spec("D1-2", None, depends_on=("D1-1",))
        self.registry.register(dependent)
        dependent.handler = _passing(dependent)

        result = SelfcheckRunner(self.ctx, self.registry).run(None)
        statuses = {item.check_id: item for item in result.checks}
        self.assertIs(statuses["D1-2"].status, Status.BLOCKED)
        self.assertEqual(statuses["D1-2"].sub_reason, "DEPENDENCY_FAILED")

    def test_manual_pending_dependency_propagates_strictest(self) -> None:
        base = _spec("D1-1", None)
        self.registry.register(base)
        base.handler = lambda ctx: build_result(base, Status.MANUAL_PENDING, output_summary="待填")
        dependent = _spec("D1-2", None, depends_on=("D1-1",))
        self.registry.register(dependent)
        dependent.handler = _passing(dependent)

        result = SelfcheckRunner(self.ctx, self.registry).run(None)
        statuses = {item.check_id: item for item in result.checks}
        self.assertIs(statuses["D1-2"].status, Status.MANUAL_PENDING)
        self.assertEqual(statuses["D1-2"].sub_reason, "DEPENDENCY_FAILED")

    def test_check_id_mismatch_is_blocked(self) -> None:
        spec = _spec("D1-1", None)
        self.registry.register(spec)
        spec.handler = _wrong_id(spec)
        result = SelfcheckRunner(self.ctx, self.registry).run(None)
        self.assertIs(result.checks[0].status, Status.BLOCKED)
        self.assertIn("不一致", result.checks[0].output_summary)

    def test_scope_excluded_items_are_unverified(self) -> None:
        for index in range(1, 3):
            spec = _spec(f"D1-{index}", None)
            self.registry.register(spec)
            spec.handler = _passing(spec)
        capability = _spec("D2-1", None)
        capability.dimension = Dimension.CAPABILITY
        self.registry.register(capability)
        capability.handler = _passing(capability)

        result = SelfcheckRunner(self.ctx, self.registry).run(("D1",))
        statuses = {item.check_id: item.status for item in result.checks}
        self.assertIs(statuses["D2-1"], Status.UNVERIFIED)
        self.assertIs(result.checks[-1].status, Status.UNVERIFIED)
        self.assertEqual(result.checks[-1].sub_reason, "SCOPE_EXCLUDED")
        self.assertEqual(result.exit_code, 2)

    def test_order_is_registration_order(self) -> None:
        ids = ["D1-3", "D1-1", "D1-2"]
        for check_id in ids:
            spec = _spec(check_id, None)
            self.registry.register(spec)
            spec.handler = _passing(spec)
        result = SelfcheckRunner(self.ctx, self.registry).run(None)
        self.assertEqual([item.check_id for item in result.checks], ids)

    def test_readonly_violation_blocks_everything(self) -> None:
        spec = _spec("D1-1", None)
        self.registry.register(spec)

        def mutating(ctx):
            (self.root / "README.md").write_text("# mutated\n", encoding="utf-8")
            return build_result(spec, Status.PASS, output_summary="通过")

        spec.handler = mutating
        result = SelfcheckRunner(self.ctx, self.registry).run(None)
        self.assertFalse(result.readonly_ok)
        self.assertEqual(result.overall, "不通过")
        self.assertEqual(result.exit_code, 3)
        self.assertIn("README.md", result.readonly_files["changed"])


if __name__ == "__main__":
    unittest.main()