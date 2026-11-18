from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import load_config
from app.eval.splitter import EvalSetSplitter


def main(argv: list[str] | None = None) -> int:
    config = load_config()
    parser = argparse.ArgumentParser(description="评测集一次性拆分：用例输入集 + 预期答案集")
    parser.add_argument("--dry-run", action="store_true", help="只计算摘要与分布，不写盘")
    parser.add_argument("--apply", action="store_true", help="staging 原子落盘")
    parser.add_argument("--legacy-set", default=config.eval.legacy_set_path)
    parser.add_argument("--set-version", default=config.eval.set_version)
    parser.add_argument("--actor", default="cli")
    parser.add_argument("--cases-dir", default=config.eval.cases_dir)
    parser.add_argument("--expected-dir", default=config.eval.expected_dir)
    args = parser.parse_args(argv)
    if not args.dry_run and not args.apply:
        parser.error("需要指定 --dry-run 或 --apply")

    splitter = EvalSetSplitter(
        ROOT / args.legacy_set,
        ROOT / args.cases_dir,
        ROOT / args.expected_dir,
        args.set_version,
        args.actor,
    )
    try:
        report = splitter.dry_run() if args.dry_run else splitter.apply()
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}")
        return 1
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    print(f"cases={report.case_count} distribution={report.category_distribution}")
    print(f"cases_digest={report.cases_digest}")
    print(f"expected_digest={report.expected_digest}")
    print(f"binding_digest={report.binding_digest}")
    print(f"applied={report.applied} skipped={report.skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())