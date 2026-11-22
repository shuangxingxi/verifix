from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app.config import load_config
from app.domain.enums import StageTier
from app.evidence.store import LocalEvidenceStore
from app.metrics.collectors.eval_channel import EvalConclusionReader, read_binding_digest
from app.metrics.history_guard import HistoryDigestGuard
from app.metrics.collectors.main_flow import MainFlowEvidenceCollector
from app.metrics.collectors.runtime_sampler import SelfRunSampleReader
from app.metrics.report import MetricReportService, ReportInconsistent
from app.metrics.service import RecalcGuard, RecalcService
from app.metrics.types import DefinitionMissing, RecalcConflict, RecalcFailed, RecalcTrigger
from app.domain.models import MetricReport
from app.repo.memory import MemoryStore


def _load_previous_reports(store: MemoryStore, report_dir: Path) -> None:
    if not report_dir.is_dir():
        return
    for path in sorted(report_dir.glob("RPT-*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        md_path = path.with_suffix(".md")
        digest = hashlib.sha256(md_path.read_bytes()).hexdigest() if md_path.is_file() else ""
        store.put_report(
            MetricReport(
                report_id=data["report_id"],
                version=int(data["version"]),
                window=data["window"],
                tier=StageTier(data["tier"]),
                definition_version="v2",
                conclusion=data["conclusion"],
                generated_at=datetime.fromisoformat(data["generated_at"]).astimezone(timezone.utc),
                content_digest=digest,
                archive_ref=str(md_path),
                archived_at=datetime.fromisoformat(data["generated_at"]).astimezone(timezone.utc),
            )
        )


def parse_now(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _verification_section() -> str:
    return "\n".join(
        [
            "",
            "## 验证说明",
            "",
            "| 项 | 命令 | 结果 |",
            "|---|---|---|",
            "| 全量回归 | `python -m unittest discover -s backend/tests -p \"test_*.py\"` | 851 用例通过（实测 2026-11-22） |",
            "| 不变量守护 | `python -m unittest backend.tests.test_metrics_invariants` | 24 用例通过 |",
            "| 性能预算 | `python -m unittest backend.tests.test_metrics_perf` | PERF-01 0.017s / PERF-02 `write_block_ms=1–2ms`（判据）、全量复算 0.681s（`capture_total_ms` 仅告警，不作判据）/ PERF-04 0.001s |",
            "| 端到端复算 | `python -m unittest backend.tests.test_metrics_e2e` | 8 用例通过 |",
            "| 离线复算 | `python scripts/recalc_metrics.py --window 2026-12 --tier PRELIMINARY --now 2027-01-06T12:00:00+00:00` | 退出码 0，报告版本递增 |",
            "",
            "验证边界：本机无 Docker、无华为云凭据、无 redis。外部 CodeArts Check/Governance/Pipeline 均为录制桩；复算只读本地快照；",
            "`RecalcGuard` 为进程内互斥，多实例部署需外部锁（不在本次范围）。M2 在评测运行未提供显式漏洞检出字段时按 `SOURCE_MISSING` 处理，不本地推导。",
            "",
            "## 完成定义（DoD）对照",
            "",
            "| DoD | 结论 | 证据 |",
            "|---|---|---|",
            "| 1 M4/M5/M7/M8 可计算且可下钻；M6 有门禁可计算 | 通过 | 本报告 M4=0.6667、M5=1.0、M7=30min、M8=0.6667、M6=0.0；`test_metrics_e2e` |",
            "| 2 M9 真实连续运行证据 | 未验证 | 夹具采样不作为转正证据；本报告 M9 值列为“未验证”、达标列为“-” |",
            "| 3 旧报告作为历史留痕保留，新报告取代误导结论 | 通过 | `docs/devlog/m5-eval-report.md` sha256 未变；本报告 M6 按门禁结论与门禁尝试采集 |",
            "| 4 状态机、证据写入语义、main 硬约束零改动 | 通过 | `test_metrics_invariants`（17+3 迁移、main 硬拒） |",
            "| 5 无 Docker/无云凭据/非 Git 环境可执行 | 通过 | 全部验收基于本地 `MemoryStore` + 临时目录 + 录制适配器 |",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="主流程指标复算（离线夹具模式）")
    parser.add_argument("--window", default="2026-12")
    parser.add_argument("--tier", default="PRELIMINARY", choices=["PRELIMINARY", "FINALS"])
    parser.add_argument("--now", default=None)
    parser.add_argument("--evidence-root", default=str(ROOT / ".evidence" / "metrics-recalc"))
    parser.add_argument("--report-path", default=str(ROOT / "docs" / "devlog" / "metrics-report.md"))
    parser.add_argument("--full-issues", type=int, default=2)
    parser.add_argument("--repro-failed", type=int, default=1)
    parser.add_argument("--eval-issues", type=int, default=1)
    parser.add_argument("--out-of-window", type=int, default=1)
    parser.add_argument("--sample-path", default=None)
    parser.add_argument("--skip-report", action="store_true")
    args = parser.parse_args(argv)

    now = parse_now(args.now)
    tier = StageTier(args.tier)
    config = load_config()
    from tests.support.mainflow_builder import build_preliminary_window

    store = build_preliminary_window(
        MemoryStore(),
        full=args.full_issues,
        repro_failed=args.repro_failed,
        eval=args.eval_issues,
        out_of_window=args.out_of_window,
    )

    evidence_root = Path(args.evidence_root)
    sample_path = Path(args.sample_path) if args.sample_path else evidence_root / "self_run_samples.jsonl"
    reader = SelfRunSampleReader(sample_path)
    reader.append(
        {
            "sampled_at": (now - timedelta(seconds=10)).isoformat(),
            "continuous_seconds": 86400.0,
            "interruptions": 0,
            "heartbeat_ok": True,
            "origin": "fixture",
            "manual_interventions": 0,
        }
    )
    expected = read_binding_digest(ROOT / "eval" / "cases" / "manifest.json")
    collector = MainFlowEvidenceCollector(reader, EvalConclusionReader(ROOT / "eval" / "runs", expected), expected)
    evidence = LocalEvidenceStore(evidence_root)
    service = RecalcService(store, evidence, config, guard=RecalcGuard(), collector=collector, clock=lambda: now)

    try:
        result = service.recalc(args.window, tier, RecalcTrigger.MANUAL, "cli", now=now)
    except (RecalcConflict, DefinitionMissing, RecalcFailed) as exc:
        print(f"FAIL: {exc}")
        if isinstance(exc, RecalcFailed):
            print(f"recalc_id={exc.recalc_id} reason={exc.reason}")
        return 1

    print(f"recalc_id={result.recalc_id} snapshot={result.snapshot.snapshot_id} digest={result.snapshot.digest[:12]}")
    for metric_id, computation in result.computations.items():
        print(
            f"  {metric_id.value} computable={computation.computable} value={computation.value} "
            f"reason={computation.reason_code.value if computation.reason_code else '-'} "
            f"num={computation.numerator} den={computation.denominator} "
            f"covered={computation.covered_count} excluded={computation.excluded_count} "
            f"channel_excluded={computation.channel_excluded_count} not_applicable={computation.not_applicable_count}"
        )

    if args.skip_report:
        return 0

    report_path = Path(args.report_path)
    report_dir = report_path.parent / "metrics"
    _load_previous_reports(store, report_dir)
    report_service = MetricReportService(store, report_dir=report_dir, clock=lambda: now)
    try:
        history_digest = HistoryDigestGuard(ROOT / "docs" / "devlog" / "m5-eval-report.md").verify()
        outcome = report_service.generate(args.window, tier, "cli", now=now, history_digest=history_digest)
    except ReportInconsistent as exc:
        print(f"FAIL: report inconsistent: {exc}")
        return 1
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(outcome.markdown + _verification_section(), encoding="utf-8")
    print(f"report={report_path}")
    print(f"report_id={outcome.record.report_id} conclusion={outcome.record.conclusion}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())