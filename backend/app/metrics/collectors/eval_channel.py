from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

CATEGORIES = ("POSITIVE", "NEGATIVE", "BOUNDARY", "ADVERSARIAL")
LEGACY_ANSWER_FIELDS = {"category", "status", "verdict_agrees", "shallow_fix_rejected"}


def _parse_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def read_expected_digest(path: Path | str | None) -> str | None:
    if path is None:
        return None
    candidate = Path(path)
    if not candidate.is_file():
        return None
    text = candidate.read_text(encoding="utf-8").strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict) and payload.get("sha256"):
        return str(payload["sha256"])
    parts = text.split()
    return parts[0] if parts else None


def read_binding_digest(manifest_path: Path | str | None) -> str | None:
    if manifest_path is None:
        return None
    candidate = Path(manifest_path)
    if not candidate.is_file():
        return None
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload.get("binding_digest")


@dataclass
class EvalConclusion:
    eval_run_id: str
    set_digest: str
    digest_match: bool
    total: int
    completed: int
    category_stats: dict
    m1: dict
    m3: dict
    m2: dict | None
    results: list
    binding_digest: str = ""
    legacy_conclusion: bool = False
    publishable: bool = True

    def to_dict(self) -> dict:
        return {
            "eval_run_id": self.eval_run_id,
            "set_digest": self.set_digest,
            "digest_match": self.digest_match,
            "total": self.total,
            "completed": self.completed,
            "category_stats": self.category_stats,
            "m1": self.m1,
            "m3": self.m3,
            "m2": self.m2,
            "results": self.results,
            "binding_digest": self.binding_digest,
            "legacy_conclusion": self.legacy_conclusion,
            "publishable": self.publishable,
        }


class EvalConclusionReader:
    def __init__(
        self,
        run_dir: Path | str,
        expected_set_digest: str | None = None,
        verdict_dir: Path | str | None = None,
    ) -> None:
        self.run_dir = Path(run_dir)
        self.expected_set_digest = expected_set_digest
        self.verdict_dir = Path(verdict_dir) if verdict_dir is not None else self.run_dir.parent / "verdicts"

    def latest_completed(self, expected_set_digest: str | None = None) -> dict | None:
        expected = expected_set_digest or self.expected_set_digest
        conclusion = self._latest_adjudicated(expected) or self._latest_legacy(expected)
        return conclusion.to_dict() if conclusion is not None else None

    def _latest_adjudicated(self, expected: str | None) -> EvalConclusion | None:
        if not self.verdict_dir.is_dir():
            return None
        candidates: list[tuple[datetime, dict]] = []
        for path in self.verdict_dir.glob("*.verdict.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            binding = str(payload.get("binding_digest", ""))
            if expected and binding != expected:
                continue
            stored = _parse_dt(payload.get("adjudicated_at")) or datetime.min.replace(tzinfo=timezone.utc)
            candidates.append((stored, payload))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        payload = candidates[-1][1]
        return self._from_verdict(payload)

    def _from_verdict(self, payload: dict) -> EvalConclusion:
        stats = {
            str(item.get("category")): {"total": int(item.get("total", 0)), "passed": int(item.get("passed", 0))}
            for item in payload.get("category_stats") or []
        }
        m1 = payload.get("m1") or {}
        m3 = payload.get("m3") or {}
        m2_payload = payload.get("m2")
        m2 = None
        if m2_payload:
            m2 = {"detected": int(m2_payload.get("numerator", 0)), "total": int(m2_payload.get("denominator", 0))}
        case_verdicts = payload.get("case_verdicts") or []
        binding = str(payload.get("binding_digest", ""))
        return EvalConclusion(
            eval_run_id=str(payload.get("eval_run_id", "")),
            set_digest=binding,
            digest_match=True,
            total=len(case_verdicts),
            completed=len(case_verdicts),
            category_stats=stats,
            m1={"detected": int(m1.get("numerator", 0)), "total": int(m1.get("denominator", 0))},
            m3={"agrees": int(m3.get("numerator", 0)), "labelled": int(m3.get("denominator", 0))},
            m2=m2,
            results=[],
            binding_digest=binding,
            legacy_conclusion=bool(payload.get("legacy_conclusion", False)),
            publishable=bool(payload.get("publishable", True)),
        )

    def _latest_legacy(self, expected: str | None) -> EvalConclusion | None:
        if not self.run_dir.is_dir():
            return None
        candidates: list[tuple[datetime, dict]] = []
        for path in self.run_dir.glob("EVALRUN-*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if payload.get("status") not in {"COMPLETED", "ADJUDICATED"}:
                continue
            if int(payload.get("completed", 0)) != int(payload.get("total", -1)):
                continue
            started = _parse_dt(payload.get("started_at")) or datetime.min.replace(tzinfo=timezone.utc)
            candidates.append((started, payload))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        payload = candidates[-1][1]
        results = payload.get("results") or []
        legacy = any(LEGACY_ANSWER_FIELDS.intersection(row or {}) for row in results)
        stats = {}
        for category in CATEGORIES:
            rows = [row for row in results if row.get("category") == category]
            stats[category] = {
                "total": len(rows),
                "passed": sum(1 for row in rows if row.get("status") == "PASS"),
            }
        positive = [row for row in results if row.get("category") in {"POSITIVE", "BOUNDARY"}]
        m1 = {
            "detected": sum(1 for row in positive if row.get("detected")),
            "total": len(positive),
        }
        labelled = [row for row in results if row.get("verdict") is not None]
        m3 = {
            "agrees": sum(1 for row in labelled if row.get("verdict_agrees")),
            "labelled": len(labelled),
        }
        m2 = None
        if results and all("vuln_detected" in row for row in results):
            m2 = {
                "detected": sum(1 for row in results if row.get("vuln_detected")),
                "total": len(results),
            }
        digest = str(payload.get("set_digest", ""))
        binding = str(payload.get("binding_digest", ""))
        return EvalConclusion(
            eval_run_id=str(payload.get("eval_run_id", "")),
            set_digest=digest,
            digest_match=expected is None or expected == digest or (bool(binding) and expected == binding),
            total=int(payload.get("total", 0)),
            completed=int(payload.get("completed", 0)),
            category_stats=stats,
            m1=m1,
            m3=m3,
            m2=m2,
            results=results,
            binding_digest=binding,
            legacy_conclusion=legacy,
            publishable=not legacy,
        )