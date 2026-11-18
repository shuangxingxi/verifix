from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.pipeline import GateJudger, GateRunSnapshot, GateStageResult, RecordedPipelineClient
from app.adapters.repo import LocalRepoAdapter
from app.adapters.types import UpstreamUnavailable
from app.agents.critic.service import CriticService, CriticStatus
from app.agents.gatekeeper.service import GatekeeperService
from app.agents.patcher.service import PatcherService
from app.agents.reproducer.executor import LocalTestExecutor
from app.agents.reproducer.service import ReproducerService
from app.agents.reproducer.templates import render_test
from app.config import load_config
from app.domain.enums import DefectClass, FixParadigm, IssueStatus, ProofResult, Severity, SourceKind, VerdictConclusion
from app.domain.models import Alert, EnvSnapshot, GateResult, Issue, Location, Patch, Proof, Verdict
from app.orchestration.service import OrchestrationService
from app.orchestration.state_machine import Transition, TransitionContext
from app.repo.memory import MemoryStore
from app.tools.errors import ForbiddenBranchError
from app.tracing.service import ReachabilityService

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TARGET = PROJECT_ROOT / "verifix-target"


def make_issue(store: MemoryStore, issue_id: str, defect: DefectClass, file: str, line: int, rule_id: str,
               component: str | None = None, version: str | None = None) -> Issue:
    issue = Issue(
        issue_id=issue_id,
        repo="verifix-target",
        code_version="abc123",
        defect_class=defect,
        severity=Severity.HIGH,
        status=IssueStatus.RECEIVED,
        fingerprint=("f" * 63) + issue_id[-1],
    )
    store.add(issue)
    store.link_alert(
        issue_id,
        Alert(
            alert_ref=f"check:{issue_id}",
            source_kind=SourceKind.CHECK,
            rule_id=rule_id,
            location=Location(file=file, line=line, component=component, component_version=version),
            raw_severity=Severity.HIGH,
            snippet_fingerprint="s" * 64,
            defect_class=defect,
        ),
    )
    return issue


class ChainFixture:
    def __init__(self) -> None:
        self.config = load_config()
        self.store = MemoryStore()
        self.repo = LocalRepoAdapter()
        self.repo.load_from_directory(TARGET)
        self.reachability = ReachabilityService(self.store, self.config)
        self.reproducer = ReproducerService(self.store, LocalTestExecutor(), self.config)
        self.patcher = PatcherService(self.store, self.config)
        self.critic = CriticService(self.store, self.config, LocalTestExecutor())
        self.pipeline = RecordedPipelineClient.all_passed()
        self.gatekeeper = GatekeeperService(self.store, self.config, self.repo, self.pipeline)

    def prepare(self, issue_id: str, defect: DefectClass, file: str, line: int, rule_id: str,
                fixed_version: str | None = None):
        make_issue(self.store, issue_id, defect, file, line, rule_id,
                   component="requests" if defect is DefectClass.DEPENDENCY_CVE else None,
                   version="2.19.1" if defect is DefectClass.DEPENDENCY_CVE else None)
        if defect is DefectClass.DEPENDENCY_CVE:
            self._force_reachable(issue_id)
        else:
            self.reachability.analyze(self.store.get(issue_id), TARGET)
        repro = self.reproducer.reproduce(self.store.get(issue_id), TARGET)
        assert repro.status.value == "PROVEN", repro.message
        patch_outcome = self.patcher.patch(self.store.get(issue_id), TARGET, fixed_version=fixed_version)
        assert patch_outcome.status == "PATCHED", patch_outcome.message
        return self.store.get(issue_id), patch_outcome.patch, repro.proof, patch_outcome.candidate

    def _force_reachable(self, issue_id: str) -> None:
        from app.domain.enums import EventType

        orchestration = OrchestrationService(self.store, self.store, self.store)
        orchestration.apply(
            Transition.T1,
            TransitionContext(issue=self.store.get(issue_id)),
            EventType.INGEST,
            "normalizer",
        )
        verdict = Verdict(
            verdict_id=f"V-{issue_id}",
            issue_id=issue_id,
            conclusion=VerdictConclusion.REACHABLE,
            confidence=0.9,
            taint_path=["requirements.txt:dependency"],
            basis="dependency is imported by the application",
            decided_by="tracer",
        )
        self.store.add_verdict(verdict)
        orchestration.apply(
            Transition.T2,
            TransitionContext(issue=self.store.get(issue_id), verdict=verdict),
            EventType.VERDICT,
            "tracer",
        )


class CriticTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ChainFixture()

    def test_three_checks_and_audit_pass(self) -> None:
        issue, patch, proof, candidate = self.fixture.prepare("ISS-1", DefectClass.SQL_INJECTION, "app/main.py", 31, "py/sql-injection")
        critic = self.fixture.critic.evaluate(issue, patch, candidate, TARGET)
        self.assertIs(critic.status, CriticStatus.PASSED, critic.message)
        self.assertTrue(critic.red_green_paired)
        self.assertTrue(critic.regression_zero_fail)
        self.assertTrue(critic.anti_cheat_ok)
        self.assertTrue(all(item.verdict.value == "PASS" for item in critic.findings))

    def test_proof_fingerprint_mismatch_blocks(self) -> None:
        issue, patch, proof, candidate = self.fixture.prepare("ISS-2", DefectClass.SQL_INJECTION, "app/main.py", 31, "py/sql-injection")
        tampered = proof.model_copy(update={"fingerprint": "0" * 64})
        self.fixture.store.add_proof(tampered)
        critic = self.fixture.critic.evaluate(issue, patch, candidate, TARGET)
        self.assertIs(critic.status, CriticStatus.L2)
        self.assertFalse(critic.anti_cheat_ok)

    def test_backdoor_branch_is_rejected(self) -> None:
        issue, patch, proof, candidate = self.fixture.prepare("ISS-3", DefectClass.SQL_INJECTION, "app/main.py", 31, "py/sql-injection")
        poisoned = candidate
        from app.agents.patcher.templates import PatchCandidate

        poisoned = PatchCandidate(
            files=poisoned.files,
            diff=poisoned.diff + "\n@@ -40,1 +40,3 @@\n-    pass\n+    if token == \"dbg-9f3a2c\":\n+        return\n",
            lines_changed=poisoned.lines_changed + 2,
            files_changed=poisoned.files_changed,
            fix_paradigm=poisoned.fix_paradigm,
            strength=poisoned.strength,
            rationale=poisoned.rationale,
            referenced_files=poisoned.referenced_files,
        )
        critic = self.fixture.critic.evaluate(issue, patch, poisoned, TARGET)
        self.assertIs(critic.status, CriticStatus.L3, critic.message)


class GateJudgerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.proof = Proof(
            proof_id="P-1",
            issue_id="ISS-1",
            test_path="tests/security/test_x.py",
            pre_patch_result=ProofResult.FAIL,
            fingerprint="a" * 64,
            env_snapshot=EnvSnapshot(),
            generated_marker="AUTOGENERATED",
        )
        self.judger = GateJudger()

    def snapshot(self, proof_ok: bool = True, regression_ok: bool = True, coverage: float = 0.0, rescan: int = 0) -> GateRunSnapshot:
        return GateRunSnapshot(
            run_id="pipeline:r1",
            terminal=True,
            stages={
                "proof": GateStageResult("proof", proof_ok),
                "regression": GateStageResult("regression", regression_ok, coverage_delta_pp=coverage),
                "rescan": GateStageResult("rescan", True, new_alerts=rescan),
            },
        )

    def test_all_pass(self) -> None:
        gate = self.judger.judge("PA-1", self.proof, self.snapshot(), True)
        self.assertIs(gate.outcome.value, "PASSED")
        self.assertTrue(gate.red_green_paired)

    def test_coverage_boundary_minus_half_pp_passes(self) -> None:
        gate = self.judger.judge("PA-1", self.proof, self.snapshot(coverage=-0.5), True)
        self.assertTrue(gate.regression_zero_fail)
        self.assertIs(gate.outcome.value, "PASSED")

    def test_coverage_beyond_tolerance_fails(self) -> None:
        gate = self.judger.judge("PA-1", self.proof, self.snapshot(coverage=-0.51), True)
        self.assertFalse(gate.regression_zero_fail)
        self.assertIs(gate.outcome.value, "FAILED")

    def test_green_without_red_fails(self) -> None:
        proof = self.proof.model_copy(update={"pre_patch_result": ProofResult.PASS})
        gate = self.judger.judge("PA-1", proof, self.snapshot(), True)
        self.assertFalse(gate.red_green_paired)
        self.assertIs(gate.outcome.value, "FAILED")

    def test_rescan_new_alert_fails(self) -> None:
        gate = self.judger.judge("PA-1", self.proof, self.snapshot(rescan=1), True)
        self.assertIs(gate.outcome.value, "FAILED")


class RepoAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = LocalRepoAdapter()
        self.repo.load_from_directory(TARGET)

    def test_main_is_hard_rejected(self) -> None:
        with self.assertRaises(ForbiddenBranchError):
            self.repo.create_branch("verifix-target", "main", "abc")
        with self.assertRaises(ForbiddenBranchError):
            self.repo.merge_to_release_auto("verifix-target", "main")
        self.assertTrue(self.repo.violations)

    def test_publish_and_merge_to_release_auto(self) -> None:
        self.repo.create_branch("verifix-target", "verifix/ISS-1", "abc")
        self.repo.commit_files("verifix-target", "verifix/ISS-1", {"app/main.py": "x = 1"}, "fix")
        merged = self.repo.merge_to_release_auto("verifix-target", "verifix/ISS-1")
        self.assertEqual(merged.target, "release/auto")

    def test_delete_is_idempotent(self) -> None:
        self.repo.create_branch("verifix-target", "verifix/ISS-2", "abc")
        first = self.repo.delete_branch("verifix-target", "verifix/ISS-2")
        second = self.repo.delete_branch("verifix-target", "verifix/ISS-2")
        self.assertTrue(first.deleted)
        self.assertTrue(second.deleted)
        self.assertFalse(second.existed)


class GatekeeperTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ChainFixture()

    def test_l1_pipeline_opens_pr(self) -> None:
        issue, patch, proof, candidate = self.fixture.prepare("ISS-4", DefectClass.SQL_INJECTION, "app/main.py", 31, "py/sql-injection")
        critic = self.fixture.critic.evaluate(issue, patch, candidate, TARGET)
        outcome = self.fixture.gatekeeper.dispose(issue, patch, proof, candidate, critic, "run-4")
        self.assertEqual(outcome.status, "L1", outcome.message)
        self.assertIs(self.fixture.store.get("ISS-4").status, IssueStatus.DISPOSED_L1)
        self.assertEqual(len(self.fixture.repo.pull_requests), 1)
        disposition = self.fixture.store.disposition_for("ISS-4")
        self.assertIsNotNone(disposition)
        self.assertEqual(disposition.level.value, "L1")

    def test_l0_dependency_merges_release_auto(self) -> None:
        issue, patch, proof, candidate = self.fixture.prepare(
            "ISS-5", DefectClass.DEPENDENCY_CVE, "requirements.txt", 2, "dependency-cve", fixed_version="2.32.3"
        )
        critic = self.fixture.critic.evaluate(issue, patch, candidate, TARGET, test_paths=())
        self.assertIs(critic.status, CriticStatus.PASSED, critic.message)
        outcome = self.fixture.gatekeeper.dispose(issue, patch, proof, candidate, critic, "run-5")
        self.assertEqual(outcome.status, "L0", outcome.message)
        self.assertEqual(outcome.merged_into, "release/auto")
        self.assertEqual(self.fixture.repo.merged[0].target, "release/auto")

    def test_gate_failure_rolls_back_to_l2(self) -> None:
        issue, patch, proof, candidate = self.fixture.prepare("ISS-6", DefectClass.SQL_INJECTION, "app/main.py", 31, "py/sql-injection")
        self.fixture.pipeline.stages["regression"] = GateStageResult("regression", True, coverage_delta_pp=-0.9)
        critic = self.fixture.critic.evaluate(issue, patch, candidate, TARGET)
        outcome = self.fixture.gatekeeper.dispose(issue, patch, proof, candidate, critic, "run-6")
        self.assertEqual(outcome.status, "L2", outcome.message)
        self.assertIs(self.fixture.store.get("ISS-6").status, IssueStatus.DISPOSED_L2)

    def test_gate_timeout_rolls_back(self) -> None:
        issue, patch, proof, candidate = self.fixture.prepare("ISS-7", DefectClass.SQL_INJECTION, "app/main.py", 31, "py/sql-injection")
        self.fixture.pipeline.timeout = True
        critic = self.fixture.critic.evaluate(issue, patch, candidate, TARGET)
        outcome = self.fixture.gatekeeper.dispose(issue, patch, proof, candidate, critic, "run-7")
        self.assertEqual(outcome.status, "L2", outcome.message)

    def test_trigger_failure_is_integration_error(self) -> None:
        issue, patch, proof, candidate = self.fixture.prepare("ISS-8", DefectClass.SQL_INJECTION, "app/main.py", 31, "py/sql-injection")
        self.fixture.pipeline.fail_trigger = True
        critic = self.fixture.critic.evaluate(issue, patch, candidate, TARGET)
        outcome = self.fixture.gatekeeper.dispose(issue, patch, proof, candidate, critic, "run-8")
        self.assertEqual(outcome.status, "INTEGRATION_ERROR", outcome.message)
        self.assertIsNotNone(outcome.error_code)
        self.assertEqual(outcome.error_code.value, "VF-5001")


if __name__ == "__main__":
    unittest.main()