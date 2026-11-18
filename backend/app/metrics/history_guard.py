from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.api.envelope import ApiError, ErrorCode

DEFAULT_BASELINE = "docs/devlog/m5-eval-report.md=931d20442673b0922a32cfb42de1dcc9996925836607f6ddedbc5e8b1f165502"


class HistoryDigestGuard:
    def __init__(
        self,
        report_path: Path | str = "docs/devlog/m5-eval-report.md",
        baseline: str = DEFAULT_BASELINE,
        evidence_dir: Path | str = ".evidence/metrics-recalc",
    ) -> None:
        self.report_path = Path(report_path)
        configured_path, _, expected = baseline.partition("=")
        self.baseline_path = Path(configured_path) if configured_path else self.report_path
        self.expected_sha256 = expected or DEFAULT_BASELINE.split("=", 1)[1]
        self.evidence_dir = Path(evidence_dir)

    def current_digest(self) -> str:
        if not self.baseline_path.is_file():
            return ""
        return hashlib.sha256(self.baseline_path.read_bytes()).hexdigest()

    def verify(self) -> str:
        digest = self.current_digest()
        if digest != self.expected_sha256:
            self._remember(status="TAMPERED", digest=digest)
            raise ApiError(ErrorCode.HISTORY_TAMPERED, "历史留痕摘要与基线不一致，发布已阻断")
        self._remember(status="VERIFIED", digest=digest)
        return digest

    def _remember(self, status: str, digest: str) -> None:
        path = self.evidence_dir / "history-baseline.json"
        if path.is_file():
            return
        try:
            self.evidence_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "path": str(self.baseline_path),
                        "sha256": digest,
                        "expected_sha256": self.expected_sha256,
                        "status": status,
                        "verified_at": datetime_now(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass


def datetime_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()