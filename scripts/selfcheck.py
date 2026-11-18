"""自检命令入口（CLI 薄壳）。

用法：python scripts/selfcheck.py [--scope D1,D3,D4] [--dry-run] [--json]
退出码：0 通过 / 2 警告或未验证 / 3 阻塞或人工待填。
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.selfcheck.context import RunLock, SelfcheckContext, Thresholds, utc_now_iso  # noqa: E402
from app.selfcheck.manual import ensure_manual_template, render_draft  # noqa: E402
from app.selfcheck.models import Dimension, Status  # noqa: E402
from app.selfcheck.report import ReportWriter, to_json  # noqa: E402
from app.selfcheck.runner import SelfcheckRunner  # noqa: E402

_SCOPE_CODES = {item.value for item in Dimension}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="selfcheck.py",
        description="M13 自检框架：把每条对外声称逼到证据上（只诊断，不修复）。",
    )
    parser.add_argument("--scope", default=None, help="逗号分隔的 D1,D2,D3,D4,D5；默认全量")
    parser.add_argument("--baseline", default=None, help="上次 selfcheck.json，默认 docs/devlog/selfcheck.json")
    parser.add_argument("--root", default=None, help="仓库根，默认脚本上级目录")
    parser.add_argument("--manual", default=None, help="人工输入，默认 docs/devlog/selfcheck-manual.md")
    parser.add_argument("--jobs", type=int, default=1, help="维度间并行度（1–5，D1 内部始终串行）")
    parser.add_argument("--timeout", type=float, default=None, help="单项上限秒数，默认 600")
    parser.add_argument("--json", action="store_true", help="仅输出 JSON 到 stdout，不写文件")
    parser.add_argument("--dry-run", action="store_true", help="不写归档、不更新索引、不更新入口副本")
    parser.add_argument("--no-report", action="store_true", help="写归档，但 stdout 输出 JSON")
    parser.add_argument("--allow-writes", action="store_true", help="允许 D1-4 真正执行并写 eval/runs")
    parser.add_argument("--refresh-evidence", action="store_true", help="允许 D1-6 重跑沙箱并写 .evidence")
    return parser


def _parse_scope(raw: str | None) -> tuple[str, ...] | None:
    if raw is None:
        return None
    parts = {item.strip().upper() for item in raw.split(",") if item.strip()}
    invalid = parts - _SCOPE_CODES
    if invalid or not parts:
        raise ValueError("invalid --scope: " + ",".join(sorted(invalid) or ["<empty>"]))
    return tuple(sorted(parts))


def _resolve(root: Path, value: str | None, default: str) -> Path:
    candidate = Path(value) if value else Path(default)
    return candidate if candidate.is_absolute() else root / candidate


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else 2
    root = Path(args.root).resolve() if args.root else REPO_ROOT
    try:
        scope = _parse_scope(args.scope)
    except ValueError as exc:
        print(f"[selfcheck] {exc}", file=sys.stderr)
        parser.print_usage(sys.stderr)
        return 2
    if args.jobs < 1 or args.jobs > 5:
        print("[selfcheck] --jobs 取值必须为 1–5", file=sys.stderr)
        return 2

    thresholds = Thresholds()
    if args.timeout is not None:
        thresholds = dataclasses.replace(thresholds, item_timeout=args.timeout)
    ctx = SelfcheckContext(
        root,
        manual_path=_resolve(root, args.manual, "docs/devlog/selfcheck-manual.md"),
        baseline_path=_resolve(root, args.baseline, "docs/devlog/selfcheck.json"),
        thresholds=thresholds,
        dry_run=args.dry_run,
    )
    ctx.allow_writes = bool(args.allow_writes)
    ctx.refresh_evidence = bool(args.refresh_evidence)
    ctx.scope = scope

    lock = RunLock(ctx.output_dir / ".lock")
    state = lock.acquire(
        {
            "pid": os.getpid(),
            "started_at": utc_now_iso(),
            "scope": list(scope or ()),
            "run_id": "",
        },
        stale_seconds=thresholds.stale_lock_seconds,
    )
    if not state.acquired:
        owner = state.owner or {}
        print(
            f"[selfcheck] 自检进行中（pid={owner.get('pid', '?')}, run_id={owner.get('run_id', '?')}），拒绝并发执行。",
            file=sys.stderr,
        )
        return 3
    if state.reason == "STALE_LOCK_TAKEN":
        ctx.notes.append("已接管陈旧锁（STALE_LOCK_TAKEN）。")
    try:
        result = SelfcheckRunner(ctx).run(scope)
        payload = to_json(result)
        if args.dry_run or args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return result.exit_code
        try:
            outcome = ReportWriter(ctx).write(result)
        except Exception as exc:  # noqa: BLE001 - 写失败必须映射为全局阻塞
            print(f"[selfcheck] 报告写入失败：{type(exc).__name__}: {exc}", file=sys.stderr)
            return 3
        draft_text, draft_count = render_draft(ctx)
        draft_path = root / "docs" / "devlog" / "selfcheck-manual-draft.md"
        draft_path.parent.mkdir(parents=True, exist_ok=True)
        draft_path.write_text(draft_text, encoding="utf-8")
        ensure_manual_template(ctx.manual_path, dry_run=False)
        if args.no_report:
            payload["run_id"] = outcome.run_id
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return result.exit_code
        blocked = sum(1 for item in result.checks if item.status is Status.BLOCKED)
        pending = sum(1 for item in result.checks if item.status is Status.MANUAL_PENDING)
        print(f"自检完成：{result.overall}（退出码 {result.exit_code}）")
        print(f"归档：{outcome.run_id}")
        print(f"报告：{ctx.rel(outcome.report_path)}")
        print(f"实质阻塞 {blocked} 项 / 人工待填 {pending} 项 / 草稿候选 {draft_count} 条")
        return result.exit_code
    except KeyboardInterrupt:
        print("[selfcheck] 已中断，未写归档。", file=sys.stderr)
        return 3
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())