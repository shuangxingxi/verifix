from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.realscan.models import ReconcileRecord


class ReconcileError(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"reconcile failed: {reason}")


class TruthReconciler:
    def __init__(self, truth_path: Path | str) -> None:
        self.truth_path = Path(truth_path)

    def reconcile(
        self,
        scan_id: str,
        detections,
        target_version: str | None = None,
    ) -> ReconcileRecord:
        payload = self._read_once()
        version = str(payload.get("version", ""))
        if target_version is not None and version != str(target_version):
            raise ReconcileError("version_mismatch")
        items = payload.get("items") or []
        if not isinstance(items, list):
            raise ReconcileError("truth_invalid")
        truth_keys = {
            (str(item.get("file", "")), int(item.get("line", 0)), str(item.get("defect_class", ""))): str(item.get("id", ""))
            for item in items
        }
        found_keys = {
            (_attr(detection, "file"), int(_attr(detection, "line")), _attr(detection, "defect_class")): _attr(detection, "detection_id")
            for detection in detections
        }
        matched = sum(1 for key in truth_keys if key in found_keys)
        missing = sorted(truth_id for key, truth_id in truth_keys.items() if key not in found_keys)
        extra = sorted(detection_id for key, detection_id in found_keys.items() if key not in truth_keys)
        digest = hashlib.sha256(self.truth_path.read_bytes()).hexdigest()
        return ReconcileRecord(
            reconcile_id=f"REC-{scan_id}",
            scan_id=scan_id,
            truth_version=version,
            truth_sha256=digest,
            truth_read_count=1,
            read_phase="POST_SCAN",
            matched=matched,
            missing=missing,
            extra=extra,
            coverage=f"{matched}/{len(items)}",
        )

    def _read_once(self) -> dict:
        try:
            raw = self.truth_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ReconcileError("truth_unreadable") from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ReconcileError("truth_invalid") from exc
        if not isinstance(payload, dict):
            raise ReconcileError("truth_invalid")
        return payload


def _attr(item, name: str):
    if isinstance(item, dict):
        return item.get(name, "")
    return getattr(item, name, "")