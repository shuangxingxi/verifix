from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import AppConfig
from app.domain.enums import MetricId
from app.metrics.rules.m9 import M9Rule, M9TrustPolicy

NOW = datetime(2027, 1, 6, 12, 0, tzinfo=timezone.utc)


def runtime_sample(**overrides) -> dict:
    sample = {
        "sampled_at": NOW - timedelta(seconds=10),
        "continuous_seconds": 86400.0,
        "interruptions": 0,
        "heartbeat_ok": True,
        "tracker_started_at": NOW - timedelta(seconds=86410),
        "origin": "runtime",
        "manual_interventions": 0,
    }
    sample.update(overrides)
    return sample


class M9TrustPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = M9TrustPolicy()

    def test_all_six_conditions_trusted(self) -> None:
        verdict = self.policy.evaluate([runtime_sample()], NOW)
        self.assertTrue(verdict.trusted)
        self.assertEqual(verdict.reason, "")

    def test_fixture_origin_unverified(self) -> None:
        verdict = self.policy.evaluate([runtime_sample(origin="fixture")], NOW)
        self.assertFalse(verdict.trusted)
        self.assertEqual(verdict.reason, "FIXTURE_ORIGIN")

    def test_missing_tracker_start_unverified(self) -> None:
        verdict = self.policy.evaluate([runtime_sample(tracker_started_at=None)], NOW)
        self.assertEqual(verdict.reason, "MISSING_TRACKER_START")

    def test_interruption_unverified(self) -> None:
        verdict = self.policy.evaluate([runtime_sample(interruptions=1)], NOW)
        self.assertEqual(verdict.reason, "INTERRUPTED")

    def test_manual_intervention_unverified(self) -> None:
        verdict = self.policy.evaluate([runtime_sample(manual_interventions=1)], NOW)
        self.assertEqual(verdict.reason, "MANUAL_INTERVENTION")

    def test_insufficient_duration_unverified(self) -> None:
        verdict = self.policy.evaluate([runtime_sample(continuous_seconds=86399.0)], NOW)
        self.assertEqual(verdict.reason, "INSUFFICIENT_DURATION")

    def test_sample_gap_unverified(self) -> None:
        samples = [
            runtime_sample(sampled_at=NOW - timedelta(seconds=200)),
            runtime_sample(sampled_at=NOW - timedelta(seconds=10)),
        ]
        verdict = self.policy.evaluate(samples, NOW)
        self.assertEqual(verdict.reason, "SAMPLE_GAP")

    def test_stale_sample_unverified(self) -> None:
        verdict = self.policy.evaluate([runtime_sample(sampled_at=NOW - timedelta(seconds=151))], NOW)
        self.assertEqual(verdict.reason, "SAMPLE_STALE")

    def test_duration_skew_unverified(self) -> None:
        verdict = self.policy.evaluate(
            [runtime_sample(tracker_started_at=NOW - timedelta(seconds=86471))], NOW
        )
        self.assertEqual(verdict.reason, "DURATION_SKEW")

    def test_missing_samples_unverified(self) -> None:
        verdict = self.policy.evaluate([], NOW)
        self.assertEqual(verdict.reason, "MISSING_RUNTIME_EVIDENCE")

    def test_boundary_values_are_trusted(self) -> None:
        samples = [
            runtime_sample(
                sampled_at=NOW - timedelta(seconds=150),
                tracker_started_at=NOW - timedelta(seconds=150 + 86400),
            ),
            runtime_sample(
                sampled_at=NOW - timedelta(seconds=30),
                tracker_started_at=NOW - timedelta(seconds=30 + 86400),
            ),
        ]
        verdict = self.policy.evaluate(samples, NOW)
        self.assertTrue(verdict.trusted)

    def test_rule_marks_unverified_details(self) -> None:
        from app.metrics.collectors.main_flow import CollectedEvidence
        from app.metrics.definitions import DefinitionRegistry

        evidence = CollectedEvidence(
            window="2026-12",
            tier=__import__("app.domain.enums", fromlist=["StageTier"]).StageTier.PRELIMINARY,
            window_start=NOW - timedelta(days=1),
            window_end=NOW,
            self_run_sample=runtime_sample(origin="fixture"),
            self_run_samples=[runtime_sample(origin="fixture")],
        )
        definition = DefinitionRegistry().all_effective(NOW)[MetricId.M9]
        result = M9Rule().evaluate(evidence, definition, NOW)
        self.assertEqual(result.covered_count, 0)
        self.assertTrue(result.details["unverified"])
        self.assertIn("夹具", result.details["unverified_reason"])


class M9ThresholdConfigTest(unittest.TestCase):
    def test_relaxed_gap_fails_startup(self) -> None:
        with self.assertRaises(ValueError):
            AppConfig(metrics={"m9_max_sample_gap_seconds": 300})

    def test_relaxed_age_fails_startup(self) -> None:
        with self.assertRaises(ValueError):
            AppConfig(metrics={"m9_max_sample_age_seconds": 300})

    def test_relaxed_duration_fails_startup(self) -> None:
        with self.assertRaises(ValueError):
            AppConfig(metrics={"m9_min_continuous_seconds": 3600})

    def test_relaxed_skew_fails_startup(self) -> None:
        with self.assertRaises(ValueError):
            AppConfig(metrics={"m9_max_tracker_skew_seconds": 120})


if __name__ == "__main__":
    unittest.main()