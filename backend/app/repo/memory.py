from __future__ import annotations

import copy
import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from typing import Iterator

from app.domain.enums import CircuitStatus, DefectClass, IssueStatus, RunTerminalState, StepKind
from app.domain.models import (
    Alert,
    AuditFinding,
    CircuitState,
    Disposition,
    DispositionHistoryEntry,
    Event,
    ExclusionEntry,
    GateAttempt,
    GateResult,
    Issue,
    Metric,
    MetricDefinitionRecord,
    MetricReport,
    MetricSnapshotRef,
    Patch,
    PatchAttempt,
    Proof,
    RecalcRun,
    ReproductionAttempt,
    Run,
    RunStep,
    Verdict,
)
from app.repo.interfaces import (
    EventStore,
    EvidenceStore,
    GovernanceStore,
    IssueStore,
    OutboxStore,
    RunStore,
    VerdictStore,
)


SNAPSHOT_COLLECTIONS = (
    "issues",
    "fingerprints",
    "alerts",
    "verdicts",
    "proofs",
    "patches",
    "audit_findings",
    "gate_results",
    "dispositions",
    "runs",
    "run_by_issue",
    "events",
    "outbox",
    "metrics",
    "circuits",
    "reproduction_attempts",
    "patch_attempts",
    "gate_attempts",
    "disposition_history",
    "metric_definitions",
    "metric_snapshots",
    "recalc_runs",
    "metric_exclusions",
    "metric_reports",
)


ATTEMPT_COLLECTIONS = (
    "reproduction_attempts",
    "patch_attempts",
    "gate_attempts",
    "disposition_history",
)


CONTENT_COLLECTIONS = (
    "issues",
    "alerts",
    "verdicts",
    "proofs",
    "reproduction_attempts",
    "patches",
    "patch_attempts",
    "gate_results",
    "gate_attempts",
    "dispositions",
    "disposition_history",
    "runs",
    "events",
)


