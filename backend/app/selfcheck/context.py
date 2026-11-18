"""自检上下文：路径解析、只读快照、单实例锁、幂等指纹与脱敏。

所有路径拼接集中在本模块；检查项模块只允许经上下文访问器取路径。
本模块是四个允许写盘的通道之一（仅锁文件），其余写通道在 `report.py`。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from app.realscan.evidence import _EVIDENCE_PATTERNS, EvidenceScrubber

TOOL_VERSION = "selfcheck-1.0"
DEFINITION_VERSION = "v2"

_LOCK_NAME = ".lock"
_SNAPSHOT_SINGLE_FILES = (
    "README.md",
    "NOTES.md",
    "sandbox/spec.json",
    "verifix-target/ground_truth.json",
)
_SNAPSHOT_TREES = (
    "deliverables",
    ".evidence",
    "backend/tests",
    "frontend/src",
    "docs/devlog/metrics",
)
_EXCLUDED_DIR_PARTS = frozenset(
    {"__pycache__", ".pytest_cache", ".work", "node_modules", "dist", ".git"}
)
_EXCLUDED_FILE_NAMES = frozenset({"selfcheck-manual-draft.md"})


@dataclass(frozen=True)
class Thresholds:
    orphan_rate: float = 0.1
    min_sample_size: int = 5
    item_timeout: float = 600.0
    regression_timeout: float = 900.0
    build_timeout: float = 900.0
    probe_timeout: float = 30.0
    stale_lock_seconds: int = 1800


def mask(text: str) -> str:
    """对疑似凭据片段做掩码；未命中时原样返回。"""

    if not text:
        return ""
    if not EvidenceScrubber().redact(text).redacted:
        return text
    masked = text
    for _name, pattern in _EVIDENCE_PATTERNS:
        masked = pattern.sub("***MASKED***", masked)
    return masked


class SelfcheckContext:
    def __init__(
        self,
        root: str | Path,
        *,
        output_dir: str | Path | None = None,
        manual_path: str | Path | None = None,
        baseline_path: str | Path | None = None,
        tmp_dir: str | Path | None = None,
        probe: Any | None = None,
        clock: Callable[[], datetime] | None = None,
        thresholds: Thresholds | None = None,
        dry_run: bool = False,
    ) -> None:
        self.root = Path(root).resolve()
        self.output_dir = Path(output_dir).resolve() if output_dir else self.root / "docs" / "devlog" / "selfcheck"
        self.entry_report = self.root / "docs" / "devlog" / "m13-selfcheck-report.md"
        self.entry_json = self.root / "docs" / "devlog" / "selfcheck.json"
        self.manual_path = Path(manual_path).resolve() if manual_path else self.root / "docs" / "devlog" / "selfcheck-manual.md"
        self.baseline_path = Path(baseline_path).resolve() if baseline_path else self.root / "docs" / "devlog" / "selfcheck.json"
        self.tmp_dir = Path(tmp_dir).resolve() if tmp_dir else Path(tempfile.mkdtemp(prefix="selfcheck-"))
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.thresholds = thresholds or Thresholds()
        self.dry_run = dry_run
        self.allow_writes = False
        self.refresh_evidence = False
        self.scope: Optional[tuple[str, ...]] = None
        self.artifacts: dict[str, list[Any]] = {
            "claims": [],
            "evidence": [],
            "consistency": [],
            "delivery": [],
        }
        self.notes: list[str] = []
        self.warnings: list[str] = []
        if probe is None:
            from .probes import SubprocessProbe

            self.probe = SubprocessProbe(self)
        else:
            self.probe = probe

    # ---- 路径访问器 -------------------------------------------------
    def path(self, value: str | Path) -> Path:
        candidate = Path(value)
        return candidate if candidate.is_absolute() else self.root / candidate

    def rel(self, value: str | Path) -> str:
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        try:
            return candidate.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return candidate.name

    def sanitize(self, text: str) -> str:
        """把宿主绝对路径折叠为仓库相对路径，避免用户名目录进入报告。"""

        if not text:
            return ""
        patterns = [str(self.root), str(self.root).replace("\\", "/")]
        for prefix in patterns:
            text = text.replace(prefix, "")
        return text.lstrip("\\/")

    def read_text(self, value: str | Path, default: str | None = None) -> str | None:
        candidate = self.path(value)
        if not candidate.is_file():
            return default
        try:
            return candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return default

    def exists(self, value: str | Path) -> bool:
        return self.path(value).exists()

    def is_within(self, value: str | Path) -> bool:
        candidate = Path(value).resolve()
        for base in (self.root, self.tmp_dir):
            try:
                candidate.relative_to(base)
                return True
            except ValueError:
                continue
        return False

    # ---- 只读快照 ---------------------------------------------------
    def snapshot_paths(self) -> list[str]:
        collected: set[str] = set()
        for single in _SNAPSHOT_SINGLE_FILES:
            if (self.root / single).is_file():
                collected.add(single)
        devlog = self.root / "docs" / "devlog"
        if devlog.is_dir():
            for item in devlog.rglob("*.md"):
                if not item.is_file():
                    continue
                if item.name in _EXCLUDED_FILE_NAMES:
                    continue
                if self._excluded(item):
                    continue
                collected.add(self.rel(item))
        for tree in _SNAPSHOT_TREES:
            base = self.root / tree
            if not base.is_dir():
                continue
            for item in base.rglob("*"):
                if not item.is_file() or self._excluded(item):
                    continue
                collected.add(self.rel(item))
        return sorted(collected)

    @staticmethod
    def _excluded(item: Path) -> bool:
        if any(part in _EXCLUDED_DIR_PARTS for part in item.parts):
            return True
        name = item.name
        if name.startswith(".staging-"):
            return True
        if name in _EXCLUDED_FILE_NAMES:
            return True
        normalized = item.as_posix()
        if "/docs/devlog/selfcheck/" in normalized:
            return True
        if normalized.endswith("/docs/devlog/m13-selfcheck-report.md"):
            return True
        if normalized.endswith("/docs/devlog/selfcheck.json"):
            return True
        if normalized.endswith("/.evidence/self_run_samples.jsonl"):
            return True
        return False

    def snapshot(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for relative in self.snapshot_paths():
            candidate = self.root / relative
            try:
                result[relative] = hashlib.sha256(candidate.read_bytes()).hexdigest()
            except OSError:
                result[relative] = "unreadable"
        return result

    def tree_digest(self, snapshot: dict[str, str] | None = None) -> str:
        mapping = snapshot if snapshot is not None else self.snapshot()
        joined = "\n".join(f"{key}:{mapping[key]}" for key in sorted(mapping))
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()

    def fingerprint(self, scope: Iterable[str] | None = None, baseline_id: str | None = None) -> str:
        scope_text = ",".join(sorted(scope)) if scope is not None else "ALL"
        joined = "|".join(
            (
                scope_text,
                baseline_id or "NO_BASELINE",
                self.tree_digest(),
                DEFINITION_VERSION,
                TOOL_VERSION,
            )
        )
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()


class ReadOnlySnapshot:
    """执行前后摘要比对；只报告差异，不提供任何还原能力。"""

    def __init__(self, ctx: SelfcheckContext) -> None:
        self.ctx = ctx

    def capture(self) -> dict[str, str]:
        return self.ctx.snapshot()

    def diff(self, before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
        added = sorted(set(after) - set(before))
        removed = sorted(set(before) - set(after))
        changed = sorted(key for key in set(before) & set(after) if before[key] != after[key])
        return {"added": added, "removed": removed, "changed": changed}

    def has_diff(self, diff: dict[str, list[str]]) -> bool:
        return any(diff[key] for key in ("added", "removed", "changed"))


@dataclass
class LockState:
    acquired: bool
    reason: str = ""
    owner: dict[str, Any] = field(default_factory=dict)


class RunLock:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.held = False

    def acquire(
        self,
        payload: dict[str, Any] | None = None,
        *,
        stale_seconds: int = 1800,
    ) -> LockState:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
        for attempt in range(2):
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                owner = self._read_owner()
                if attempt == 0 and self._is_stale(owner, stale_seconds):
                    try:
                        self.path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    continue
                return LockState(acquired=False, reason="HELD", owner=owner)
            else:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(body)
                self.held = True
                return LockState(acquired=True, reason="STALE_LOCK_TAKEN" if attempt else "")
        return LockState(acquired=False, reason="HELD", owner=self._read_owner())

    def _read_owner(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _is_stale(owner: dict[str, Any], stale_seconds: int) -> bool:
        pid = owner.get("pid")
        if not isinstance(pid, int):
            return True
        if not _pid_alive(pid):
            return True
        started = str(owner.get("started_at", ""))
        try:
            stamp = datetime.fromisoformat(started)
        except ValueError:
            return True
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - stamp).total_seconds()
        return age > stale_seconds

    def release(self) -> None:
        if not self.held:
            return
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass
        self.held = False


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


_TIME_FMT = "%Y%m%dT%H%M%S%z"


def run_stamp(clock: Callable[[], datetime]) -> str:
    return clock().astimezone().strftime(_TIME_FMT)


def sanitize_output(text: str, ctx: SelfcheckContext) -> str:
    return ctx.sanitize(mask(text))


_ABSOLUTE_PATH_RE = re.compile(r"[A-Za-z]:[\\/][^\s\"']+")


def strip_absolute_paths(text: str, ctx: SelfcheckContext) -> str:
    return _ABSOLUTE_PATH_RE.sub(lambda m: ctx.rel(m.group(0)), text)


def utc_now_iso(clock: Callable[[], datetime] | None = None) -> str:
    return (clock() if clock else datetime.now(timezone.utc)).astimezone().isoformat()


def monotonic() -> float:
    return time.monotonic()