from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import AppConfig, ConfigValidationError, RealscanConfig
from app.realscan.policy import PolicyFile, PolicyInvalidError, RunSpecBuilder

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "sandbox" / "spec.json"


def _policy_payload() -> dict:
    return json.loads(POLICY.read_text(encoding="utf-8"))


class PolicyLoadTest(unittest.TestCase):
    def test_pol01_loads_eleven_keys_and_five_cases(self) -> None:
        policy = PolicyFile.load(POLICY)
        self.assertEqual(policy.policy_version, "1.0.0")
        self.assertEqual(len(policy.isolation), 11)
        self.assertEqual(len(policy.escape_cases), 5)
        self.assertEqual(policy.sha256, "bd62277bbae9d6ed146e92231b36bc2a3e5462e5aca715144ad8332384e36168")

    def test_pol02_rejects_missing_key(self) -> None:
        with TemporaryDirectory() as tmp:
            payload = _policy_payload()
            payload["isolation"].pop("tmpfs")
            path = Path(tmp) / "spec.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(PolicyInvalidError):
                PolicyFile.load(path)

    def test_pol03_rejects_network_widening(self) -> None:
        with TemporaryDirectory() as tmp:
            payload = _policy_payload()
            payload["isolation"]["network"] = "bridge"
            path = Path(tmp) / "spec.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(PolicyInvalidError):
                PolicyFile.load(path)

    def test_pol04_runspec_cannot_widen_network_or_readonly(self) -> None:
        policy = PolicyFile.load(POLICY)
        spec = RunSpecBuilder(policy, "vf-verify-ut01").build(ROOT, stdin_mode=True)
        self.assertIn("--network=none", spec.argv)
        self.assertIn("--read-only", spec.argv)
        self.assertIn("--cap-drop=ALL", spec.argv)
        self.assertIn("--security-opt=no-new-privileges", spec.argv)
        self.assertIn("--user=10001:10001", spec.argv)
        self.assertIn("--memory=1024m", spec.argv)
        self.assertIn("--pids-limit=128", spec.argv)
        self.assertIn("--entrypoint", spec.argv)
        self.assertEqual(len([item for item in spec.argv if item.startswith("--tmpfs=")]), 2)
        self.assertFalse(any(item == "--network" for item in spec.argv))
        self.assertFalse(any(item.startswith("--network=host") for item in spec.argv))
        self.assertFalse(any(item.startswith("--network=bridge") for item in spec.argv))
        self.assertFalse(any(item == "--privileged" for item in spec.argv))

    def test_pol05_config_has_no_network_widening_and_budget_limits(self) -> None:
        defaults = AppConfig()
        dumped = defaults.realscan.model_dump()
        self.assertNotIn("network", dumped)
        self.assertEqual(len(dumped), 23)
        self.assertTrue(dumped["p4_05_enabled"])
        self.assertTrue(dumped["allow_host_fallback"])
        with self.assertRaises(Exception):
            AppConfig(realscan=RealscanConfig(probe_budget_seconds=20))
        with self.assertRaises(Exception):
            AppConfig(realscan=RealscanConfig(constraint_budget_seconds=200))
        with self.assertRaises(Exception):
            AppConfig(realscan=RealscanConfig(listen_port=-1))


class ConfigRealscanTest(unittest.TestCase):
    def test_rejects_empty_images(self) -> None:
        with self.assertRaises(ValueError):
            AppConfig(realscan=RealscanConfig(sandbox_images=[]))
        with self.assertRaises(ValueError):
            AppConfig(realscan=RealscanConfig(target_images=[]))

    def test_rejects_evidence_root_in_expected(self) -> None:
        with self.assertRaises(ValueError):
            AppConfig(realscan=RealscanConfig(evidence_root="eval/expected/pack"))

    def test_rejects_parent_child_cases_expected(self) -> None:
        with self.assertRaises(ValueError):
            AppConfig(realscan=RealscanConfig(cases_dir="eval", expected_dir="eval/expected"))

    def test_default_config_serializes(self) -> None:
        payload = AppConfig().model_dump()
        self.assertIn("realscan", payload)
        self.assertEqual(payload["realscan"]["runtime_transport"], "auto")
        self.assertEqual(payload["realscan"]["q_defaults"]["Q-04"], "C")


if __name__ == "__main__":
    unittest.main()