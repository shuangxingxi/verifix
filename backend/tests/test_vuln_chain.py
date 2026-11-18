from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.types import ComponentRef, VersionRange, compare_versions, stricter_range
from app.adapters.vuln import CnvdMirrorSource, OsvSource, VulnSourceChain
from app.domain.enums import SourceKind


class VersionRangeTest(unittest.TestCase):
    def test_compare_versions(self) -> None:
        self.assertEqual(compare_versions("2.19.1", "2.19.2"), -1)
        self.assertEqual(compare_versions("2.20.0", "2.20"), 0)
        self.assertEqual(compare_versions("1.0.0", "0.9.12"), 1)

    def test_contains(self) -> None:
        affected = VersionRange(introduced_inclusive="2.0.0", fixed_exclusive="2.20.0")
        self.assertTrue(affected.contains("2.19.1"))
        self.assertFalse(affected.contains("1.9.9"))
        self.assertFalse(affected.contains("2.20.0"))

    def test_stricter_range_expands_coverage(self) -> None:
        left = VersionRange("2.0.0", "2.20.0")
        right = VersionRange("1.0.0", "2.32.3")
        merged = stricter_range(left, right)
        self.assertEqual(merged.introduced_inclusive, "1.0.0")
        self.assertEqual(merged.fixed_exclusive, "2.32.3")


class VulnChainTest(unittest.TestCase):
    def setUp(self) -> None:
        self.osv = OsvSource(advisory={("requests", "2.19.1"): VersionRange("2.0.0", "2.20.0")})
        self.cnvd = CnvdMirrorSource(advisory={"requests": VersionRange("1.0.0", "2.32.3")})

    def test_conflict_takes_stricter_range_and_keeps_sources(self) -> None:
        chain = VulnSourceChain([self.osv, self.cnvd])
        outcome = chain.query(ComponentRef("requests", "2.19.1"))
        self.assertIsNotNone(outcome.result)
        result = outcome.result
        self.assertEqual(result.affected.introduced_inclusive, "1.0.0")
        self.assertEqual(result.affected.fixed_exclusive, "2.32.3")
        self.assertTrue(result.conflict)
        self.assertIn("OSV", result.contributing_sources)
        self.assertIn("CNVD", result.contributing_sources)
        self.assertTrue(result.needs_human)
        self.assertEqual(len(result.raw_ranges), 2)

    def test_osv_failure_falls_back_to_cnvd(self) -> None:
        self.osv.fail = True
        chain = VulnSourceChain([self.osv, self.cnvd])
        outcome = chain.query(ComponentRef("requests", "2.19.1"))
        self.assertTrue(outcome.degraded)
        self.assertIn("CNVD", outcome.message)
        self.assertIs(outcome.result.source, SourceKind.CNVD)
        self.assertTrue(outcome.result.needs_human)

    def test_both_sources_unavailable(self) -> None:
        self.osv.fail = True
        self.cnvd.fail = True
        outcome = VulnSourceChain([self.osv, self.cnvd]).query(ComponentRef("requests", "2.19.1"))
        self.assertIsNone(outcome.result)
        self.assertTrue(outcome.degraded)
        self.assertIn("均不可用", outcome.message)

    def test_consistent_ranges_are_not_flagged_as_conflict(self) -> None:
        cnvd = CnvdMirrorSource(advisory={"requests": VersionRange("2.0.0", "2.20.0")})
        outcome = VulnSourceChain([self.osv, cnvd]).query(ComponentRef("requests", "2.19.1"))
        self.assertFalse(outcome.result.conflict)
        self.assertEqual(outcome.result.affected.introduced_inclusive, "2.0.0")

    def test_is_affected(self) -> None:
        chain = VulnSourceChain([self.osv, self.cnvd])
        self.assertTrue(chain.is_affected(ComponentRef("requests", "2.19.1")))
        self.assertFalse(chain.is_affected(ComponentRef("requests", "2.99.0")))


if __name__ == "__main__":
    unittest.main()