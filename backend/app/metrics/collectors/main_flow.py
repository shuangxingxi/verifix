from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.domain.enums import MetricChannel, StageTier
from app.metrics.reason_codes import UncomputableReason
from app.metrics.snapshot import window_bounds

REPRO_ENTERED_STATUSES = frozenset(
    {
        "REPRODUCING",
        "PROVEN",
        "REPRO_FAILED",
        "PATCHING",
        "AUDITING",
        "GATING",
        "ROLLING_BACK",
        "DISPOSED_L0",
        "DISPOSED_L1",
        "DISPOSED_L2",
        "DISPOSED_L3",
    }
)


def parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass
class IssueEvidenceView:
    issue_id: str
    channel: MetricChannel
    channel_basis: str
    channel_legacy: bool
    first_observed_at: datetime | None
    fallback_occurred_at: bool
    tz_ok: bool
    status: str
    in_scope: bool
    alert_count: int = 0
    verdict: dict | None = None
    verdict_conclusion: str | None = None
    reproduction_attempts: list[dict] = field(default_factory=list)
    proof: dict | None = None
    patch_attempts: list[dict] = field(default_factory=list)
    latest_patch: dict | None = None
    gate_attempts: list[dict] = field(default_factory=list)
    gate_results: list[dict] = field(default_factory=list)
    disposition: dict | None = None
    disposition_history: list[dict] = field(default_factory=list)
    alerts: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    proof_step_status: str | None = None
    missing: list[str] = field(default_factory=list)
    legacy_flags: list[str] = field(default_factory=list)

    @property
    def latest_reproduction_status(self) -> str | None:
        if not self.reproduction_attempts:
            return None
        return max(self.reproduction_attempts, key=lambda item: item.get("attempt_index", 0)).get("status")

    @property
    def entered_reproduction(self) -> bool:
        return (
            bool(self.reproduction_attempts)
            or self.proof is not None
            or self.status in REPRO_ENTERED_STATUSES
            or (self.proof_step_status is not None and self.proof_step_status != "NOT_RUN")
        )

    @property
    def effective_verdict(self) -> dict | None:
        return self.verdict


@dataclass
class CollectedEvidence:
    window: str
    tier: StageTier
    window_start: datetime
    window_end: datetime
    issues: list[IssueEvidenceView] = field(default_factory=list)
    channel_excluded_count: int = 0
    pre_exclusions: list[dict] = field(default_factory=list)
    not_applicable_count: int = 0
    self_run_sample: dict | None = None
    self_run_samples: list[dict] = field(default_factory=list)
    eval_conclusion: dict | None = None
    snapshot_id: str = ""
    snapshot_digest: str = ""

    def scope_exclusion(self, metric_id, issue: IssueEvidenceView, reason: str, detail: str) -> dict:
        return {
            "issue_id": issue.issue_id,
            "metric_id": metric_id.value,
            "reason_code": reason if isinstance(reason, str) else reason.value,
            "detail": detail,
        }


