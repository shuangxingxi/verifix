from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.adapters.pipeline import RecordedPipelineClient
from app.adapters.repo import LocalRepoAdapter
from app.agents.critic.service import CriticService
from app.agents.gatekeeper.service import GatekeeperService
from app.agents.patcher.service import PatcherService
from app.agents.reproducer.executor import LocalTestExecutor
from app.agents.reproducer.service import ReproducerService
from app.api.envelope import ApiError
from app.config import load_config
from app.container import AppContainer
from app.domain.enums import DefectClass, EventType, IssueStatus, Severity, StepKind, StepStatus
from app.intake.auth import AuthGuard
from app.intake.service import IntakeService, ManualIssueInput
from app.main import create_app
from app.orchestration.state_machine import Transition, TransitionContext
from app.tracing.service import ReachabilityService

TARGET = Path(__file__).resolve().parents[2] / "verifix-target"


def _manual_payload() -> dict:
    return {
        "repo": "verifix-target",
        "code_version": "abc123",
        "rule_id": "py/sql-injection",
        "severity": "HIGH",
        "file": "app/main.py",
        "line": 31,
        "defect_class": "C02",
        "snippet": "SELECT * FROM users WHERE id = '%s' % uid",
    }


def _intake_payload() -> ManualIssueInput:
    return ManualIssueInput(
        repo="verifix-target",
        code_version="abc123",
        rule_id="py/sql-injection",
        severity=Severity.HIGH,
        file="app/main.py",
        line=31,
        defect_class=DefectClass.SQL_INJECTION,
        snippet="SELECT * FROM users WHERE id = '%s' % uid",
    )


class FiveEntryPipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config()
        self.box = AppContainer(self.config)
        self.client = TestClient(create_app(self.config, self.box))
        self.guard = AuthGuard(secret="dev-secret")
        self.store = self.box.store

    def _webhook(self, body: bytes, signature: str | None = None):
        headers = {"content-type": "application/json"}
        if signature is not None:
            headers["x-codearts-signature"] = signature
        return self.client.post("/api/v1/webhooks/codearts-repo", content=body, headers=headers)

    def test_five_entries_are_accepted(self) -> None:
        manual = self.client.post("/api/v1/issues", json=_manual_payload())
        self.assertLess(manual.status_code, 300, manual.text)

        body = json.dumps({"repo": "verifix-target", "branch": "verifix/ISS-1", "base_sha": "abc", "action": "merged"}).encode("utf-8")
        webhook = self._webhook(body, self.guard.sign(body))
        self.assertEqual(webhook.status_code, 202)

        cve = self.client.post(
            "/api/v1/triggers/cve",
            json={
                "repo": "verifix-target",
                "code_version": "v1",
                "package": "requests",
                "current_version": "2.19.1",
                "fixed_version": "2.20.0",
                "severity": "high",
            },
        )
        self.assertEqual(cve.status_code, 202)
        self.assertTrue(cve.json()["data"]["issue_id"].startswith("ISS-"))

        runtime = self.client.post(
            "/api/v1/runtime/alerts",
            json={
                "repo": "verifix-target",
                "code_version": "v1",
                "rule_id": "py/command-injection",
                "file": "app/main.py",
                "line": 81,
                "severity": "high",
                "snippet": "os.popen('ping ' + host)",
                "evidence_ref": "runtime:ev-1",
            },
        )
        self.assertEqual(runtime.status_code, 202)

        scheduled = self.client.post(
            "/api/v1/triggers/scheduled",
            json={"repo": "verifix-target", "window": "2026-11-14T16", "idempotency_key": "sched-1"},
        )
        self.assertEqual(scheduled.status_code, 202)
        self.assertFalse(scheduled.json()["data"]["duplicate"])

    def test_duplicate_webhook_replay_has_no_side_effects(self) -> None:
        body = json.dumps({"repo": "verifix-target", "branch": "verifix/ISS-1", "base_sha": "abc", "action": "merged"}).encode("utf-8")
        signature = self.guard.sign(body)
        issues_before = len(self.store.issues)
        pending_before = list(self.store.pending())
        first = self._webhook(body, signature)
        second = self._webhook(body, signature)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 202)
        self.assertEqual(first.json()["data"], second.json()["data"])
        self.assertEqual(len(self.store.issues), issues_before)
        self.assertEqual(list(self.store.pending()), pending_before)

    def test_scheduled_same_window_is_idempotent(self) -> None:
        payload = {"repo": "verifix-target", "window": "2026-11-14T16", "idempotency_key": "sched-2"}
        first = self.client.post("/api/v1/triggers/scheduled", json=payload)
        second = self.client.post("/api/v1/triggers/scheduled", json=payload)
        self.assertEqual(first.status_code, 202)
        self.assertFalse(first.json()["data"]["duplicate"])
        self.assertTrue(second.json()["data"]["duplicate"])
        self.assertEqual(first.json()["data"]["run_id"], second.json()["data"]["run_id"])

    def test_manual_retry_enqueues_without_state_regression(self) -> None:
        intake = IntakeService(self.store, self.config)
        submitted = intake.submit_manual(_intake_payload())
        status_before = self.store.get(submitted.issue_id).status
        response = self.client.post(f"/api/v1/issues/{submitted.issue_id}/retry", headers={"x-actor": "operator"})
        self.assertLess(response.status_code, 300, response.text)
        pending = self.store.pending()
        self.assertTrue(any(key.startswith(f"retry:{submitted.issue_id}") for key in pending), pending)
        self.assertIs(self.store.get(submitted.issue_id).status, status_before)
        self.assertIs(status_before, IssueStatus.RECEIVED)

    def test_outbox_resume_is_idempotent_and_keeps_evidence(self) -> None:
        intake = IntakeService(self.store, self.config)
        submitted = intake.submit_manual(_intake_payload())
        pending = self.store.pending()
        self.assertEqual(pending, [f"triage:{submitted.issue_id}"])
        self.store.mark_done(pending[0])
        self.store.mark_done(pending[0])
        self.assertEqual(self.store.pending(), [])
        events = self.store.list_for_run(submitted.run_id)
        self.assertGreaterEqual(len(events), 1)
        self.assertEqual(len(self.store.get_run(submitted.run_id).steps), 7)
        self.assertTrue(self.store.verify_chain(submitted.run_id))

    # ---- §13.2 五入口 -> 处置全链路 / 重放 / 中断续跑 ----

    def _submit_manual(self) -> str:
        submitted = self.client.post("/api/v1/issues", json=_manual_payload())
        self.assertEqual(submitted.status_code, 202, submitted.text)
        return submitted.json()["data"]["issue_id"]

    def _chain_services(self, store):
        repo = LocalRepoAdapter()
        repo.load_from_directory(TARGET)
        reachability = ReachabilityService(store, self.config)
        reproducer = ReproducerService(store, LocalTestExecutor(), self.config)
        patcher = PatcherService(store, self.config)
        critic = CriticService(store, self.config, LocalTestExecutor())
        gatekeeper = GatekeeperService(store, self.config, repo, RecordedPipelineClient.all_passed())
        return repo, reachability, reproducer, patcher, critic, gatekeeper

    def _drive_to_l1_disposition(self, issue_id: str):
        repo, reachability, reproducer, patcher, critic, gatekeeper = self._chain_services(self.store)
        reachability.analyze(self.store.get(issue_id), TARGET)
        repro = reproducer.reproduce(self.store.get(issue_id), TARGET)
        self.assertEqual(repro.status.value, "PROVEN", repro.message)
        patch_outcome = patcher.patch(self.store.get(issue_id), TARGET)
        self.assertEqual(patch_outcome.status, "PATCHED", patch_outcome.message)
        critic_outcome = critic.evaluate(
            self.store.get(issue_id), patch_outcome.patch, patch_outcome.candidate, TARGET
        )
        gate_outcome = gatekeeper.dispose(
            self.store.get(issue_id),
            patch_outcome.patch,
            repro.proof,
            patch_outcome.candidate,
            critic_outcome,
            f"run-{issue_id}",
        )
        return repo, repro, patch_outcome, gate_outcome

    def test_manual_entry_reaches_l1_disposition_with_full_evidence(self) -> None:
        issue_id = self._submit_manual()
        repo, reachability, reproducer, patcher, critic, gatekeeper = self._chain_services(self.store)

        reachability.analyze(self.store.get(issue_id), TARGET)
        self.assertIs(self.store.get(issue_id).status, IssueStatus.REACHABLE)
        verdict = self.store.effective(issue_id)
        self.assertIsNotNone(verdict)
        self.assertEqual(verdict.conclusion.value, "REACHABLE")
        self.assertTrue(verdict.taint_path)

        repro = reproducer.reproduce(self.store.get(issue_id), TARGET)
        self.assertEqual(repro.status.value, "PROVEN", repro.message)
        self.assertIs(self.store.get(issue_id).status, IssueStatus.PROVEN)

        patch_outcome = patcher.patch(self.store.get(issue_id), TARGET)
        self.assertEqual(patch_outcome.status, "PATCHED", patch_outcome.message)
        critic_outcome = critic.evaluate(
            self.store.get(issue_id), patch_outcome.patch, patch_outcome.candidate, TARGET
        )
        gate_outcome = gatekeeper.dispose(
            self.store.get(issue_id),
            patch_outcome.patch,
            repro.proof,
            patch_outcome.candidate,
            critic_outcome,
            f"run-{issue_id}",
        )

        self.assertEqual(gate_outcome.status, "L1", gate_outcome.message)
        self.assertIs(self.store.get(issue_id).status, IssueStatus.DISPOSED_L1)

        disposition = self.store.disposition_for(issue_id)
        self.assertEqual(disposition.level.value, "L1")
        self.assertEqual(disposition.reason_code, "GATE_PASSED")
        self.assertTrue(disposition.evidence_ref)
        self.assertIsNotNone(disposition.ready_at)

        self.assertEqual(list(repo.branches), [f"verifix/{issue_id}"])
        self.assertEqual([pr.source for pr in repo.pull_requests], [f"verifix/{issue_id}"])
        self.assertEqual([pr.target for pr in repo.pull_requests], ["main"])
        self.assertEqual(len(repo.merged), 0)

        run = self.store.run_for_issue(issue_id)
        self.assertTrue(self.store.verify_chain(run.run_id))
        done_kinds = {step.kind for step in run.steps if step.status is StepStatus.DONE}
        self.assertLessEqual(
            {
                StepKind.VERDICT,
                StepKind.PROOF,
                StepKind.PATCH,
                StepKind.AUDIT,
                StepKind.DISPOSITION,
            },
            done_kinds,
        )
        self.assertIsNotNone(self.store.proof_for(issue_id))
        self.assertEqual(len(self.store.patch_attempts_for(issue_id)), 1)
        self.assertEqual(len(self.store.disposition_history_for(issue_id)), 1)
        gate_attempts = self.store.gate_attempts_for(patch_outcome.patch.patch_id)
        self.assertEqual(len(gate_attempts), 1)
        self.assertEqual(gate_attempts[0].outcome.value, "PASSED")
        self.assertTrue(gate_attempts[0].red_green_paired)
        self.assertTrue(gate_attempts[0].regression_zero_fail)

        view = self.client.get(f"/api/v1/issues/{issue_id}/disposition")
        self.assertEqual(view.status_code, 200, view.text)
        self.assertEqual(view.json()["data"]["level"], "L1")
        self.assertTrue(view.json()["data"]["conclusion_trusted"])

    def test_webhook_replay_after_disposition_has_no_duplicate_side_effects(self) -> None:
        issue_id = self._submit_manual()
        repo, _repro, _patch, gate_outcome = self._drive_to_l1_disposition(issue_id)
        self.assertEqual(gate_outcome.status, "L1", gate_outcome.message)
        run = self.store.run_for_issue(issue_id)

        before = {
            "issues": len(self.store.issues),
            "branches": len(repo.branches),
            "pull_requests": len(repo.pull_requests),
            "merged": len(repo.merged),
            "dispositions": len(self.store.disposition_history_for(issue_id)),
            "events": len(self.store.list_for_run(run.run_id)),
            "status": self.store.get(issue_id).status,
            "pending": list(self.store.pending()),
        }

        body = json.dumps(
            {"repo": "verifix-target", "branch": f"verifix/{issue_id}", "base_sha": "abc", "action": "merged"}
        ).encode("utf-8")
        signature = self.guard.sign(body)
        first = self._webhook(body, signature)
        second = self._webhook(body, signature)

        self.assertEqual(first.status_code, 202, first.text)
        self.assertEqual(second.status_code, 202, second.text)
        self.assertEqual(first.json()["data"], second.json()["data"])

        after = {
            "issues": len(self.store.issues),
            "branches": len(repo.branches),
            "pull_requests": len(repo.pull_requests),
            "merged": len(repo.merged),
            "dispositions": len(self.store.disposition_history_for(issue_id)),
            "events": len(self.store.list_for_run(run.run_id)),
            "status": self.store.get(issue_id).status,
            "pending": list(self.store.pending()),
        }
        self.assertEqual(after, before)
        self.assertIs(self.store.get(issue_id).status, IssueStatus.DISPOSED_L1)
        self.assertTrue(self.store.verify_chain(run.run_id))

    def test_resume_after_interruption_keeps_status_and_evidence(self) -> None:
        issue_id = self._submit_manual()
        _repo, reachability, reproducer, _patcher, _critic, _gatekeeper = self._chain_services(self.store)
        reachability.analyze(self.store.get(issue_id), TARGET)
        repro = reproducer.reproduce(self.store.get(issue_id), TARGET)
        self.assertEqual(repro.status.value, "PROVEN", repro.message)

        status_at_interrupt = self.store.get(issue_id).status
        proof_at_interrupt = self.store.proof_for(issue_id)
        run = self.store.run_for_issue(issue_id)
        events_at_interrupt = len(self.store.list_for_run(run.run_id))
        self.assertIn(f"triage:{issue_id}", self.store.pending())

        # 重启：重新装配组件并重放 Outbox 中未完成的 triage 任务
        repo, _reachability, _reproducer, patcher, critic, gatekeeper = self._chain_services(self.store)
        for key in list(self.store.pending()):
            self.store.mark_done(key)

        self.assertIs(self.store.get(issue_id).status, status_at_interrupt)
        self.assertEqual(self.store.proof_for(issue_id).model_dump(), proof_at_interrupt.model_dump())
        self.assertEqual(len(self.store.list_for_run(run.run_id)), events_at_interrupt)
        self.assertEqual(self.store.pending(), [])

        # 重放已完成的迁移必须被状态机拒绝，证明状态不会回退
        with self.assertRaises(ApiError) as regressed:
            self.box.orchestration().apply(
                Transition.T1,
                TransitionContext(issue=self.store.get(issue_id)),
                EventType.INGEST,
                "replay",
            )
        self.assertIn("illegal source state", regressed.exception.detail)
        self.assertIs(self.store.get(issue_id).status, status_at_interrupt)

        patch_outcome = patcher.patch(self.store.get(issue_id), TARGET)
        self.assertEqual(patch_outcome.status, "PATCHED", patch_outcome.message)
        critic_outcome = critic.evaluate(
            self.store.get(issue_id), patch_outcome.patch, patch_outcome.candidate, TARGET
        )
        gate_outcome = gatekeeper.dispose(
            self.store.get(issue_id),
            patch_outcome.patch,
            self.store.proof_for(issue_id),
            patch_outcome.candidate,
            critic_outcome,
            f"run-{issue_id}",
        )

        self.assertEqual(gate_outcome.status, "L1", gate_outcome.message)
        self.assertIs(self.store.get(issue_id).status, IssueStatus.DISPOSED_L1)
        self.assertEqual(self.store.proof_for(issue_id).proof_id, proof_at_interrupt.proof_id)
        self.assertEqual(len(self.store.patch_attempts_for(issue_id)), 1)
        self.assertEqual(list(repo.branches), [f"verifix/{issue_id}"])
        self.assertTrue(self.store.verify_chain(run.run_id))

        steps = {step.kind: step.status for step in self.store.run_for_issue(issue_id).steps}
        for kind in (StepKind.VERDICT, StepKind.PROOF, StepKind.PATCH, StepKind.AUDIT, StepKind.DISPOSITION):
            self.assertIs(steps[kind], StepStatus.DONE)

    def test_disposition_api_rejects_unresolvable_run_evidence(self) -> None:
        issue_id = self._submit_manual()
        _repo, _repro, _patch, gate_outcome = self._drive_to_l1_disposition(issue_id)
        self.assertEqual(gate_outcome.status, "L1", gate_outcome.message)

        trusted = self.store.disposition_for(issue_id)
        self.store.add_disposition(
            trusted.model_copy(
                update={"evidence_ref": f"runs/RUN-MISSING/{issue_id}/disposition#sha256={'0' * 64}"}
            )
        )
        rejected = self.client.get(f"/api/v1/issues/{issue_id}/disposition")
        self.assertEqual(rejected.status_code, 500, rejected.text)
        self.assertEqual(rejected.json()["code"], "VF-7001")
        self.assertIn("证据缺失", rejected.json()["message"])

        self.store.add_disposition(trusted.model_copy(update={"evidence_ref": "pipeline/run-1"}))
        restored = self.client.get(f"/api/v1/issues/{issue_id}/disposition")
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertTrue(restored.json()["data"]["evidence_ok"])
        self.assertTrue(restored.json()["data"]["conclusion_trusted"])

    def test_main_branch_push_is_skipped_without_creating_issue(self) -> None:
        issues_before = len(self.store.issues)
        pending_before = list(self.store.pending())
        body = json.dumps(
            {"repo": "verifix-target", "branch": "main", "base_sha": "abc", "action": "merged"}
        ).encode("utf-8")
        response = self._webhook(body, self.guard.sign(body))

        self.assertEqual(response.status_code, 202, response.text)
        data = response.json()["data"]
        self.assertTrue(data["skipped"])
        self.assertIsNone(data["issue_id"])
        self.assertIn("main", data["reason"])
        self.assertEqual(len(self.store.issues), issues_before)
        self.assertEqual(list(self.store.pending()), pending_before)


if __name__ == "__main__":
    unittest.main()