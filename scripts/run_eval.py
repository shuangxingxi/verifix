from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import load_config
from app.domain.enums import StageTier
from app.domain.models import MetricReport
from app.eval.adjudication import AdjudicationService
from app.eval.loader import ExpectedAnswerReader
from app.eval.runner import EvalRunner
from app.metrics.eval_special_report import EvalSpecialReportBuilder
from app.metrics.report import ReportOutcome

TARGET = ROOT / "verifix-target"
EVAL_DIR = ROOT / "eval"
REPORT = ROOT / "docs" / "devlog" / "eval-report.md"
ARCHIVE_DIR = ROOT / "docs" / "devlog" / "metrics"
LEGACY_REPORT = ROOT / "docs" / "devlog" / "m5-eval-report.md"


def _latest_main_outcome() -> ReportOutcome | None:
    if not ARCHIVE_DIR.is_dir():
        return None
    candidates = sorted(ARCHIVE_DIR.glob("RPT-*.json"))
    if not candidates:
        return None
    path = candidates[-1]
    payload = json.loads(path.read_text(encoding="utf-8"))
    md = path.with_suffix(".md")
    record = MetricReport(
        report_id=payload["report_id"],
        version=int(payload.get("version", 1)),
        window=payload["window"],
        tier=StageTier(payload["tier"]),
        definition_version="v2",
        conclusion=payload["conclusion"],
        generated_at=datetime.fromisoformat(payload["generated_at"]).astimezone(timezone.utc),
        content_digest="",
        archive_ref=str(md),
        eval_run_id=payload.get("eval_run_id"),
        binding_digest=payload.get("binding_digest"),
        history_digest=payload.get("history_digest"),
    )
    return ReportOutcome(
        record=record,
        markdown=md.read_text(encoding="utf-8") if md.is_file() else "",
        rows=payload.get("rows") or [],
    )


def main(argv: list[str] | None = None) -> int:
    config = load_config()
    parser = argparse.ArgumentParser(description="评测链路：启动 -> 驱动 -> 裁决 -> 引用主报告")
    parser.add_argument("--set-version", default=config.eval.set_version, required=False)
    parser.add_argument("--actor", default="cli")
    parser.add_argument("--legacy", action="store_true", help="已退役，传此参数会被拒绝")
    args = parser.parse_args(argv)
    if args.legacy:
        print("FAIL: VF-8002 评测集已退役，请使用 eval/cases 用例输入集")
        return 1

    runner = EvalRunner(config, TARGET, EVAL_DIR / "runs")
    run = runner.start(EVAL_DIR / "cases", args.set_version, "exec")
    rounds = 0
    while run.status not in {"COMPLETED", "SECURITY_ABORTED", "QUARANTINED"}:
        runner.step(run.eval_run_id, limit=5)
        rounds += 1
        if rounds > 30:
            print("FAIL: eval did not complete")
            return 1
    if run.status != "COMPLETED":
        print(f"FAIL: run status={run.status}")
        return 1

    answer_reader = ExpectedAnswerReader(EVAL_DIR / "expected", runner.audit, args.set_version)
    answers = answer_reader.load("judge", run.eval_run_id)
    verdict = AdjudicationService(EVAL_DIR / "verdicts").adjudicate(
        run.eval_run_id, run.binding_digest, answers, run.results
    ).verdict
    runner.mark_adjudicated(run.eval_run_id)

    main_outcome = _latest_main_outcome()
    if main_outcome is None:
        from app.metrics.report import ReportInconsistent

        print("FAIL: 主报告缺失，请先运行 scripts/recalc_metrics.py")
        del ReportInconsistent
        return 1
    builder = EvalSpecialReportBuilder(ROOT / config.eval.report_dir)
    special = builder.build(main_outcome, verdict=verdict, load_record=run.load_record, actor=args.actor)
    print(f"completed={run.completed}/{run.total} rounds={rounds}")
    print(f"eval_run_id={run.eval_run_id} binding={run.binding_digest[:12]}…")
    print(f"M1={verdict.m1.numerator}/{verdict.m1.denominator} M3={verdict.m3.numerator}/{verdict.m3.denominator}")
    print(f"special_report={special.report_id} conclusion={special.conclusion}")
    print(f"report={REPORT}")
    print("legacy_report_untouched=True" if LEGACY_REPORT.is_file() else "legacy_report_absent=True")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())