def canonical_content(value):
    from pydantic import BaseModel

    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): canonical_content(item) for key, item in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [canonical_content(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


class AppendOnlyViolation(Exception):
    pass


class TransactionConflict(Exception):
    pass


class RecordNotFound(KeyError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _event_hash(prev_hash: str, event: Event) -> str:
    payload = "|".join(
        [
            prev_hash,
            str(event.seq),
            event.event_type.value,
            event.occurred_at.isoformat(),
            event.actor,
            event.step.value if event.step else "",
            event.payload_ref or "",
            str(event.schema_version),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class MemoryStore(IssueStore, VerdictStore, EvidenceStore, RunStore, EventStore, OutboxStore, GovernanceStore):
    def __init__(self) -> None:
        self.issues: dict[str, Issue] = {}
        self.fingerprints: dict[str, str] = {}
        self.alerts: dict[str, list[Alert]] = {}
        self.verdicts: dict[str, list[Verdict]] = {}
        self.proofs: dict[str, Proof] = {}
        self.patches: dict[str, Patch] = {}
        self.audit_findings: dict[str, list[AuditFinding]] = {}
        self.gate_results: dict[str, GateResult] = {}
        self.dispositions: dict[str, Disposition] = {}
        self.runs: dict[str, Run] = {}
        self.run_by_issue: dict[str, str] = {}
        self.events: dict[str, list[Event]] = {}
        self.outbox: dict[str, dict[str, str]] = {}
        self.metrics: dict[tuple[str, str, str], Metric] = {}
        self.circuits: dict[DefectClass, CircuitState] = {}
        self.reproduction_attempts: dict[str, list[ReproductionAttempt]] = {}
        self.patch_attempts: dict[str, list[PatchAttempt]] = {}
        self.gate_attempts: dict[str, list[GateAttempt]] = {}
        self.disposition_history: dict[str, list[DispositionHistoryEntry]] = {}
        self.metric_definitions: dict[str, MetricDefinitionRecord] = {}
        self.metric_snapshots: dict[str, MetricSnapshotRef] = {}
        self.recalc_runs: dict[str, RecalcRun] = {}
        self.metric_exclusions: dict[tuple[str, str], list[ExclusionEntry]] = {}
        self.metric_reports: dict[str, MetricReport] = {}
        self._transaction_depth = 0
        self._snapshot: dict[str, object] | None = None

    @contextmanager
    def transaction(self) -> Iterator["MemoryStore"]:
        if self._transaction_depth == 0:
            self._snapshot = self._take_snapshot()
        self._transaction_depth += 1
        try:
            yield self
        except Exception:
            self._transaction_depth -= 1
            if self._transaction_depth == 0 and self._snapshot is not None:
                self._restore_snapshot(self._snapshot)
                self._snapshot = None
            raise
        else:
            self._transaction_depth -= 1
            if self._transaction_depth == 0:
                self._snapshot = None

    def _take_snapshot(self) -> dict[str, object]:
        return {name: copy.deepcopy(getattr(self, name)) for name in SNAPSHOT_COLLECTIONS}

    def _restore_snapshot(self, snapshot: dict[str, object]) -> None:
        for name in SNAPSHOT_COLLECTIONS:
            setattr(self, name, snapshot[name])

    def add(self, issue: Issue) -> Issue:
        key = f"{issue.repo}::{issue.code_version}::{issue.fingerprint}"
        existing = self.fingerprints.get(key)
        if existing is not None:
            return self.issues[existing]
        self.issues[issue.issue_id] = issue
        self.fingerprints[key] = issue.issue_id
        return issue

    def get(self, issue_id: str) -> Issue:
        issue = self.issues.get(issue_id)
        if issue is None:
            raise RecordNotFound(issue_id)
        return issue

    def find_by_fingerprint(self, repo: str, fingerprint: str) -> Issue | None:
        for key, issue_id in self.fingerprints.items():
            parts = key.split("::")
            if parts[0] == repo and parts[-1] == fingerprint:
                return self.issues[issue_id]
        return None

    def update(self, issue: Issue) -> Issue:
        if issue.issue_id not in self.issues:
            raise RecordNotFound(issue.issue_id)
        self.issues[issue.issue_id] = issue
        return issue

    def list_by_status(self, status: IssueStatus) -> list[Issue]:
        return [issue for issue in self.issues.values() if issue.status is status]

    def add_alert(self, alert: Alert) -> Alert:
        for entries in self.alerts.values():
            if any(entry.alert_ref == alert.alert_ref for entry in entries):
                return alert
        return self.link_alert(self._alert_owner(alert), alert)

    def _alert_owner(self, alert: Alert) -> str:
        for issue_id, issue in self.issues.items():
            if issue.fingerprint == alert.snippet_fingerprint:
                return issue_id
        return "unassigned"

    def link_alert(self, issue_id: str, alert: Alert) -> Alert:
        bucket = self.alerts.setdefault(issue_id, [])
        if any(entry.alert_ref == alert.alert_ref for entry in bucket):
            return alert
        bucket.append(alert)
        return alert

    def alerts_for(self, issue_id: str) -> list[Alert]:
        return list(self.alerts.get(issue_id, []))

    def add_verdict(self, verdict: Verdict) -> Verdict:
        history = self.verdicts.setdefault(verdict.issue_id, [])
        if verdict.is_effective:
            for previous in history:
                if previous.is_effective:
                    history[history.index(previous)] = previous.model_copy(update={"is_effective": False})
        history.append(verdict)
        return verdict

    def effective(self, issue_id: str) -> Verdict | None:
        for verdict in reversed(self.verdicts.get(issue_id, [])):
            if verdict.is_effective:
                return verdict
        return None

    def history(self, issue_id: str) -> list[Verdict]:
        return list(self.verdicts.get(issue_id, []))

    def add_proof(self, proof: Proof) -> Proof:
        self.proofs[proof.issue_id] = proof
        return proof

    def proof_for(self, issue_id: str) -> Proof | None:
        return self.proofs.get(issue_id)

    def add_patch(self, patch: Patch) -> Patch:
        self.patches[patch.issue_id] = patch
        return patch

    def patch_for(self, issue_id: str) -> Patch | None:
        return self.patches.get(issue_id)

    def add_audit_finding(self, finding: AuditFinding) -> AuditFinding:
        self.audit_findings.setdefault(finding.patch_id, []).append(finding)
        return finding

    def audit_findings_for(self, patch_id: str) -> list[AuditFinding]:
        return list(self.audit_findings.get(patch_id, []))

    def add_gate_result(self, result: GateResult) -> GateResult:
        self.gate_results[result.patch_id] = result
        return result

    def gate_result_for(self, patch_id: str) -> GateResult | None:
        return self.gate_results.get(patch_id)

    def add_disposition(self, disposition: Disposition) -> Disposition:
        self.dispositions[disposition.issue_id] = disposition
        return disposition

    def disposition_for(self, issue_id: str) -> Disposition | None:
        return self.dispositions.get(issue_id)

    def add_run(self, run: Run) -> Run:
        if run.run_id in self.runs:
            raise TransactionConflict(f"run {run.run_id} already exists")
        self.runs[run.run_id] = run
        self.run_by_issue[run.issue_id] = run.run_id
        return run

    def get_run(self, run_id: str) -> Run:
        run = self.runs.get(run_id)
        if run is None:
            raise RecordNotFound(run_id)
        return run

    def run_for_issue(self, issue_id: str) -> Run | None:
        run_id = self.run_by_issue.get(issue_id)
        return self.runs.get(run_id) if run_id else None

    def append_step(self, run_id: str, step: RunStep) -> Run:
        run = self.get_run(run_id)
        steps = [existing for existing in run.steps if existing.kind is not step.kind]
        steps.append(step)
        order = {kind: index for index, kind in enumerate(StepKind)}
        steps.sort(key=lambda item: order[item.kind])
        updated = run.model_copy(update={"steps": steps})
        self.runs[run_id] = updated
        return updated

    def finish_run(self, run_id: str, terminal_state: RunTerminalState) -> Run:
        run = self.get_run(run_id)
        updated = run.model_copy(update={"terminal_state": terminal_state, "ended_at": _now()})
        self.runs[run_id] = updated
        return updated

    def append(self, event: Event) -> Event:
        chain = self.events.setdefault(event.run_id, [])
        prev_hash = chain[-1].self_hash if chain else ""
        seq = (chain[-1].seq + 1) if chain else 1
        materialized = event.model_copy(update={"seq": seq, "prev_hash": prev_hash})
        sealed = materialized.model_copy(update={"self_hash": _event_hash(prev_hash, materialized)})
        chain.append(sealed)
        return sealed

    def list_for_run(self, run_id: str) -> list[Event]:
        return list(self.events.get(run_id, []))

    def verify_chain(self, run_id: str) -> bool:
        prev_hash = ""
        for index, event in enumerate(self.events.get(run_id, []), start=1):
            if event.seq != index or event.prev_hash != prev_hash:
                return False
            if event.self_hash != _event_hash(event.prev_hash, event):
                return False
            prev_hash = event.self_hash
        return True

    def forbid_mutation(self, run_id: str) -> None:
        raise AppendOnlyViolation(f"events of run {run_id} are append-only")

    def enqueue(self, key: str, task_type: str, payload_ref: str) -> None:
        self.outbox[key] = {"task_type": task_type, "payload_ref": payload_ref, "status": "PENDING"}

    def pending(self) -> list[str]:
        return [key for key, item in self.outbox.items() if item["status"] == "PENDING"]

    def mark_done(self, key: str) -> None:
        if key in self.outbox:
            self.outbox[key]["status"] = "DONE"

    def add_metric(self, metric: Metric) -> Metric:
        self.metrics[(metric.metric_id.value, metric.stage_tier.value, metric.window)] = metric
        return metric

    def record_reproduction(self, attempt: ReproductionAttempt) -> ReproductionAttempt:
        bucket = self.reproduction_attempts.setdefault(attempt.issue_id, [])
        if any(existing.attempt_id == attempt.attempt_id for existing in bucket):
            raise AppendOnlyViolation(f"reproduction attempt {attempt.attempt_id} already exists")
        bucket.append(attempt)
        return attempt

    def reproduction_attempts_for(self, issue_id: str) -> list[ReproductionAttempt]:
        return list(self.reproduction_attempts.get(issue_id, []))

    def next_reproduction_index(self, issue_id: str) -> int:
        return len(self.reproduction_attempts.get(issue_id, [])) + 1

    def record_patch(self, attempt: PatchAttempt) -> PatchAttempt:
        bucket = self.patch_attempts.setdefault(attempt.issue_id, [])
        if any(existing.attempt_id == attempt.attempt_id for existing in bucket):
            raise AppendOnlyViolation(f"patch attempt {attempt.attempt_id} already exists")
        bucket.append(attempt)
        return attempt

    def patch_attempts_for(self, issue_id: str) -> list[PatchAttempt]:
        return list(self.patch_attempts.get(issue_id, []))

    def next_patch_index(self, issue_id: str) -> int:
        return len(self.patch_attempts.get(issue_id, [])) + 1

    def record_gate(self, attempt: GateAttempt) -> GateAttempt:
        bucket = self.gate_attempts.setdefault(attempt.patch_id, [])
        if any(existing.attempt_id == attempt.attempt_id for existing in bucket):
            raise AppendOnlyViolation(f"gate attempt {attempt.attempt_id} already exists")
        bucket.append(attempt)
        return attempt

    def gate_attempts_for(self, patch_id: str) -> list[GateAttempt]:
        return list(self.gate_attempts.get(patch_id, []))

    def record_disposition(self, entry: DispositionHistoryEntry) -> DispositionHistoryEntry:
        bucket = self.disposition_history.setdefault(entry.issue_id, [])
        bucket.append(entry)
        return entry

    def disposition_history_for(self, issue_id: str) -> list[DispositionHistoryEntry]:
        return list(self.disposition_history.get(issue_id, []))

    def put_definition(self, record: MetricDefinitionRecord) -> MetricDefinitionRecord:
        self.metric_definitions[f"{record.metric_id.value}:{record.definition_version}"] = record
        return record

    def get_definition(self, metric_id, version: str) -> MetricDefinitionRecord | None:
        return self.metric_definitions.get(f"{metric_id.value}:{version}")

    def list_definitions(self) -> list[MetricDefinitionRecord]:
        return list(self.metric_definitions.values())

    def put_snapshot(self, ref: MetricSnapshotRef) -> MetricSnapshotRef:
        self.metric_snapshots[ref.snapshot_id] = ref
        return ref

    def get_snapshot(self, snapshot_id: str) -> MetricSnapshotRef | None:
        return self.metric_snapshots.get(snapshot_id)

    def put_recalc(self, run: RecalcRun) -> RecalcRun:
        self.recalc_runs[run.recalc_id] = run
        return run

    def get_recalc(self, recalc_id: str) -> RecalcRun | None:
        return self.recalc_runs.get(recalc_id)

    def update_recalc(self, run: RecalcRun) -> RecalcRun:
        if run.recalc_id not in self.recalc_runs:
            raise RecordNotFound(run.recalc_id)
        self.recalc_runs[run.recalc_id] = run
        return run

    def in_progress(self, window: str, tier) -> RecalcRun | None:
        for run in self.recalc_runs.values():
            if run.window == window and run.tier is tier and run.status == "RUNNING":
                return run
        return None

    def metrics_for(self, window: str | None = None, tier=None) -> list[Metric]:
        selected = [
            metric
            for metric in self.metrics.values()
            if (window is None or metric.window == window) and (tier is None or metric.stage_tier is tier)
        ]
        order = {value: index for index, value in enumerate(("M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9"))}
        return sorted(selected, key=lambda item: order[item.metric_id.value])

    def put_exclusions(self, recalc_id: str, metric_id, entries: list[ExclusionEntry]) -> list[ExclusionEntry]:
        key = (recalc_id, metric_id.value if hasattr(metric_id, "value") else str(metric_id))
        self.metric_exclusions[key] = list(entries)
        return self.metric_exclusions[key]

    def exclusions(self, recalc_id: str, metric_id) -> list[ExclusionEntry]:
        key = (recalc_id, metric_id.value if hasattr(metric_id, "value") else str(metric_id))
        return list(self.metric_exclusions.get(key, []))

    def put_report(self, report: MetricReport) -> MetricReport:
        self.metric_reports[report.report_id] = report
        return report

    def get_report(self, report_id: str) -> MetricReport | None:
        return self.metric_reports.get(report_id)

    def next_report_version(self, window: str, tier) -> int:
        versions = [
            report.version
            for report in self.metric_reports.values()
            if report.window == window and report.tier is tier
        ]
        return (max(versions) + 1) if versions else 1

    def circuit_for(self, defect_class: DefectClass) -> CircuitState:
        state = self.circuits.get(defect_class)
        if state is None:
            state = CircuitState(defect_class=defect_class, state=CircuitStatus.CLOSED)
            self.circuits[defect_class] = state
        return state

    def save_circuit(self, state: CircuitState) -> CircuitState:
        self.circuits[state.defect_class] = state
        return state

    def snapshot_digest(self) -> str:
        payload = json.dumps(
            {
                "issues": sorted(self.issues.keys()),
                "runs": sorted(self.runs.keys()),
                "events": {run_id: len(chain) for run_id, chain in sorted(self.events.items())},
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
    def content_digest(self) -> str:
        payload = {name: canonical_content(getattr(self, name)) for name in CONTENT_COLLECTIONS}
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def snapshot_copy(self) -> "MemoryStore":
        clone = MemoryStore()
        for name in SNAPSHOT_COLLECTIONS:
            value = getattr(self, name)
            if isinstance(value, dict):
                copied = {
                    key: list(item) if isinstance(item, list) else item
                    for key, item in value.items()
                }
            elif isinstance(value, list):
                copied = list(value)
            else:
                copied = value
            setattr(clone, name, copied)
        return clone

    def collection_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for name in SNAPSHOT_COLLECTIONS:
            value = getattr(self, name)
            if isinstance(value, dict):
                counts[name] = sum(len(item) if isinstance(item, list) else 1 for item in value.values())
            elif isinstance(value, list):
                counts[name] = len(value)
            else:
                counts[name] = 1
        return counts

    def event_chain_lengths(self) -> dict[str, int]:
        return {run_id: len(chain) for run_id, chain in self.events.items()}

    def verify_all_chains(self) -> bool:
        return all(self.verify_chain(run_id) for run_id in self.events)