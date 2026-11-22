#!/usr/bin/env python
"""一次性黄金基线采集（PERF-02 改造前冻结）。

只读产品代码，只写 ``backend/tests/support/`` 下的黄金夹具。
对产品源码、``docs/devlog/**``、``.evidence/git-baseline/**`` 一律拒绝写入。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.domain.enums import StageTier  # noqa: E402
from app.evidence.store import LocalEvidenceStore  # noqa: E402
from app.metrics.snapshot import SNAPSHOT_KEY_PREFIX, SnapshotBuilder  # noqa: E402
from tests.support.perf_fixture import (  # noqa: E402
    NOW,
    PERF02_EVENTS,
    PERF02_ISSUES,
    PERF02_RUNS,
    TIER,
    WINDOW,
    build_perf02_store,
    build_small_store,
)

SUPPORT_DIR = ROOT / "backend" / "tests" / "support"
DEFAULT_ARCHIVE_DIR = SUPPORT_DIR / "snapshot_golden"
DEFAULT_OUT = SUPPORT_DIR / "snapshot_golden.json"
DEFAULT_SMALL_OUT = SUPPORT_DIR / "snapshot_golden_small.json"
TARGET_KEYS = ("payload_sha256", "digest", "snapshot_id", "archive_sha256")


class GoldenError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def fail(code: str, message: str) -> None:
    raise GoldenError(code, message)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def ensure_writable(path: Path) -> None:
    target = path.resolve()
    support = SUPPORT_DIR.resolve()
    try:
        target.relative_to(support)
    except ValueError as exc:
        raise GoldenError("WRITE_FORBIDDEN", f"refuse to write outside {SUPPORT_DIR}: {target}") from exc


def code_revision() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        fail("CODE_REVISION_UNAVAILABLE", str(exc))
    return result.stdout.strip()


def canonical_payload_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def collect(*, small: bool, window: str, tier: StageTier) -> tuple[dict, bytes, str]:
    store, scale = build_small_store() if small else build_perf02_store()
    if not small:
        if (scale["issues"], scale["runs"], scale["events"]) != (PERF02_ISSUES, PERF02_RUNS, PERF02_EVENTS):
            fail("FIXTURE_SCALE_MISMATCH", f"unexpected fixture scale: {scale}")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        evidence_root = Path(tmp) / "evidence"
        builder = SnapshotBuilder(store, LocalEvidenceStore(evidence_root))
        envelope = builder.capture(window, tier)
        payload = envelope.payload
        encoded = canonical_payload_bytes(payload)
        key = f"{SNAPSHOT_KEY_PREFIX}{envelope.ref.snapshot_id}.json"
        archive_file = evidence_root / key
        if not archive_file.is_file():
            fail("ARCHIVE_MISSING", f"archive not found: {archive_file}")
        archived = archive_file.read_bytes()
    payload_sha256 = sha256_bytes(encoded)
    archive_sha256 = sha256_bytes(archived)
    if payload_sha256 != archive_sha256:
        fail("ARCHIVE_MISMATCH", "archive bytes differ from canonical payload bytes")
    if envelope.ref.digest != payload_sha256:
        fail("DIGEST_MISMATCH", "ref.digest differs from canonical payload sha256")
    return (
        {
            "readonly": True,
            "note": "改造前黄金基线，冻结后只读；任何数值变动视为回归",
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "code_revision": code_revision(),
            "fixture": {
                "window": window,
                "tier": tier.value,
                "now": NOW.astimezone(timezone.utc).isoformat(),
                **scale,
            },
            "payload_sha256": payload_sha256,
            "payload_bytes": len(encoded),
            "digest": envelope.ref.digest,
            "snapshot_id": envelope.ref.snapshot_id,
            "archive_sha256": archive_sha256,
            "archive_bytes": len(archived),
            "archive_name": Path(key).name,
            "issue_count": envelope.ref.issue_count,
            "event_count": envelope.ref.event_count,
            "record_counts": envelope.ref.record_counts,
            "payload_keys": sorted(payload.keys()),
            "payload_keys_ordered": list(payload.keys()),
        },
        archived,
        Path(key).name,
    )


def write_golden(record: dict, out: Path, archive_dir: Path, archived: bytes, archive_name: str) -> None:
    ensure_writable(out)
    ensure_writable(archive_dir / archive_name)
    if out.is_file():
        previous = json.loads(out.read_text(encoding="utf-8"))
        for key in TARGET_KEYS:
            if previous.get(key) != record.get(key):
                fail("GOLDEN_MISMATCH", f"frozen golden differs on {key}: {previous.get(key)} != {record.get(key)}")
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / archive_name
    if target.is_file():
        if target.read_bytes() != archived:
            fail("GOLDEN_MISMATCH", f"frozen archive differs: {target}")
    else:
        target.write_bytes(archived)
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="采集 PERF-02 改造前黄金基线")
    parser.add_argument("--window", default=WINDOW)
    parser.add_argument("--tier", default=TIER.value, choices=tuple(item.value for item in StageTier))
    parser.add_argument("--out", default=None)
    parser.add_argument("--archive-dir", default=None)
    parser.add_argument("--small", action="store_true")
    args = parser.parse_args(argv)

    tier = StageTier(args.tier)
    out = Path(args.out) if args.out else (DEFAULT_SMALL_OUT if args.small else DEFAULT_OUT)
    archive_dir = Path(args.archive_dir) if args.archive_dir else DEFAULT_ARCHIVE_DIR
    try:
        record, archived, archive_name = collect(small=args.small, window=args.window, tier=tier)
        write_golden(record, out, archive_dir, archived, archive_name)
    except GoldenError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                key: record[key]
                for key in ("payload_sha256", "digest", "snapshot_id", "archive_sha256", "archive_bytes")
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())