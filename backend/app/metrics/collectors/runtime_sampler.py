from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

TAIL_BYTES = 64 * 1024


@dataclass(frozen=True)
class SelfRunSampleRecord:
    sampled_at: datetime
    continuous_seconds: float
    interruptions: int
    heartbeat_ok: bool
    tracker_started_at: datetime | None = None
    origin: str = "fixture"
    manual_interventions: int = 0


def _parse_dt(value) -> datetime | None:
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


class SelfRunSampleReader:
    def __init__(self, path: Path | str, timeout_s: float = 120.0) -> None:
        self.path = Path(path) if path is not None else None
        self.timeout_s = timeout_s

    def latest(self) -> dict | None:
        record = self._read_last_record()
        if record is None:
            return None
        return {
            "sampled_at": record.sampled_at,
            "continuous_seconds": record.continuous_seconds,
            "interruptions": record.interruptions,
            "heartbeat_ok": record.heartbeat_ok,
            "tracker_started_at": record.tracker_started_at,
            "origin": record.origin,
            "manual_interventions": record.manual_interventions,
        }

    def latest_record(self) -> SelfRunSampleRecord | None:
        return self._read_last_record()

    def latest_n(self, count: int = 3) -> list[dict]:
        records = self._read_records()
        if count <= 0:
            return []
        return [
            {
                "sampled_at": record.sampled_at,
                "continuous_seconds": record.continuous_seconds,
                "interruptions": record.interruptions,
                "heartbeat_ok": record.heartbeat_ok,
                "tracker_started_at": record.tracker_started_at,
                "origin": record.origin,
                "manual_interventions": record.manual_interventions,
            }
            for record in records[-count:]
        ]

    def _read_last_record(self) -> SelfRunSampleRecord | None:
        records = self._read_records()
        return records[-1] if records else None

    def _read_records(self) -> list[SelfRunSampleRecord]:
        if self.path is None or not self.path.is_file():
            return []
        size = self.path.stat().st_size
        if size == 0:
            return []
        with self.path.open("rb") as handle:
            handle.seek(max(0, size - TAIL_BYTES * 4))
            chunk = handle.read()
        records: list[SelfRunSampleRecord] = []
        for raw_line in chunk.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            sampled_at = _parse_dt(payload.get("sampled_at"))
            if sampled_at is None:
                continue
            records.append(
                SelfRunSampleRecord(
                    sampled_at=sampled_at,
                    continuous_seconds=float(payload.get("continuous_seconds", 0.0)),
                    interruptions=int(payload.get("interruptions", 0)),
                    heartbeat_ok=bool(payload.get("heartbeat_ok", False)),
                    tracker_started_at=_parse_dt(payload.get("tracker_started_at")),
                    origin=str(payload.get("origin") or "fixture"),
                    manual_interventions=int(payload.get("manual_interventions", 0)),
                )
            )
        return records

    def append(self, sample: dict) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(sample, ensure_ascii=False, sort_keys=True) + "\n")