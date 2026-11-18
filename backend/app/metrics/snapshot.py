from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.domain.enums import MetricChannel, StageTier
from app.domain.models import MetricSnapshotRef
from app.metrics.isolation import ChannelResolver
from app.repo.memory import MemoryStore, canonical_content
from app.tools.redactor import SecretRedactor

SNAPSHOT_SCHEMA_VERSION = 1
SNAPSHOT_KEY_PREFIX = "metrics/snapshots/"


class SnapshotIntegrityError(Exception):
    pass


class SnapshotNotFound(SnapshotIntegrityError):
    pass


@dataclass(frozen=True)
class IntegrityReport:
    snapshot_id: str
    chain_valid: bool
    broken_runs: list[str]
    digest_match: bool
    record_counts: dict[str, int]


@dataclass
class SnapshotEnvelope:
    payload: dict
    ref: MetricSnapshotRef
    reused: bool = False


@dataclass
class ProbeState:
    snapshot_digest: str
    content_digest: str
    collection_counts: dict[str, int]
    event_chain_lengths: dict[str, int]

    def diff(self, other: "ProbeState") -> list[str]:
        differences: list[str] = []
        if self.snapshot_digest != other.snapshot_digest:
            differences.append("snapshot_digest")
        if self.content_digest != other.content_digest:
            differences.append("content_digest")
        if self.collection_counts != other.collection_counts:
            differences.append("collection_counts")
        if self.event_chain_lengths != other.event_chain_lengths:
            differences.append("event_chain_lengths")
        return differences


class ReadOnlyProbe:
    def capture(self, store: MemoryStore) -> ProbeState:
        return ProbeState(
            snapshot_digest=store.snapshot_digest(),
            content_digest=store.content_digest(),
            collection_counts=store.collection_counts(),
            event_chain_lengths=store.event_chain_lengths(),
        )

    def compare(self, before: ProbeState, after: ProbeState) -> list[str]:
        return before.diff(after)


def window_bounds(window: str) -> tuple[datetime, datetime]:
    try:
        year_text, month_text = window.split("-")
        year = int(year_text)
        month = int(month_text)
        if month < 1 or month > 12:
            raise ValueError
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"invalid window: {window}") from exc
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = datetime(year + 1, 1, 1, tzinfo=timezone.utc) if month == 12 else datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def annotate_time(value: datetime | None) -> tuple[datetime | None, bool]:
    if value is None:
        return None, False
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc), False
    return value.astimezone(timezone.utc), True


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def _event_time(value) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    return parsed.astimezone(timezone.utc).isoformat()


