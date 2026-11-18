from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field


class AuthError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"unauthorized: {reason}")


@dataclass
class AuthGuard:
    secret: str
    allowed_tokens: frozenset[str] = frozenset()
    require_signature: bool = True

    def sign(self, body: bytes) -> str:
        return hmac.new(self.secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    def verify_signature(self, body: bytes, signature: str | None) -> None:
        if not self.require_signature:
            return
        if not signature:
            raise AuthError("missing signature")
        expected = self.sign(body)
        if not hmac.compare_digest(expected, signature.strip()):
            raise AuthError("signature mismatch")

    def verify_token(self, token: str | None) -> None:
        if not self.allowed_tokens:
            return
        if not token:
            raise AuthError("missing token")
        if token not in self.allowed_tokens:
            raise AuthError("invalid token")


@dataclass
class RateLimiter:
    limit: int = 60
    window_seconds: float = 60.0
    _hits: dict[str, list[float]] = field(default_factory=dict)

    def allow(self, key: str, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        window_start = current - self.window_seconds
        hits = [stamp for stamp in self._hits.get(key, []) if stamp > window_start]
        if len(hits) >= self.limit:
            self._hits[key] = hits
            return False
        hits.append(current)
        self._hits[key] = hits
        return True

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)