from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import timedelta

from pydantic import BaseModel, Field

from app.config import AppConfig
from app.domain.enums import DefectClass, EventType, IssueStatus, Severity, SourceKind, StepKind, StepStatus
from app.domain.models import Alert, Event, Issue, Location, Run, RunStep, utc_now
from app.repo.memory import MemoryStore


class ManualIssueInput(BaseModel):
    repo: str = Field(min_length=1)
    code_version: str = Field(min_length=1)
    rule_id: str = Field(min_length=1)
    severity: Severity
    file: str = Field(min_length=1)
    line: int | None = Field(default=None, ge=1)
    component: str | None = None
    component_version: str | None = None
    defect_class: DefectClass | None = None
    source_kind: SourceKind = SourceKind.MANUAL
    snippet: str = ""

    def location(self) -> Location:
        return Location(file=self.file, line=self.line, component=self.component, component_version=self.component_version)


@dataclass(frozen=True)
class SubmissionResult:
    issue_id: str
    run_id: str
    status: IssueStatus
    idempotent: bool
    in_scope: bool


def compute_fingerprint(repo: str, code_version: str, location: Location, rule_id: str, snippet: str) -> str:
    normalized = " ".join(snippet.split())
    payload = "|".join([repo, code_version, location.file, str(location.line or ""), rule_id, normalized])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class IntakeService:
    def __init__(self, store: MemoryStore, config: AppConfig):
        self.store = store
        self.config = config

    def submit_manual(self, payload: ManualIssueInput, actor: str = "manual-submit") -> SubmissionResult:
        location = payload.location()
        fingerprint = compute_fingerprint(
            payload.repo, payload.code_version, location, payload.rule_id, payload.snippet
        )
        existing = self.store.find_by_fingerprint(payload.repo, fingerprint)
        if existing is not None:
            run = self.store.run_for_issue(existing.issue_id)
            return SubmissionResult(
                issue_id=existing.issue_id,
                run_id=run.run_id if run else "",
                status=existing.status,
                idempotent=True,
                in_scope=existing.in_scope,
            )

        now = utc_now()
        in_scope = payload.defect_class is not None
        issue = Issue(
            issue_id=f"ISS-{uuid.uuid4().hex[:12]}",
            repo=payload.repo,
            code_version=payload.code_version,
            defect_class=payload.defect_class,
            severity=payload.severity,
            status=IssueStatus.RECEIVED,
            source_count=1,
            fingerprint=fingerprint,
            in_scope=in_scope,
            occurred_at=now,
            updated_at=now,
        )
        with self.store.transaction():
            self.store.add(issue)
            self.store.link_alert(
                issue.issue_id,
                Alert(
                    alert_ref=f"manual:{issue.issue_id}",
                    source_kind=payload.source_kind,
                    rule_id=payload.rule_id,
                    location=payload.location(),
                    raw_severity=payload.severity,
                    snippet_fingerprint=fingerprint,
                    defect_class=payload.defect_class,
                    snippet=payload.snippet,
                ),
            )
            run = Run(
                run_id=f"RUN-{uuid.uuid4().hex[:12]}",
                issue_id=issue.issue_id,
                started_at=now,
                deadline_at=now + timedelta(seconds=self.config.run.deadline_seconds),
                steps=[RunStep(kind=kind, status=StepStatus.NOT_RUN) for kind in StepKind],
            )
            self.store.add_run(run)
            self.store.append(
                Event(
                    event_id=f"INGEST-{issue.issue_id}",
                    run_id=run.run_id,
                    seq=1,
                    event_type=EventType.INGEST,
                    occurred_at=now,
                    actor=actor,
                    step=StepKind.INGEST,
                    payload_ref=f"issue/{issue.issue_id}",
                )
            )
            self.store.enqueue(f"triage:{issue.issue_id}", "triage", f"issue/{issue.issue_id}")
        return SubmissionResult(
            issue_id=issue.issue_id,
            run_id=run.run_id,
            status=issue.status,
            idempotent=False,
            in_scope=in_scope,
        )