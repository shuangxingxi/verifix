from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class SetNxPort(Protocol):
    def set_if_absent(self, key: str, ttl_seconds: int) -> bool: ...


class InMemorySetNx:
    def __init__(self) -> None:
        self.keys: set[str] = set()

    def set_if_absent(self, key: str, ttl_seconds: int) -> bool:
        del ttl_seconds
        if key in self.keys:
            return False
        self.keys.add(key)
        return True

    def release(self, key: str) -> None:
        self.keys.discard(key)


@dataclass(frozen=True)
class DedupOutcome:
    existing_issue_id: str | None
    claimed: bool


class DedupService:
    def __init__(self, store, setnx: SetNxPort | None = None, ttl_seconds: int = 86_400):
        self.store = store
        self.setnx = setnx or InMemorySetNx()
        self.ttl_seconds = ttl_seconds

    def claim(self, repo: str, fingerprint: str) -> DedupOutcome:
        existing = self.store.find_by_fingerprint(repo, fingerprint)
        if existing is not None:
            return DedupOutcome(existing_issue_id=existing.issue_id, claimed=False)
        key = f"dedup:{repo}:{fingerprint}"
        if not self.setnx.set_if_absent(key, self.ttl_seconds):
            existing = self.store.find_by_fingerprint(repo, fingerprint)
            return DedupOutcome(existing_issue_id=existing.issue_id if existing else None, claimed=False)
        return DedupOutcome(existing_issue_id=None, claimed=True)

    def release(self, repo: str, fingerprint: str) -> None:
        if hasattr(self.setnx, "release"):
            self.setnx.release(f"dedup:{repo}:{fingerprint}")