from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.adapters.pipeline import RecordedPipelineClient
from app.adapters.repo import LocalRepoAdapter
from app.agents.critic.service import CriticService
from app.agents.gatekeeper.service import GatekeeperService
from app.agents.patcher.service import PatcherService
from app.agents.reproducer.executor import LocalTestExecutor
from app.agents.reproducer.service import ReproducerService
from app.config import load_config
from app.domain.enums import (
    DefectClass,
    DispositionLevel,
    FixParadigm,
    GateOutcome,
    IssueStatus,
    MetricChannel,
    ProofResult,
    ReproductionAttemptStatus,
    Severity,
    SourceKind,
    VerdictConclusion,
)
from app.domain.models import (
    Alert,
    Disposition,
    DispositionHistoryEntry,
    EnvSnapshot,
    GateAttempt,
    Issue,
    Location,
    Patch,
    PatchAttempt,
    Proof,
    ReproductionAttempt,
    Verdict,
)
from app.repo.memory import MemoryStore
from app.tracing.service import ReachabilityService

ROOT = Path(__file__).resolve().parents[3]
TARGET = ROOT / "verifix-target"
WINDOW_OBSERVED = datetime(2026, 12, 5, 10, 0, tzinfo=timezone.utc)


def make_issue(
    store: MemoryStore,
    issue_id: str,
    *,
    observed_at: datetime = WINDOW_OBSERVED,
    defect: DefectClass = DefectClass.SQL_INJECTION,
    file: str = "app/main.py",
    line: int = 31,
    rule_id: str = "py/sql-injection",
    channel: MetricChannel = MetricChannel.MAIN,
) -> Issue:
    issue = Issue(
        issue_id=issue_id,
        repo="verifix-target",
        code_version="abc123",
        defect_class=defect,
        severity=Severity.HIGH,
        status=IssueStatus.RECEIVED,
        fingerprint=hashlib.sha256(issue_id.encode("utf-8")).hexdigest(),
        occurred_at=observed_at,
        channel=channel,
    )
    store.add(issue)
    store.link_alert(
        issue_id,
        Alert(
            alert_ref=f"check:{issue_id}",
            source_kind=SourceKind.CHECK,
            rule_id=rule_id,
            location=Location(file=file, line=line),
            raw_severity=Severity.HIGH,
            snippet_fingerprint="s" * 64,
            defect_class=defect,
            observed_at=observed_at,
        ),
    )
    return issue


def run_full_chain(
    store: MemoryStore,
    issue_id: str = "ISS-1",
    *,
    observed_at: datetime = WINDOW_OBSERVED,
    config=None,
    target_root: Path = TARGET,
) -> dict:
    settings = config or load_config()
    repo = LocalRepoAdapter()
    repo.load_from_directory(Path(target_root))
    reachability = ReachabilityService(store, settings)
    reproducer = ReproducerService(store, LocalTestExecutor(), settings)
    patcher = PatcherService(store, settings)
    critic = CriticService(store, settings, LocalTestExecutor())
    pipeline = RecordedPipelineClient.all_passed()
    gatekeeper = GatekeeperService(store, settings, repo, pipeline)

    make_issue(store, issue_id, observed_at=observed_at)
    reachability.analyze(store.get(issue_id), Path(target_root))
    repro = reproducer.reproduce(store.get(issue_id), Path(target_root))
    if repro.status.value != "PROVEN":
        raise AssertionError(f"reproduce failed: {repro.message}")
    patch_outcome = patcher.patch(store.get(issue_id), Path(target_root))
    if patch_outcome.status != "PATCHED":
        raise AssertionError(f"patch failed: {patch_outcome.message}")
    critic_outcome = critic.evaluate(store.get(issue_id), patch_outcome.patch, patch_outcome.candidate, Path(target_root))
    gate_outcome = gatekeeper.dispose(
        store.get(issue_id),
        patch_outcome.patch,
        repro.proof,
        patch_outcome.candidate,
        critic_outcome,
        f"run-{issue_id}",
    )
    return {
        "issue": store.get(issue_id),
        "repro": repro,
        "patch": patch_outcome.patch,
        "critic": critic_outcome,
        "gate": gate_outcome,
    }


