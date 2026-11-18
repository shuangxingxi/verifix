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
from app.eval.models import EvalLoadRecord, EvalVerdict
from app.metrics.eval_special_report import EvalSpecialReportBuilder
from app.metrics.report import ReportOutcome

ARCHIVE_DIR = ROOT / "docs" / "devlog" / "metrics"


def _load_main(report_id: str) -> ReportOutcome:
    path = ARCHIVE_DIR / f"{report_id}.json"
    if not path.is_file():
        raise SystemExit(f"FAIL: 主报告不存在：{path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    md_path = ARCHIVE_DIR / f"{report_id}.md"
    record = MetricReport(
        report_id=payload["report_id"],
        version=int(payload.get("version", 1)),
        window=payload["window"],
        tier=StageTier(payload["tier"]),
        definition_version="v2",
        conclusion=payload["conclusion"],
        generated_at=datetime.fromisoformat(payload["generated_at"]).astimezone(timezone.utc),
        content_digest="",
        archive_ref=str(md_path),
        eval_run_id=payload.get("eval_run_id"),
        binding_digest=payload.get("binding_digest"),
        history_digest=payload.get("history_digest"),
    )
    markdown = md_path.read_text(encoding="utf-8") if md_path.is_file() else ""
    return ReportOutcome(record=record, markdown=markdown, rows=payload.get("rows") or [])


def _load_verdict(eval_run_id: str) -> EvalVerdict | None:
    for candidate in (ROOT / "eval" / "verdicts").glob("*.verdict.json"):
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        if payload.get("eval_run_id") == eval_run_id:
            return EvalVerdict(**payload)
    return None


def _load_record(eval_run_id: str) -> EvalLoadRecord | None:
    for candidate in (ROOT / "eval" / "runs").glob("EVALRUN-*.json"):
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        if payload.get("eval_run_id") != eval_run_id:
            continue
        load = payload.get("load_record")
        if load:
            return EvalLoadRecord(**load)
    return None


def main(argv: list[str] | None = None) -> int:
    config = load_config()
    parser = argparse.ArgumentParser(description="评测专项报告：只引用主报告，不重算")
    parser.add_argument("--main-report-id", required=True, help="主报告 report_id，必填")
    parser.add_argument("--eval-run-id", default=None)
    parser.add_argument("--actor", default="cli")
    args = parser.parse_args(argv)
    main_outcome = _load_main(args.main_report_id)
    eval_run_id = args.eval_run_id or main_outcome.record.eval_run_id or ""
    verdict = _load_verdict(eval_run_id) if eval_run_id else None
    if verdict is None:
        print("FAIL: VF-8006 运行未完成裁决")
        return 1
    load_record = _load_record(eval_run_id)
    try:
        outcome = EvalSpecialReportBuilder(ROOT / config.eval.report_dir).build(
            main_outcome, verdict=verdict, load_record=load_record, actor=args.actor
        )
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}")
        return 1
    print(f"special_report={outcome.report_id}")
    print(f"path={outcome.markdown_path}")
    print(f"conclusion={outcome.conclusion}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())