def _event_hash(prev_hash: str, event: dict) -> str:
    payload = "|".join(
        [
            prev_hash,
            str(event.get("seq")),
            str(event.get("event_type")),
            _event_time(event.get("occurred_at")),
            str(event.get("actor")),
            str(event.get("step") or ""),
            str(event.get("payload_ref") or ""),
            str(event.get("schema_version")),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SnapshotBuilder:
    def __init__(
        self,
        store: MemoryStore,
        evidence,
        snapshot_dir: Path | None = None,
        redactor: SecretRedactor | None = None,
        resolver: ChannelResolver | None = None,
    ) -> None:
        self.store = store
        self.evidence = evidence
        self.snapshot_dir = Path(snapshot_dir) if snapshot_dir is not None else None
        self.redactor = redactor or SecretRedactor()
        self.resolver = resolver or ChannelResolver()

    def capture(self, window: str, tier: StageTier) -> SnapshotEnvelope:
        started = time.perf_counter()
        start, end = window_bounds(window)
        clone = self.store.snapshot_copy()
        payload = self._build_payload(clone, window, tier, start, end)
        digest = _digest(payload)
        snapshot_id = f"SNAP-{window}-{tier.value}-{digest[:12]}"
        key = f"{SNAPSHOT_KEY_PREFIX}{snapshot_id}.json"
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        reused = False
        if self._exists(key):
            check = self.evidence.verify(key, digest)
            if not check.ok:
                raise SnapshotIntegrityError(f"snapshot {snapshot_id} exists but digest mismatch")
            reused = True
        else:
            self.evidence.put_locked(key, encoded, content_type="application/json")
        capture_ms = int((time.perf_counter() - started) * 1000)
        ref = MetricSnapshotRef(
            snapshot_id=snapshot_id,
            window=window,
            tier=tier,
            digest=digest,
            issue_count=len(payload["issues"]),
            event_count=sum(len(chain) for chain in payload["events"].values()),
            record_counts={
                name: _count_records(payload[name]) for name in _RECORD_KEYS
            },
            chain_valid=self._chains_valid(payload["events"]),
            capture_ms=capture_ms,
            redaction_hits=int(payload["redaction_hits"]),
        )
        return SnapshotEnvelope(payload=payload, ref=ref, reused=reused)

    def _exists(self, key: str) -> bool:
        root = getattr(self.evidence, "root", None)
        if root is None:
            return False
        return (Path(root) / key).is_file()

    def _build_payload(self, clone: MemoryStore, window: str, tier: StageTier, start: datetime, end: datetime) -> dict:
        annotations: list[dict] = []
        for issue_id in sorted(clone.issues):
            issue = clone.issues[issue_id]
            resolution = self.resolver.resolve(issue)
            alerts = clone.alerts.get(issue_id, [])
            observed_values = [item.observed_at for item in alerts]
            if observed_values:
                first_observed, tz_ok = annotate_time(min(observed_values))
                fallback = False
            else:
                first_observed, tz_ok = annotate_time(issue.occurred_at)
                fallback = True
            in_window = bool(first_observed is not None and start <= first_observed < end)
            annotations.append(
                {
                    "issue_id": issue_id,
                    "channel": resolution.channel.value,
                    "channel_basis": resolution.basis,
                    "channel_legacy": resolution.legacy,
                    "first_observed_at": _iso(first_observed),
                    "fallback_occurred_at": fallback,
                    "window_owner": in_window,
                    "tz_ok": tz_ok,
                    "tz_unavailable": not tz_ok,
                }
            )
        payload = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "window": window,
            "tier": tier.value,
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "annotations": {item["issue_id"]: item for item in annotations},
            "issues": [canonical_content(clone.issues[key]) for key in sorted(clone.issues)],
            "alerts": {key: [canonical_content(item) for item in value] for key, value in sorted(clone.alerts.items())},
            "verdicts": {key: [canonical_content(item) for item in value] for key, value in sorted(clone.verdicts.items())},
            "proofs": {key: canonical_content(value) for key, value in sorted(clone.proofs.items())},
            "reproduction_attempts": {
                key: [canonical_content(item) for item in value]
                for key, value in sorted(clone.reproduction_attempts.items())
            },
            "patches": {key: canonical_content(value) for key, value in sorted(clone.patches.items())},
            "patch_attempts": {
                key: [canonical_content(item) for item in value]
                for key, value in sorted(clone.patch_attempts.items())
            },
            "gate_results": {key: canonical_content(value) for key, value in sorted(clone.gate_results.items())},
            "gate_attempts": {key: [canonical_content(item) for item in value] for key, value in sorted(clone.gate_attempts.items())},
            "dispositions": {key: canonical_content(value) for key, value in sorted(clone.dispositions.items())},
            "disposition_history": {
                key: [canonical_content(item) for item in value]
                for key, value in sorted(clone.disposition_history.items())
            },
            "runs": {key: canonical_content(value) for key, value in sorted(clone.runs.items())},
            "events": {
                key: [canonical_content(item) for item in value] for key, value in sorted(clone.events.items())
            },
            "redaction_hits": 0,
        }
        hits = self._redact(payload)
        payload["redaction_hits"] = hits
        del window, tier
        return payload

    def _redact(self, payload: dict) -> int:
        hits = 0

        def apply(text: str | None) -> str | None:
            nonlocal hits
            if not text:
                return text
            result = self.redactor.redact(text)
            hits += len(result.hits)
            return result.text

        for issue_id, alerts in payload["alerts"].items():
            for alert in alerts:
                alert["snippet"] = apply(alert.get("snippet"))
        for issue_id, verdicts in payload["verdicts"].items():
            for verdict in verdicts:
                verdict["basis"] = apply(verdict.get("basis"))
                path = verdict.get("taint_path") or []
                verdict["taint_path"] = [apply(item) for item in path]
        for issue_id, disposition in payload["dispositions"].items():
            disposition["action"] = apply(disposition.get("action"))
            disposition["reason_code"] = apply(disposition.get("reason_code"))
        for issue_id, runs in payload["runs"].items():
            for step in runs.get("steps") or []:
                step["detail"] = apply(step.get("detail"))
        for run_id, events in payload["events"].items():
            for event in events:
                event["payload_ref"] = apply(event.get("payload_ref"))
        for issue_id, patch in payload["patches"].items():
            patch["branch"] = apply(patch.get("branch"))
        return hits

    def _chains_valid(self, events: dict[str, list[dict]]) -> bool:
        for chain in events.values():
            prev_hash = ""
            for index, event in enumerate(chain, start=1):
                if event.get("seq") != index or event.get("prev_hash") != prev_hash:
                    return False
                if event.get("self_hash") != _event_hash(event.get("prev_hash", ""), event):
                    return False
                prev_hash = event.get("self_hash", "")
        return True


_RECORD_KEYS = (
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


def _count_records(value) -> int:
    if isinstance(value, dict):
        return sum(len(item) if isinstance(item, list) else 1 for item in value.values())
    if isinstance(value, list):
        return len(value)
    return 1


def _digest(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class SnapshotVerifier:
    def __init__(self, evidence) -> None:
        self.evidence = evidence

    def load(self, snapshot_id: str, expected_digest: str | None = None) -> dict:
        key = f"{SNAPSHOT_KEY_PREFIX}{snapshot_id}.json"
        try:
            raw = self.evidence.read(key, expected_digest)
        except Exception as exc:
            from app.evidence.store import EvidenceMissing

            if isinstance(exc, EvidenceMissing):
                raise SnapshotNotFound(f"snapshot {snapshot_id} not found or digest mismatch") from exc
            raise
        return json.loads(raw.decode("utf-8"))

    def verify(self, snapshot_id: str, expected_digest: str) -> IntegrityReport:
        key = f"{SNAPSHOT_KEY_PREFIX}{snapshot_id}.json"
        check = self.evidence.verify(key, expected_digest)
        payload = self.load(snapshot_id, expected_digest) if check.ok else None
        if payload is None:
            return IntegrityReport(
                snapshot_id=snapshot_id,
                chain_valid=False,
                broken_runs=[],
                digest_match=False,
                record_counts={},
            )
        broken: list[str] = []
        events = payload.get("events") or {}
        for run_id, chain in events.items():
            prev_hash = ""
            valid = True
            for index, event in enumerate(chain, start=1):
                if event.get("seq") != index or event.get("prev_hash") != prev_hash:
                    valid = False
                    break
                if event.get("self_hash") != _event_hash(event.get("prev_hash", ""), event):
                    valid = False
                    break
                prev_hash = event.get("self_hash", "")
            if not valid:
                broken.append(run_id)
        return IntegrityReport(
            snapshot_id=snapshot_id,
            chain_valid=not broken,
            broken_runs=broken,
            digest_match=check.ok,
            record_counts={name: _count_records(payload.get(name, {})) for name in _RECORD_KEYS},
        )