class MainFlowEvidenceCollector:
    def __init__(self, sample_reader=None, eval_reader=None, eval_set_digest: str | None = None) -> None:
        self.sample_reader = sample_reader
        self.eval_reader = eval_reader
        self.eval_set_digest = eval_set_digest

    def build(self, snapshot: dict, snapshot_id: str = "", snapshot_digest: str = "", now: datetime | None = None) -> CollectedEvidence:
        start, end = window_bounds(snapshot["window"])
        evidence = CollectedEvidence(
            window=snapshot["window"],
            tier=StageTier(snapshot["tier"]),
            window_start=start,
            window_end=end,
            snapshot_id=snapshot_id,
            snapshot_digest=snapshot_digest,
        )
        annotations = snapshot.get("annotations") or {}
        for record in snapshot.get("issues") or []:
            view = self._view(record, snapshot, annotations.get(record["issue_id"], {}))
            if view.channel is MetricChannel.EVAL:
                if view.in_scope:
                    evidence.channel_excluded_count += 1
                continue
            if view.channel is MetricChannel.UNKNOWN:
                if view.in_scope:
                    evidence.pre_exclusions.append(
                        {
                            "issue_id": view.issue_id,
                            "reason_code": UncomputableReason.EVIDENCE_INCONSISTENT.value,
                            "detail": "通道不可判",
                        }
                    )
                continue
            if not view.in_scope:
                evidence.not_applicable_count += 1
                continue
            if not view.tz_ok or view.first_observed_at is None:
                evidence.pre_exclusions.append(
                    {
                        "issue_id": view.issue_id,
                        "reason_code": UncomputableReason.EVIDENCE_MISSING.value,
                        "detail": "告警首次观测时刻不可用",
                    }
                )
                continue
            if not (start <= view.first_observed_at < end):
                evidence.not_applicable_count += 1
                continue
            evidence.issues.append(view)

        if self.sample_reader is not None:
            evidence.self_run_sample = self.sample_reader.latest()
            latest_n = getattr(self.sample_reader, "latest_n", None)
            if callable(latest_n):
                evidence.self_run_samples = list(latest_n(3))
        if self.eval_reader is not None:
            evidence.eval_conclusion = self.eval_reader.latest_completed(self.eval_set_digest)
        del now
        return evidence

    def _view(self, record: dict, snapshot: dict, annotation: dict) -> IssueEvidenceView:
        issue_id = record["issue_id"]
        alerts = list((snapshot.get("alerts") or {}).get(issue_id, []))
        verdicts = list((snapshot.get("verdicts") or {}).get(issue_id, []))
        effective = next((item for item in reversed(verdicts) if item.get("is_effective")), None)
        attempts = list((snapshot.get("reproduction_attempts") or {}).get(issue_id, []))
        proof = (snapshot.get("proofs") or {}).get(issue_id)
        patch_attempts = list((snapshot.get("patch_attempts") or {}).get(issue_id, []))
        patch = (snapshot.get("patches") or {}).get(issue_id)
        gate_attempts: list[dict] = []
        gate_results: list[dict] = []
        if patch is not None:
            patch_id = patch.get("patch_id", "")
            gate_attempts = list((snapshot.get("gate_attempts") or {}).get(patch_id, []))
            gate_result = (snapshot.get("gate_results") or {}).get(patch_id)
            if gate_result is not None:
                gate_results = [gate_result]
        disposition = (snapshot.get("dispositions") or {}).get(issue_id)
        history = list((snapshot.get("disposition_history") or {}).get(issue_id, []))
        run = None
        for candidate in (snapshot.get("runs") or {}).values():
            if candidate.get("issue_id") == issue_id:
                run = candidate
                break
        events = list((snapshot.get("events") or {}).get(run["run_id"], [])) if run else []
        proof_step = None
        if run:
            for step in run.get("steps") or []:
                if step.get("kind") == "PROOF":
                    proof_step = step.get("status")
                    break

        channel = MetricChannel(annotation.get("channel", MetricChannel.MAIN.value))
        view = IssueEvidenceView(
            issue_id=issue_id,
            channel=channel,
            channel_basis=annotation.get("channel_basis", "default"),
            channel_legacy=bool(annotation.get("channel_legacy", False)),
            first_observed_at=parse_dt(annotation.get("first_observed_at")),
            fallback_occurred_at=bool(annotation.get("fallback_occurred_at", False)),
            tz_ok=bool(annotation.get("tz_ok", True)) and not bool(annotation.get("tz_unavailable", False)),
            status=record.get("status", ""),
            in_scope=bool(record.get("in_scope", False)),
            alert_count=len(alerts),
            verdict=effective,
            verdict_conclusion=effective.get("conclusion") if effective else None,
            reproduction_attempts=attempts,
            proof=proof,
            patch_attempts=patch_attempts,
            latest_patch=patch,
            gate_attempts=gate_attempts,
            gate_results=gate_results,
            disposition=disposition,
            disposition_history=history,
            alerts=alerts,
            events=events,
            proof_step_status=proof_step,
        )
        if not attempts:
            view.missing.append("reproduction_attempt")
            if proof is not None or view.status in {"PROVEN", "PATCHING", "AUDITING", "GATING", "ROLLING_BACK"} or str(view.status).startswith("DISPOSED"):
                view.legacy_flags.append("repro_legacy")
        if proof is None:
            view.missing.append("proof")
        if effective is None:
            view.missing.append("verdict")
        if patch is None:
            view.missing.append("patch")
        if not patch_attempts:
            view.missing.append("patch_attempt")
            if patch is not None:
                view.legacy_flags.append("patch_legacy")
        if not gate_attempts:
            view.missing.append("gate")
        if disposition is None:
            view.missing.append("disposition")
        if view.channel_legacy:
            view.legacy_flags.append("channel_legacy")
        return view