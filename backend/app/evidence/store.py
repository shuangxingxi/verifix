from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from app.api.envelope import ErrorCode


class EvidenceMissing(Exception):
    def __init__(self, key: str, detail: str = ""):
        self.key = key
        self.code = ErrorCode.EVIDENCE_MISSING
        super().__init__(f"evidence missing or corrupted: {key}" + (f" ({detail})" if detail else ""))


@dataclass(frozen=True)
class EvidenceRef:
    key: str
    sha256: str
    size_bytes: int
    content_type: str
    locked: bool


@dataclass(frozen=True)
class IntegrityCheck:
    key: str
    ok: bool
    detail: str


class LocalEvidenceStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        candidate = (self.root / key).resolve()
        if candidate != self.root and self.root.resolve() not in candidate.parents:
            raise EvidenceMissing(key, "path escapes evidence root")
        return candidate

    def put_locked(self, key: str, content: bytes, content_type: str = "application/octet-stream") -> EvidenceRef:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        os.chmod(path, stat.S_IREAD)
        digest = hashlib.sha256(content).hexdigest()
        return EvidenceRef(key=key, sha256=digest, size_bytes=len(content), content_type=content_type, locked=True)

    def read(self, key: str, expected_sha256: str | None = None) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise EvidenceMissing(key, "not found")
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if expected_sha256 is not None and digest != expected_sha256:
            raise EvidenceMissing(key, "sha256 mismatch")
        return data

    def verify(self, key: str, expected_sha256: str) -> IntegrityCheck:
        path = self._path(key)
        if not path.is_file():
            return IntegrityCheck(key=key, ok=False, detail="not found")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected_sha256:
            return IntegrityCheck(key=key, ok=False, detail="sha256 mismatch")
        return IntegrityCheck(key=key, ok=True, detail="")

    def release(self, key: str) -> None:
        path = self._path(key)
        if path.is_file():
            os.chmod(path, stat.S_IREAD | stat.S_IWRITE)