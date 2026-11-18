from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.envelope import ApiError, ErrorCode
from app.config import load_config
from app.domain.enums import CircuitStatus, DefectClass, IssueStatus, Severity
from app.intake.auth import AuthError, AuthGuard, RateLimiter
from app.intake.dedup import DedupService, InMemorySetNx
from app.intake.normalizer import IntakeOutcome, IssueNormalizer
from app.intake.triggers import CvePayload, RepoWebhookPayload, RuntimeAlertPayload, TriggerService
from app.repo.memory import MemoryStore
from app.runtime.circuit import CircuitBreaker
from app.runtime.queue import TaskQueue
from app.runtime.self_run import SelfRunTracker


class AuthTest(unittest.TestCase):
    def setUp(self) -> None:
        self.guard = AuthGuard(secret="s3cret", allowed_tokens=frozenset({"token-a"}))

    def test_signature_roundtrip(self) -> None:
        body = b'{"repo": "verifix-target"}'
        self.guard.verify_signature(body, self.guard.sign(body))

    def test_missing_or_wrong_signature_rejected(self) -> None:
        body = b'{"repo": "x"}'
        with self.assertRaises(AuthError):
            self.guard.verify_signature(body, None)
        with self.assertRaises(AuthError):
            self.guard.verify_signature(body, "deadbeef")

    def test_token_validation(self) -> None:
        self.guard.verify_token("token-a")
        with self.assertRaises(AuthError):
            self.guard.verify_token("token-b")
        with self.assertRaises(AuthError):
            self.guard.verify_token(None)


class RateLimiterTest(unittest.TestCase):
    def test_window_limits(self) -> None:
        limiter = RateLimiter(limit=2, window_seconds=60)
        self.assertTrue(limiter.allow("k", now=1000.0))
        self.assertTrue(limiter.allow("k", now=1001.0))
        self.assertFalse(limiter.allow("k", now=1002.0))
        self.assertTrue(limiter.allow("k", now=1100.0))

    def test_keys_are_independent(self) -> None:
        limiter = RateLimiter(limit=1, window_seconds=60)
        self.assertTrue(limiter.allow("a", now=1.0))
        self.assertTrue(limiter.allow("b", now=1.0))
        self.assertFalse(limiter.allow("a", now=2.0))


class TriggerServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config()
        self.store = MemoryStore()
        normalizer = IssueNormalizer(self.store, DedupService(self.store, InMemorySetNx()), self.config)
        self.auth = AuthGuard(secret="s3cret", allowed_tokens=frozenset({"token-a"}))
        self.limiter = RateLimiter(limit=5, window_seconds=60)
        self.service = TriggerService(normalizer, self.config, self.auth, self.limiter)

    def test_webhook_signature_and_main_skip(self) -> None:
        payload = RepoWebhookPayload(repo="verifix-target", branch="verifix/ISS-1", base_sha="abc")
        body = json.dumps(payload.model_dump()).encode("utf-8")
        outcome = self.service.handle_repo_webhook(payload, self.auth.sign(body), body, "token-a")
        self.assertTrue(outcome.accepted)
        self.assertFalse(outcome.skipped)

        main_payload = RepoWebhookPayload(repo="verifix-target", branch="main", base_sha="abc")
        main_body = json.dumps(main_payload.model_dump()).encode("utf-8")
        main_outcome = self.service.handle_repo_webhook(main_payload, self.auth.sign(main_body), main_body, "token-a")
        self.assertTrue(main_outcome.skipped)
        self.assertIn("main", main_outcome.reason)

    def test_webhook_bad_signature_raises(self) -> None:
        payload = RepoWebhookPayload(repo="r", branch="verifix/x", base_sha="abc")
        with self.assertRaises(ApiError) as raised:
            self.service.handle_repo_webhook(payload, "bad", b"{}", "token-a")
        self.assertIs(raised.exception.code, ErrorCode.UNAUTHORIZED)

    def test_rate_limit_rejects(self) -> None:
        limiter = RateLimiter(limit=1, window_seconds=60)
        service = TriggerService(self.service.normalizer, self.config, self.auth, limiter)
        service.handle_runtime_alert(RuntimeAlertPayload(repo="r", code_version="v", rule_id="py/sql-injection", file="a.py", line=1), "token-a")
        with self.assertRaises(ApiError) as raised:
            service.handle_runtime_alert(RuntimeAlertPayload(repo="r", code_version="v", rule_id="py/sql-injection", file="a.py", line=1), "token-a")
        self.assertIs(raised.exception.code, ErrorCode.CIRCUIT_OPEN)

    def test_cve_creates_dependency_issue(self) -> None:
        outcome = self.service.handle_cve(
            CvePayload(repo="verifix-target", code_version="v1", package="requests", current_version="2.19.1", fixed_version="2.32.3"),
            "token-a",
        )
        self.assertIs(outcome.outcome, IntakeOutcome.CREATED)
        issue = self.store.get(outcome.issue_id or "")
        self.assertIs(issue.defect_class, DefectClass.DEPENDENCY_CVE)

    def test_runtime_alert_normalizes(self) -> None:
        outcome = self.service.handle_runtime_alert(
            RuntimeAlertPayload(repo="verifix-target", code_version="v1", rule_id="py/command-injection", file="app/main.py", line=81, evidence_ref="runtime/1"),
            "token-a",
        )
        self.assertIs(outcome.outcome, IntakeOutcome.CREATED)
        self.assertIn("强证据", outcome.reason)
        issue = self.store.get(outcome.issue_id or "")
        self.assertIs(issue.defect_class, DefectClass.COMMAND_INJECTION)

    def test_runtime_alert_invalid_locator_rejected(self) -> None:
        with self.assertRaises(ApiError) as raised:
            self.service.handle_runtime_alert(
                RuntimeAlertPayload(repo="r", code_version="v", rule_id="py/sql-injection", file="a.py", line=None),
                "token-a",
            )
        self.assertIs(raised.exception.code, ErrorCode.NOT_NORMALIZED)


class CircuitBreakerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = MemoryStore()
        self.breaker = CircuitBreaker(self.store, fail_streak=3, blacklist_ttl_hours=72)

    def test_three_failures_open_circuit(self) -> None:
        for index in range(2):
            state = self.breaker.record_failure(DefectClass.SQL_INJECTION, f"fp-{index}")
            self.assertIs(state.state, CircuitStatus.CLOSED)
        state = self.breaker.record_failure(DefectClass.SQL_INJECTION, "fp-2")
        self.assertIs(state.state, CircuitStatus.OPEN)
        decision = self.breaker.check(DefectClass.SQL_INJECTION, "fp-new")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "VF-6001")

    def test_blacklist_blocks_same_fingerprint(self) -> None:
        self.breaker.record_failure(DefectClass.SQL_INJECTION, "fingerprint-x")
        decision = self.breaker.check(DefectClass.SQL_INJECTION, "fingerprint-x")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.code, "VF-6002")

    def test_reset_and_pause_resume(self) -> None:
        self.breaker.pause("lead", "maintenance")
        decision = self.breaker.check(DefectClass.SQL_INJECTION, "fp")
        self.assertFalse(decision.allowed)
        self.breaker.resume()
        self.assertTrue(self.breaker.check(DefectClass.SQL_INJECTION, "fp").allowed)

        for index in range(3):
            self.breaker.record_failure(DefectClass.SQL_INJECTION, f"fp-{index}")
        self.breaker.reset(DefectClass.SQL_INJECTION, "lead", "manual reset")
        self.assertTrue(self.breaker.check(DefectClass.SQL_INJECTION, "fp-new").allowed)

    def test_success_clears_streak(self) -> None:
        self.breaker.record_failure(DefectClass.SQL_INJECTION, "fp-1")
        state = self.breaker.record_success(DefectClass.SQL_INJECTION)
        self.assertEqual(state.fail_streak, 0)


class SelfRunTest(unittest.TestCase):
    def test_heartbeat_continuous_and_interruption(self) -> None:
        now = [1000.0]
        tracker = SelfRunTracker(heartbeat_timeout_seconds=120, clock=lambda: now[0])
        tracker.heartbeat()
        now[0] += 60
        tracker.heartbeat()
        self.assertAlmostEqual(tracker.continuous_seconds(), 60.0)
        now[0] += 300
        tracker.heartbeat()
        self.assertEqual(tracker.interruptions(), 1)
        self.assertAlmostEqual(tracker.continuous_seconds(), 0.0)

    def test_no_heartbeat_never_counts(self) -> None:
        tracker = SelfRunTracker(clock=lambda: 5000.0)
        self.assertFalse(tracker.is_healthy())
        self.assertEqual(tracker.continuous_seconds(), 0.0)

    def test_interrupt_resets(self) -> None:
        tracker = SelfRunTracker(clock=lambda: 100.0)
        tracker.heartbeat()
        tracker.interrupt()
        self.assertEqual(tracker.continuous_seconds(), 0.0)
        self.assertEqual(tracker.interruptions(), 1)


class TaskQueueTest(unittest.TestCase):
    def test_consume_ack(self) -> None:
        queue = TaskQueue()
        queue.enqueue("k1", "triage", "issue/1")
        queue.enqueue("k2", "triage", "issue/2")
        claimed = queue.consume(1)
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0].status, "RUNNING")
        queue.ack(claimed[0].key)
        self.assertEqual(queue.pending(), 1)

    def test_duplicate_enqueue_is_idempotent(self) -> None:
        queue = TaskQueue()
        first = queue.enqueue("k1", "triage", "issue/1")
        second = queue.enqueue("k1", "triage", "issue/1")
        self.assertIs(first, second)
        self.assertEqual(queue.queued(), 1)

    def test_retry_to_dead_letter(self) -> None:
        queue = TaskQueue(max_attempts=2)
        queue.enqueue("k1", "triage", "issue/1")
        queue.consume(1)
        queue.retry("k1")
        queue.consume(1)
        task = queue.retry("k1")
        self.assertIsNotNone(task)
        self.assertEqual(task.status, "FAILED")
        self.assertEqual(len(queue.dead_letters), 1)


if __name__ == "__main__":
    unittest.main()