from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums import DispositionLevel
from app.evidence.store import EvidenceMissing, LocalEvidenceStore


@dataclass(frozen=True)
class DispositionView:
    disposition_id: str
    issue_id: str
    level: str
    action: str
    reason_code: str
    evidence_ref: str
    evidence_ok: bool
    evidence_detail: str
    conclusion_trusted: bool


class DispositionInspector:
    def __init__(self, store, evidence: LocalEvidenceStore | None = None):
        self.store = store
        self.evidence = evidence

    def inspect(self, issue_id: str) -> DispositionView | None:
        disposition = self.store.disposition_for(issue_id)
        if disposition is None:
            return None
        evidence_ok = True
        detail = ""
        ref_key = disposition.evidence_ref
        expected_sha256 = None
        if "#sha256=" in ref_key:
            ref_key, expected_sha256 = ref_key.split("#sha256=", 1)
        if self.evidence is not None and ref_key.startswith("runs/"):
            try:
                self.evidence.read(ref_key, expected_sha256)
            except EvidenceMissing as exc:
                evidence_ok = False
                detail = str(exc)
        return DispositionView(
            disposition_id=disposition.disposition_id,
            issue_id=disposition.issue_id,
            level=disposition.level.value,
            action=disposition.action,
            reason_code=disposition.reason_code,
            evidence_ref=disposition.evidence_ref,
            evidence_ok=evidence_ok,
            evidence_detail=detail,
            conclusion_trusted=evidence_ok,
        )

    def level_counts(self) -> dict[str, int]:
        counts = {level.value: 0 for level in DispositionLevel}
        for disposition in self.store.dispositions.values():
            counts[disposition.level.value] = counts.get(disposition.level.value, 0) + 1
        return counts