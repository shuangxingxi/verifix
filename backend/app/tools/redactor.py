from __future__ import annotations

import re
from dataclasses import dataclass, field

MASK = "***REDACTED***"

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{12,}\b")),
    ("credentialed_url", re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@[^\s]+")),
    ("password_assignment", re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key)\s*[:=]\s*['\"]?[^\s'\"]{6,}['\"]?")),
    ("generic_secret_literal", re.compile(r"\b[0-9a-f]{32,}\b")),
)


@dataclass(frozen=True)
class RedactionHit:
    rule: str
    start: int
    length: int


@dataclass
class RedactionResult:
    text: str
    hits: list[RedactionHit] = field(default_factory=list)

    @property
    def redacted(self) -> bool:
        return bool(self.hits)

    def rules(self) -> list[str]:
        return sorted({hit.rule for hit in self.hits})


_QUICK_HINT = re.compile(
    r"AKIA|PRIVATE KEY|eyJ[A-Za-z0-9_-]{8,}|bearer\s|://|"
    r"(?i:password|passwd|pwd|secret|token|api[_-]?key)\s*[:=]|[0-9a-f]{32,}",
    re.IGNORECASE,
)


class SecretRedactor:
    def __init__(self, mask: str = MASK):
        self.mask = mask

    def redact(self, text: str) -> RedactionResult:
        if not text:
            return RedactionResult(text="", hits=[])
        if _QUICK_HINT.search(text) is None:
            return RedactionResult(text=text, hits=[])
        working = text
        hits: list[RedactionHit] = []
        for rule, pattern in _PATTERNS:
            for match in pattern.finditer(working):
                hits.append(RedactionHit(rule=rule, start=match.start(), length=len(match.group(0))))
            working = pattern.sub(self.mask, working)
        return RedactionResult(text=working, hits=hits)

    def contains_secret(self, text: str) -> bool:
        return any(pattern.search(text) for _, pattern in _PATTERNS)

    def sanitize_exports(self, payloads: dict[str, str]) -> tuple[dict[str, str], RedactionResult]:
        combined: list[RedactionHit] = []
        sanitized: dict[str, str] = {}
        for channel, payload in payloads.items():
            result = self.redact(payload)
            sanitized[channel] = result.text
            combined.extend(result.hits)
        return sanitized, RedactionResult(text="", hits=combined)

    def redaction_event_payload(self, result: RedactionResult, run_id: str) -> dict[str, object]:
        return {
            "run_id": run_id,
            "rules": result.rules(),
            "hit_count": len(result.hits),
            "masked": result.redacted,
        }