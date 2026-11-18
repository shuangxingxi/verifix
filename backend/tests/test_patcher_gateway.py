from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.patcher.gateway import (
    BugContext,
    FakeProvider,
    ModelBudgetExceeded,
    ModelGateway,
    ModelOutputRejected,
    TaskKind,
)

VALID_PATCH = {"files": {"app/main.py": "x = 1\n"}, "fix_paradigm": "PARAMETERIZED_QUERY"}
VALID_TEST = {"test_path": "tests/security/test_iss_1.py", "content": "def test_x():\n    assert True\n"}


def _ctx(issue_id: str = "ISS-1") -> BugContext:
    return BugContext(issue_id=issue_id, rule_id="py/sql-injection", defect_class="C02", file="app/main.py", line=31)


def _gateway(payload: str, max_calls: int = 3, timeout: int = 60) -> ModelGateway:
    return ModelGateway(FakeProvider(payload=payload), max_calls_per_issue=max_calls, timeout_seconds=timeout)


class BudgetAndConfigTest(unittest.TestCase):
    def test_budget_is_enforced(self) -> None:
        gateway = _gateway(json.dumps(VALID_PATCH), max_calls=1)
        gateway.generate_patch(_ctx())
        with self.assertRaises(ModelBudgetExceeded) as raised:
            gateway.generate_patch(_ctx())
        self.assertEqual(raised.exception.max_calls, 1)
        self.assertEqual(gateway.calls_for("ISS-1"), 1)

    def test_config_is_clamped(self) -> None:
        gateway = ModelGateway(FakeProvider(payload="{}"), max_calls_per_issue=99, timeout_seconds=0)
        self.assertEqual(gateway.max_calls_per_issue, 5)
        self.assertEqual(gateway.timeout_seconds, 1)
        self.assertEqual(gateway.model_provider_name, "fake")

    def test_budget_is_per_issue(self) -> None:
        gateway = _gateway(json.dumps(VALID_PATCH), max_calls=1)
        gateway.generate_patch(_ctx("ISS-1"))
        gateway.generate_patch(_ctx("ISS-2"))
        self.assertEqual(gateway.calls_for("ISS-1"), 1)
        self.assertEqual(gateway.calls_for("ISS-2"), 1)


class OutputValidationTest(unittest.TestCase):
    def test_invalid_json_is_rejected(self) -> None:
        with self.assertRaises(ModelOutputRejected) as raised:
            _gateway("not-json").generate_patch(_ctx())
        self.assertIn("invalid json", raised.exception.reason)

    def test_non_object_output_is_rejected(self) -> None:
        with self.assertRaises(ModelOutputRejected) as raised:
            _gateway("[1, 2]").generate_test(_ctx())
        self.assertIn("json object", raised.exception.reason)

    def test_missing_keys_are_rejected(self) -> None:
        with self.assertRaises(ModelOutputRejected) as raised:
            _gateway(json.dumps({"files": {}})).generate_test(_ctx())
        self.assertIn("missing keys", raised.exception.reason)

    def test_empty_files_mapping_is_rejected(self) -> None:
        with self.assertRaises(ModelOutputRejected) as raised:
            _gateway(json.dumps({"files": {}, "fix_paradigm": "X"})).generate_patch(_ctx())
        self.assertIn("non-empty files", raised.exception.reason)

    def test_files_not_mapping_is_rejected(self) -> None:
        with self.assertRaises(ModelOutputRejected):
            _gateway(json.dumps({"files": ["a.py"], "fix_paradigm": "X"})).generate_patch(_ctx())

    def test_invalid_path_is_rejected(self) -> None:
        with self.assertRaises(ModelOutputRejected) as raised:
            _gateway(json.dumps({"files": {"": "x = 1\n"}, "fix_paradigm": "X"})).generate_patch(_ctx())
        self.assertIn("invalid file path", raised.exception.reason)

    def test_non_string_body_is_rejected(self) -> None:
        with self.assertRaises(ModelOutputRejected) as raised:
            _gateway(json.dumps({"files": {"app/main.py": 1}, "fix_paradigm": "X"})).generate_patch(_ctx())
        self.assertIn("must be a string", raised.exception.reason)

    def test_syntax_error_is_rejected(self) -> None:
        with self.assertRaises(ModelOutputRejected) as raised:
            _gateway(json.dumps({"files": {"app/main.py": "def broken(:\n"}, "fix_paradigm": "X"})).generate_patch(_ctx())
        self.assertIn("syntax error", raised.exception.reason)


class SuccessPathTest(unittest.TestCase):
    def test_patch_test_and_context_paths(self) -> None:
        provider = FakeProvider(payload=json.dumps(VALID_PATCH))
        gateway = ModelGateway(provider)
        self.assertEqual(gateway.generate_patch(_ctx())["fix_paradigm"], "PARAMETERIZED_QUERY")
        self.assertEqual(gateway.calls_for("ISS-1"), 1)

        test_gateway = ModelGateway(FakeProvider(payload=json.dumps(VALID_TEST)))
        self.assertEqual(test_gateway.generate_test(_ctx())["test_path"], "tests/security/test_iss_1.py")

        adapt_gateway = ModelGateway(FakeProvider(payload="plain context"))
        self.assertEqual(adapt_gateway.adapt_context(_ctx()), "plain context")

        history = gateway.history()
        self.assertEqual(history[0]["provider"], "fake")
        self.assertEqual(history[0]["task"], TaskKind.PATCH_GEN.value)
        self.assertIn("latency_ms", history[0])

    def test_provider_contract(self) -> None:
        provider = FakeProvider(healthy=False)
        self.assertFalse(provider.health().healthy)
        self.assertGreater(provider.estimate_cost(TaskKind.PATCH_GEN, {}).budget_yuan, 0)


if __name__ == "__main__":
    unittest.main()