def _seed_full_record(store: MemoryStore, issue_id: str, observed_at: datetime) -> None:
    make_issue(store, issue_id, observed_at=observed_at)
    issue = store.get(issue_id)
    store.update(issue.model_copy(update={"status": IssueStatus.DISPOSED_L1}))
    store.add_verdict(
        Verdict(
            verdict_id=f"V-{issue_id}",
            issue_id=issue_id,
            conclusion=VerdictConclusion.REACHABLE,
            confidence=0.9,
            taint_path=["app/main.py:user"],
            basis="static path",
            decided_by="tracer",
            decided_at=observed_at,
        )
    )
    proof = Proof(
        proof_id=f"P-{issue_id}",
        issue_id=issue_id,
        test_path="tests/security/test_sql.py",
        pre_patch_result=ProofResult.FAIL,
        fingerprint=("a" * 63) + issue_id[-1],
        env_snapshot=EnvSnapshot(),
        generated_marker="AUTOGENERATED",
        created_at=observed_at,
    )
    store.add_proof(proof)
    store.record_reproduction(
        ReproductionAttempt(
            attempt_id=f"RA-{issue_id}#1",
            issue_id=issue_id,
            attempt_index=1,
            status=ReproductionAttemptStatus.PROVEN,
            proof_id=proof.proof_id,
            created_at=observed_at,
        )
    )
    patch = Patch(
        patch_id=f"PA-{issue_id}",
        issue_id=issue_id,
        proof_id=proof.proof_id,
        branch=f"verifix/{issue_id}",
        diff_ref="sha256:" + "b" * 64,
        lines_changed=2,
        files_changed=1,
        fix_paradigm=FixParadigm.PARAMETERIZED_QUERY,
        patch_strength=0.8,
        created_at=observed_at,
    )
    store.add_patch(patch)
    store.record_patch(
        PatchAttempt(
            attempt_id=f"PA-{issue_id}#1",
            issue_id=issue_id,
            attempt_index=1,
            patch_id=patch.patch_id,
            created_at=observed_at,
        )
    )
    store.record_gate(
        GateAttempt(
            attempt_id=f"GA-{patch.patch_id}#1",
            patch_id=patch.patch_id,
            issue_id=issue_id,
            outcome=GateOutcome.PASSED,
            red_green_paired=True,
            regression_zero_fail=True,
            coverage_delta_pp=0.0,
            observed_at=observed_at,
        )
    )
    ready_at = observed_at + timedelta(minutes=30)
    store.add_disposition(
        Disposition(
            disposition_id=f"D-{issue_id}",
            issue_id=issue_id,
            level=DispositionLevel.L1,
            action="open pr #1",
            evidence_ref="pipeline/run-1",
            reason_code="GATE_PASSED",
            decided_at=ready_at,
            gate_outcome=GateOutcome.PASSED,
            ready_at=ready_at,
        )
    )
    store.record_disposition(
        DispositionHistoryEntry(
            attempt_id=f"PA-{issue_id}#1",
            issue_id=issue_id,
            level=DispositionLevel.L1,
            gate_outcome=GateOutcome.PASSED,
            decided_at=ready_at,
            ready_at=ready_at,
        )
    )


def _seed_repro_failed(store: MemoryStore, issue_id: str, observed_at: datetime) -> None:
    make_issue(store, issue_id, observed_at=observed_at)
    store.update(store.get(issue_id).model_copy(update={"status": IssueStatus.REPRO_FAILED}))
    store.add_verdict(
        Verdict(
            verdict_id=f"V-{issue_id}",
            issue_id=issue_id,
            conclusion=VerdictConclusion.REACHABLE,
            confidence=0.8,
            taint_path=["app/main.py:user"],
            basis="static path",
            decided_by="tracer",
            decided_at=observed_at,
        )
    )
    store.record_reproduction(
        ReproductionAttempt(
            attempt_id=f"RA-{issue_id}#1",
            issue_id=issue_id,
            attempt_index=1,
            status=ReproductionAttemptStatus.REPRO_FAILED,
            created_at=observed_at,
        )
    )


def _seed_eval(store: MemoryStore, issue_id: str, observed_at: datetime) -> None:
    make_issue(store, issue_id, observed_at=observed_at, channel=MetricChannel.EVAL)
    store.update(store.get(issue_id).model_copy(update={"code_version": f"eval-{issue_id}"}))


def _seed_out_of_window(store: MemoryStore, issue_id: str, observed_at: datetime) -> None:
    make_issue(store, issue_id, observed_at=observed_at)


def seed_synthetic(store: MemoryStore, window: str = "2026-12", **counts: int) -> None:
    year, month = (int(part) for part in window.split("-"))
    observed_at = datetime(year, month, 5, 10, 0, tzinfo=timezone.utc)
    index = 0
    for _ in range(counts.get("full", 0)):
        index += 1
        _seed_full_record(store, f"ISF-{index:03d}", observed_at)
    for _ in range(counts.get("repro_failed", 0)):
        index += 1
        _seed_repro_failed(store, f"ISR-{index:03d}", observed_at)
    for _ in range(counts.get("eval", 0)):
        index += 1
        _seed_eval(store, f"ISE-{index:03d}", observed_at)
    for _ in range(counts.get("out_of_window", 0)):
        index += 1
        _seed_out_of_window(store, f"ISO-{index:03d}", observed_at - timedelta(days=90))


def build_preliminary_window(store: MemoryStore | None = None, *, full: int = 1, **counts: int) -> MemoryStore:
    target = store or MemoryStore()
    if full:
        for offset in range(full):
            issue_id = f"ISS-E2E-{offset + 1}"
            run_full_chain(target, issue_id)
            _normalize_ready_at(target, issue_id, WINDOW_OBSERVED + timedelta(minutes=30))
    seed_synthetic(target, "2026-12", **counts)
    return target


def _normalize_ready_at(store: MemoryStore, issue_id: str, ready_at: datetime) -> None:
    disposition = store.disposition_for(issue_id)
    if disposition is not None:
        store.add_disposition(disposition.model_copy(update={"ready_at": ready_at, "decided_at": ready_at}))
    history = store.disposition_history_for(issue_id)
    if history:
        store.disposition_history[issue_id] = [
            entry.model_copy(update={"ready_at": ready_at, "decided_at": ready_at}) for entry in history
        ]