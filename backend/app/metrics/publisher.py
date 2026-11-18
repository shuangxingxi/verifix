from __future__ import annotations

import json
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path

from app.api.envelope import ApiError, ErrorCode
from app.metrics.consistency import ConsistencyReport, CrossReportConsistencyChecker
from app.metrics.history_guard import HistoryDigestGuard


class ReportVersionLock:
    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._held: set[tuple[str, str]] = set()

    def acquire(self, window: str, tier: str) -> None:
        key = (window, tier)
        with self._guard:
            if key in self._held:
                raise ApiError(ErrorCode.REPORT_VERSION_CONFLICT, f"{window}/{tier} 正在发布")
            self._held.add(key)

    def release(self, window: str, tier: str) -> None:
        with self._guard:
            self._held.discard((window, tier))


@dataclass
class PublishOutcome:
    report_id: str
    markdown: str
    rows: list[dict]
    consistency: ConsistencyReport
    files: list[Path]


class ReportPublisher:
    def __init__(
        self,
        service,
        report_dir: Path | str,
        history_guard: HistoryDigestGuard | None = None,
        lock: ReportVersionLock | None = None,
    ) -> None:
        self.service = service
        self.report_dir = Path(report_dir)
        self.history_guard = history_guard
        self.lock = lock or ReportVersionLock()

    def publish(
        self,
        window: str,
        tier,
        actor: str,
        now=None,
        special_rows: list[dict] | None = None,
        extra_files: dict[str, str] | None = None,
    ) -> PublishOutcome:
        self.lock.acquire(window, tier.value)
        try:
            history_digest = None
            if self.history_guard is not None:
                history_digest = self.history_guard.verify()
            outcome = self.service.generate(window, tier, actor, now=now, history_digest=history_digest)
            checker = CrossReportConsistencyChecker()
            consistency = checker.compare(outcome.rows, special_rows or outcome.rows)
            if special_rows is not None and not consistency.consistent:
                raise ApiError(ErrorCode.REPORT_INCONSISTENT, "跨报告口径不一致，拒绝发布")
            payloads = {
                "md": outcome.markdown,
                "json": json.dumps(
                    {
                        "report_id": outcome.record.report_id,
                        "version": outcome.record.version,
                        "window": window,
                        "tier": tier.value,
                        "conclusion": outcome.record.conclusion,
                        "generated_at": outcome.record.generated_at.isoformat(),
                        "eval_run_id": outcome.record.eval_run_id,
                        "binding_digest": outcome.record.binding_digest,
                        "history_digest": outcome.record.history_digest,
                        "rows": outcome.rows,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                "consistency": json.dumps(consistency.to_dict(), ensure_ascii=False, indent=2),
            }
            for name, text in (extra_files or {}).items():
                payloads[name] = text
            files = self._write_atomic(outcome.record.report_id, payloads)
            return PublishOutcome(
                report_id=outcome.record.report_id,
                markdown=outcome.markdown,
                rows=outcome.rows,
                consistency=consistency,
                files=files,
            )
        finally:
            self.lock.release(window, tier.value)

    def _write_atomic(self, report_id: str, payloads: dict[str, str]) -> list[Path]:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        staging = self.report_dir / f".staging-{report_id}"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        names = {
            "md": self.report_dir / f"{report_id}.md",
            "json": self.report_dir / f"{report_id}.json",
            "consistency": self.report_dir / f"consistency-{report_id}.json",
        }
        for key, text in payloads.items():
            target = names.get(key, self.report_dir / key)
            staged = staging / target.name
            staged.write_text(text, encoding="utf-8")
        replaced: list[tuple[Path, Path | None]] = []
        try:
            for key in ("md", "json", "consistency"):
                if key not in payloads:
                    continue
                target = names[key]
                staged = staging / target.name
                backup = target.with_suffix(target.suffix + ".bak") if target.is_file() else None
                if backup is not None:
                    target.replace(backup)
                staged.replace(target)
                replaced.append((target, backup))
        except Exception:
            for target, backup in reversed(replaced):
                if target.is_file():
                    target.unlink()
                if backup is not None and backup.is_file():
                    backup.replace(target)
            shutil.rmtree(staging, ignore_errors=True)
            raise ApiError(ErrorCode.REPORT_INCONSISTENT, "发布写入失败，已回滚")
        shutil.rmtree(staging, ignore_errors=True)
        for _, backup in replaced:
            if backup is not None and backup.is_file():
                backup.unlink()
        return [names[key] for key in ("md", "json", "consistency") if key in payloads]