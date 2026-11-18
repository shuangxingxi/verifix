from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import ConfigValidationError, load_config, parse_memory_mb


class ConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        self._clean_env = {key: value for key, value in os.environ.items() if not key.startswith("VERIFIX_")}

    def load(self, **env: str):
        with patch.dict(os.environ, env, clear=True):
            os.environ.update(self._clean_env)
            return load_config(allow_frozen_overrides=False)

    def test_defaults_are_valid(self) -> None:
        config = self.load()
        self.assertEqual(config.product.brand, "VeriFix")
        self.assertEqual(config.branch.namespace, "verifix/")
        self.assertEqual(config.release.auto_branch, "release/auto")
        self.assertEqual(config.stage.total_seconds(), 870)
        self.assertEqual(config.sandbox.memory_mb(), 1024)
        self.assertEqual(config.frozen_overrides, ())

    def test_stage_timeout_sum_must_be_below_deadline(self) -> None:
        with self.assertRaises(ConfigValidationError) as ctx:
            self.load(VERIFIX_STAGE_GATE_READBACK_SECONDS="600")
        self.assertIn("stage.timeout", str(ctx.exception))

    def test_deadline_over_900_rejected(self) -> None:
        with self.assertRaises(ConfigValidationError) as ctx:
            self.load(VERIFIX_RUN_DEADLINE_SECONDS="901")
        self.assertIn("run.deadline_seconds", str(ctx.exception))

    def test_sandbox_memory_over_1g_rejected(self) -> None:
        with self.assertRaises(ConfigValidationError) as ctx:
            self.load(VERIFIX_SANDBOX_MEM="2g")
        self.assertIn("sandbox.mem", str(ctx.exception))

    def test_sandbox_cpu_over_one_rejected(self) -> None:
        with self.assertRaises(ConfigValidationError) as ctx:
            self.load(VERIFIX_SANDBOX_CPU="2")
        self.assertIn("sandbox.cpu", str(ctx.exception))

    def test_frozen_patch_limits_rejected(self) -> None:
        with self.assertRaises(ConfigValidationError) as ctx:
            self.load(VERIFIX_PATCH_MAX_LINES="31")
        self.assertIn("patch.max_lines", str(ctx.exception))

    def test_protected_branch_rejected(self) -> None:
        with self.assertRaises(ConfigValidationError) as ctx:
            self.load(VERIFIX_RELEASE_AUTO_BRANCH="main")
        self.assertIn("release.auto_branch", str(ctx.exception))

    def test_brand_change_does_not_move_namespace(self) -> None:
        config = self.load(VERIFIX_PRODUCT_BRAND="ShieldFix")
        self.assertEqual(config.product.brand, "ShieldFix")
        self.assertEqual(config.branch.namespace, "verifix/")
        self.assertEqual(config.release.auto_branch, "release/auto")

    def test_memory_parser(self) -> None:
        self.assertEqual(parse_memory_mb("1g"), 1024)
        self.assertEqual(parse_memory_mb("512m"), 512)
        with self.assertRaises(ValueError):
            parse_memory_mb("one-gig")


if __name__ == "__main__":
    unittest.main()