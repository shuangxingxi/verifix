from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(TESTS))

from app.selfcheck.checks import d3_evidence
from app.selfcheck.context import SelfcheckContext
from app.selfcheck.models import Status
from support.selfcheck_fixtures import append_document, write_repo


class EvidenceCheckTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        fixture = write_repo(self.root)
        self.evidence_id = str(fixture["evidence_id"])
        self.pack = self.root / ".evidence" / "sandbox-realscan" / self.evidence_id
        self.ctx = SelfcheckContext(self.root)

    def test_summary_check_passes_on_real_pack(self) -> None:
        result = d3_evidence._d3_3(self.ctx)
        self.assertIs(result.status, Status.PASS)
        self.assertIn("100%", result.output_summary)

    def test_tampered_file_detected_with_path(self) -> None:
        (self.pack / "runtime_facts.json").write_text('{"image_id": "tampered"}', encoding="utf-8")
        result = d3_evidence._d3_3(self.ctx)
        self.assertIs(result.status, Status.BLOCKED)
        self.assertEqual(result.sub_reason, "TAMPERED")
        self.assertIn("runtime_facts.json", result.output_summary)

    def test_missing_digest_is_missing_not_tampered(self) -> None:
        (self.pack / "EVIDENCE.sha256").unlink()
        result = d3_evidence._d3_3(self.ctx)
        self.assertIs(result.status, Status.BLOCKED)
        self.assertEqual(result.sub_reason, "MISSING")

    def test_three_way_digest_conflict_detected(self) -> None:
        (self.pack / "runtime_facts.json").write_text('{"image_id": "tampered"}', encoding="utf-8")
        result = d3_evidence._d3_4(self.ctx)
        self.assertIs(result.status, Status.BLOCKED)
        self.assertEqual(result.sub_reason, "DIGEST_MISMATCH")

    def test_orphan_rate_warns_without_reference(self) -> None:
        result = d3_evidence._d3_2(self.ctx)
        self.assertIs(result.status, Status.WARNING)
        self.assertEqual(result.sub_reason, "ORPHAN_RATE_EXCEEDED")

    def test_orphan_rate_passes_when_referenced(self) -> None:
        append_document(
            self.root,
            "docs/devlog/m7-target-realscan-report.md",
            f"- 证据：`.evidence/sandbox-realscan/{self.evidence_id}`",
        )
        result = d3_evidence._d3_2(self.ctx)
        self.assertIs(result.status, Status.PASS)

    def test_unresolved_reference_is_blocked(self) -> None:
        append_document(
            self.root,
            "docs/devlog/m12-closure-and-blockers.md",
            "- 证据：`VER-20260101T000000+0800-dead`",
        )
        result = d3_evidence._d3_5(self.ctx)
        self.assertIs(result.status, Status.BLOCKED)
        self.assertEqual(result.sub_reason, "UNRESOLVED_REFERENCE")
        self.assertIn("m12-closure-and-blockers.md", result.output_summary)

    def test_no_reference_is_unverified_not_pass(self) -> None:
        result = d3_evidence._d3_5(self.ctx)
        self.assertIs(result.status, Status.UNVERIFIED)
        self.assertEqual(result.sub_reason, "NO_REFERENCE")

    def test_claim_without_evidence_is_blocked(self) -> None:
        result = d3_evidence._d3_1(self.ctx)
        self.assertIs(result.status, Status.BLOCKED)
        self.assertEqual(result.sub_reason, "CLAIM_WITHOUT_EVIDENCE")


    def test_history_digest_positive_negative_and_missing(self) -> None:
        import hashlib

        from app.realscan.evidence import verify_history_digests

        target = self.root / "docs" / "devlog" / "custom-history.md"
        target.write_text("原始内容", encoding="utf-8")
        expected = hashlib.sha256(target.read_bytes()).hexdigest()
        baseline = {"docs/devlog/custom-history.md": expected}
        self.assertEqual(verify_history_digests(self.root, baseline), [])
        target.write_text("原始内容!", encoding="utf-8")
        violations = verify_history_digests(self.root, baseline)
        self.assertEqual(len(violations), 1)
        self.assertTrue(violations[0].startswith("docs/devlog/custom-history.md:"))
        self.assertEqual(
            verify_history_digests(self.root, {"docs/devlog/none.md": "0" * 64}),
            ["docs/devlog/none.md:missing"],
        )

    def test_d3_group_never_writes(self) -> None:
        before = self.ctx.tree_digest()
        for handler in (
            d3_evidence._d3_1,
            d3_evidence._d3_2,
            d3_evidence._d3_3,
            d3_evidence._d3_4,
            d3_evidence._d3_5,
            d3_evidence._d3_6,
            d3_evidence._d3_7,
        ):
            handler(self.ctx)
        self.assertEqual(before, self.ctx.tree_digest())


if __name__ == "__main__":
    unittest.main()