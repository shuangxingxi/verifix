from __future__ import annotations

import hashlib
import json
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.api.envelope import ApiError, ErrorCode
from app.realscan.models import BoundaryKind, EvidencePack, VerificationSource

MANIFEST_NAME = "manifest.json"
DIGEST_NAME = "EVIDENCE.sha256"
INDEX_NAME = "INDEX.json"


@dataclass
class EvidenceInput:
    commands: list[str]
    runtime_facts: dict[str, object] = field(default_factory=dict)
    reuse_conditions: dict[str, object] = field(default_factory=dict)
    boundary_tags: list[BoundaryKind] = field(default_factory=list)
    verification_source: VerificationSource = VerificationSource.UNVERIFIED
    files: dict[str, str] = field(default_factory=dict)
    raw_output: str = ""


@dataclass(frozen=True)
class IntegrityReport:
    evidence_id: str
    ok: bool
    mismatches: list[str]


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_text(payload: str) -> str:
    return _sha256_bytes(payload.encode("utf-8"))


class EvidencePackWriter:
    def __init__(self, root: Path, scrubber: object | None = None, leak_scanner: object | None = None) -> None:
        self.root = Path(root)
        self.scrubber = scrubber
        self.leak_scanner = leak_scanner
        self._issued: set[str] = set()

    def new_evidence_id(self, prefix: str) -> str:
        if prefix not in {"VER", "SCAN", "ISO"}:
            raise ValueError(f"unsupported evidence prefix: {prefix}")
        for _ in range(64):
            stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
            candidate = f"{prefix}-{stamp}-{secrets.token_hex(2)}"
            if candidate not in self._issued:
                self._issued.add(candidate)
                return candidate
        raise ApiError(ErrorCode.EVIDENCE_INTEGRITY, "unable to allocate a unique evidence id")

    def staging_path(self, evidence_id: str) -> Path:
        return self.root / f".staging-{evidence_id}"

    def final_path(self, evidence_id: str) -> Path:
        return self.root / evidence_id

    def write_staging(self, evidence_id: str, rel_path: str, content: str) -> Path:
        target = self._safe_rel(self.staging_path(evidence_id), rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self._scrub(content, rel_path), encoding="utf-8")
        return target

    def _scrub(self, content: str, rel_path: str) -> str:
        if self.scrubber is not None:
            result = self.scrubber.redact(content)
            if getattr(result, "redacted", False):
                raise ApiError(ErrorCode.EVIDENCE_INTEGRITY, f"credential detected in {rel_path}")
        if self.leak_scanner is not None:
            hits = self.leak_scanner.scan(content) if hasattr(self.leak_scanner, "scan") else []
            if hits:
                raise ApiError(ErrorCode.EVIDENCE_INTEGRITY, f"answer markers detected in {rel_path}")
        return content

    @staticmethod
    def _safe_rel(base: Path, rel_path: str) -> Path:
        raw = Path(rel_path)
        if raw.is_absolute() or ".." in raw.parts:
            raise ApiError(ErrorCode.EVIDENCE_INTEGRITY, f"unsafe evidence path: {rel_path}")
        return base / raw

    def write(self, prefix: str, payload: EvidenceInput, evidence_id: str | None = None) -> EvidencePack:
        if not payload.commands:
            raise ApiError(ErrorCode.EVIDENCE_INTEGRITY, "evidence requires at least one command")
        render_commands(payload.commands)
        evidence_id = evidence_id or self.new_evidence_id(prefix)
        final = self.final_path(evidence_id)
        if final.exists():
            report = self.verify(evidence_id)
            if report.ok:
                return self._pack_from_manifest(evidence_id)
            raise ApiError(ErrorCode.EVIDENCE_INTEGRITY, f"evidence target exists with different digest: {evidence_id}")
        created_at = datetime.now(timezone.utc)
        self._assert_monotonic(created_at)
        staging = self.staging_path(evidence_id)
        self.root.mkdir(parents=True, exist_ok=True)
        staging.mkdir(parents=True, exist_ok=False)
        try:
            files = dict(payload.files)
            files.setdefault("commands.txt", render_commands(payload.commands))
            files.setdefault(
                "scrubber_report.json",
                json.dumps({"credential_hits": 0, "answer_hits": 0}, ensure_ascii=False, sort_keys=True),
            )
            for rel_path, content in files.items():
                self.write_staging(evidence_id, rel_path, content)
            if payload.raw_output:
                self.write_staging(evidence_id, "raw/output.txt", payload.raw_output)
            raw_digest = _sha256_text(payload.raw_output)

            content_digest = _tree_digest(staging)
            size_bytes = _tree_size(staging)
            manifest = {
                "evidence_id": evidence_id,
                "path": evidence_id,
                "sha256": content_digest,
                "size_bytes": size_bytes,
                "commands": list(payload.commands),
                "runtime_facts": dict(payload.runtime_facts),
                "raw_output_digest": raw_digest,
                "reuse_conditions": dict(payload.reuse_conditions),
                "boundary_tags": [tag.value for tag in payload.boundary_tags],
                "verification_source": payload.verification_source.value,
                "created_at": created_at.isoformat(),
                "evidence_ref": evidence_id + "/manifest.json",
            }
            manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
            manifest_path = staging / MANIFEST_NAME
            manifest_path.write_text(manifest_text, encoding="utf-8")

            lines = []
            for item in sorted(staging.rglob("*")):
                if item.is_file():
                    lines.append(f"{_sha256_bytes(item.read_bytes())}  {item.relative_to(staging).as_posix()}")
            (staging / DIGEST_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")


            os.replace(staging, final)
            self._update_index(
                {
                    "evidence_id": evidence_id,
                    "path": evidence_id,
                    "sha256": content_digest,
                    "created_at": created_at.isoformat(),
                    "verification_source": payload.verification_source.value,
                }
            )
        except ApiError:
            self._discard(staging)
            raise
        except OSError as exc:
            self._discard(staging)
            raise ApiError(ErrorCode.EVIDENCE_INTEGRITY, f"evidence write failed: {type(exc).__name__}") from exc

        return EvidencePack(
            evidence_id=evidence_id,
            path=evidence_id,
            sha256=content_digest,
            size_bytes=size_bytes,
            commands=list(payload.commands),
            runtime_facts=dict(payload.runtime_facts),
            raw_output_digest=raw_digest,
            reuse_conditions=dict(payload.reuse_conditions),
            boundary_tags=list(payload.boundary_tags),
            verification_source=payload.verification_source,
            created_at=created_at,
        )

    def verify(self, evidence_id: str) -> IntegrityReport:
        final = self.final_path(evidence_id)
        digest_file = final / DIGEST_NAME
        if not final.is_dir() or not digest_file.is_file():
            return IntegrityReport(evidence_id=evidence_id, ok=False, mismatches=[DIGEST_NAME])
        mismatches: list[str] = []
        for line in digest_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            parts = line.split("  ", 1)
            if len(parts) != 2:
                mismatches.append(line)
                continue
            expected, rel_path = parts
            candidate = self._safe_rel(final, rel_path)
            if not candidate.is_file():
                mismatches.append(f"missing:{rel_path}")
                continue
            if _sha256_bytes(candidate.read_bytes()) != expected:
                mismatches.append(f"digest:{rel_path}")
        manifest_path = final / MANIFEST_NAME
        if not manifest_path.is_file():
            mismatches.append(MANIFEST_NAME)
        else:
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest.get("sha256") != _tree_digest(final):
                    mismatches.append("manifest_digest")
            except json.JSONDecodeError:
                mismatches.append("manifest_invalid")
        return IntegrityReport(evidence_id=evidence_id, ok=not mismatches, mismatches=mismatches)

    def _assert_monotonic(self, created_at: datetime) -> None:
        index_path = self.root / INDEX_NAME
        if not index_path.is_file():
            return
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        packs = payload.get("packs") or []
        if not isinstance(packs, list) or not packs:
            return
        last = max(str(item.get("created_at", "")) for item in packs)
        if last and created_at.isoformat() < last:
            raise ApiError(ErrorCode.EVIDENCE_INTEGRITY, "evidence timestamp went backwards")

    def _pack_from_manifest(self, evidence_id: str) -> EvidencePack:
        final = self.final_path(evidence_id)
        manifest = json.loads((final / MANIFEST_NAME).read_text(encoding="utf-8"))
        return EvidencePack(
            evidence_id=evidence_id,
            path=evidence_id,
            sha256=str(manifest.get("sha256", "")) or "0" * 64,
            size_bytes=int(manifest.get("size_bytes", 0)),
            commands=list(manifest.get("commands", [])),
            runtime_facts=dict(manifest.get("runtime_facts", {})),
            raw_output_digest=str(manifest.get("raw_output_digest", "")),
            reuse_conditions=dict(manifest.get("reuse_conditions", {})),
            boundary_tags=[BoundaryKind(str(item)) for item in manifest.get("boundary_tags", [])],
            verification_source=VerificationSource(str(manifest.get("verification_source", "UNVERIFIED"))),
            created_at=datetime.fromisoformat(str(manifest.get("created_at"))),
        )

    def _update_index(self, entry: dict[str, object]) -> None:
        index_path = self.root / INDEX_NAME
        payload: dict[str, object] = {"packs": []}
        if index_path.is_file():
            try:
                payload = json.loads(index_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {"packs": []}
        packs = payload.get("packs")
        if not isinstance(packs, list):
            packs = []
        packs = [item for item in packs if item.get("evidence_id") != entry["evidence_id"]]
        packs.append(entry)
        packs.sort(key=lambda item: str(item.get("evidence_id", "")))
        payload["packs"] = packs
        index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    @staticmethod
    def _discard(path: Path) -> None:
        if not path.exists():
            return
        import shutil

        shutil.rmtree(path, ignore_errors=True)


_EVIDENCE_PATTERNS = (
    ("aws_access_key", __import__("re").compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private_key_block", __import__("re").compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("jwt", __import__("re").compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("bearer_token", __import__("re").compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{12,}\b")),
    ("credentialed_url", __import__("re").compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@[^\s]+")),
    (
        "password_assignment",
        __import__("re").compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key)\s*[:=]\s*['\"]?[^\s'\"]{6,}['\"]?"),
    ),
    (
        "secret_key_assignment",
        __import__("re").compile(r"(?i)\b(SECRET_KEY|DB_PASSWORD|API_KEY|ACCESS_TOKEN)\s*=\s*['\"]?(?!\*\*\*)[^\s'\"]{6,}"),
    ),
    ("sudo_stdin", __import__("re").compile(r"(?i)\bsudo\s+-S\b")),
)


@dataclass
class ScrubVerdict:
    text: str
    hits: list[str] = field(default_factory=list)

    @property
    def redacted(self) -> bool:
        return bool(self.hits)


class EvidenceScrubber:
    def redact(self, text: str) -> ScrubVerdict:
        return ScrubVerdict(text=text, hits=[name for name, pattern in _EVIDENCE_PATTERNS if pattern.search(text)])

    def contains_secret(self, text: str) -> bool:
        return any(pattern.search(text) for _name, pattern in _EVIDENCE_PATTERNS)


def render_commands(commands: list[str], cwd: str | None = None) -> str:
    lines: list[str] = []
    base = cwd or str(Path.cwd())
    for command in commands:
        text = command.strip()
        if not text or "\n" in text:
            raise ApiError(ErrorCode.EVIDENCE_INTEGRITY, "evidence command must be a single non-empty line")
        if "..." in text or __import__("re").search(r"<[A-Za-z_][^>]*>", text):
            raise ApiError(ErrorCode.EVIDENCE_INTEGRITY, "evidence command must not contain placeholders")
        lowered = text.lower()
        for token in ("password=", "--password", "secret_key=", "db_password=", "sudo -s"):
            if token in lowered:
                raise ApiError(ErrorCode.EVIDENCE_INTEGRITY, "evidence command must not contain credentials")
        lines.append(f"# cwd={base}")
        lines.append(text)
    return "\n".join(lines) + "\n"


REQUIRED_REUSE_KEYS = ("image_id", "exec_domain", "network_mode", "dependency_versions")


def validate_reuse_conditions(conditions: dict[str, object]) -> list[str]:
    return [key for key in REQUIRED_REUSE_KEYS if not conditions.get(key)]


HISTORY_BASELINE: dict[str, str] = {
    ".evidence/sandbox/M0-SANDBOX-20261113T171337.txt": "a365c35284bd0be2ef5b8589283007a73a17c4fa9f4f3f73984ba274a9b17db6",
    "docs/devlog/m0-sandbox-verification.md": "35b0c79267427a13041d431b14d4a3f9408621cd5c11e04af88e7aef24a68d30",
    "docs/devlog/m1-detect-report.md": "8892168ab81864c3f14397965419e6e20647e7cd45be6ca33559e868899ed6bb",
    "docs/devlog/m5-eval-report.md": "931d20442673b0922a32cfb42de1dcc9996925836607f6ddedbc5e8b1f165502",
    "docs/devlog/m2-reproduce-report.md": "e6fe54abcc850420da4955ff2ba545b909b02800ff85d74e6cd3e184547531d3",
    "docs/devlog/m1-reachability-report.md": "89d8a582ebc97216462bd9e9d430c8a7e3beb7b266b3f1a4c89ee0adaa13d4f8",
    "sandbox/spec.json": "bd62277bbae9d6ed146e92231b36bc2a3e5462e5aca715144ad8332384e36168",
    "verifix-target/ground_truth.json": "286d13be98fdfc9c18967be8d82e761ab1751ee1aacfc836d599e937b69becb2",
    "verifix-target/requirements.txt": "5e19106aab58ab1414748848bc3b13e2568f54f119603e2606a80d93ba6795a3",
}


def verify_history_digests(project_root: Path, baseline: dict[str, str] | None = None) -> list[str]:
    root = Path(project_root)
    violations: list[str] = []
    for relative, expected in (baseline or HISTORY_BASELINE).items():
        path = root / relative
        if not path.is_file():
            violations.append(f"{relative}:missing")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            violations.append(f"{relative}:{actual}")
    return violations


def assert_history_intact(project_root: Path, baseline: dict[str, str] | None = None) -> None:
    violations = verify_history_digests(project_root, baseline)
    if violations:
        raise ApiError(ErrorCode.HISTORY_TAMPERED, "history digest changed: " + ",".join(violations))


def verify_reuse(recorded: dict[str, object], current: dict[str, object]) -> list[str]:
    missing = validate_reuse_conditions(recorded)
    if missing:
        return ["missing:" + ",".join(missing)]
    drift = [key for key in REQUIRED_REUSE_KEYS if recorded.get(key) != current.get(key)]
    return ["drift:" + ",".join(drift)] if drift else []

def _tree_files(root: Path):
    for item in sorted(root.rglob("*")):
        if item.is_file() and item.name != MANIFEST_NAME and item.name != DIGEST_NAME:
            yield item


def _tree_digest(root: Path) -> str:
    joined = "\n".join(
        f"{item.relative_to(root).as_posix()}:{_sha256_bytes(item.read_bytes())}" for item in _tree_files(root)
    )
    return _sha256_text(joined)


def _tree_size(root: Path) -> int:
    return sum(item.stat().st_size for item in _tree_files(root))
