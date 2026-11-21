#!/usr/bin/env python
"""真实时钟短跑观察：origin=runtime，结束时立即评估 M9 可信判定。

不满 86400 秒时结论为未验证，本脚本只产出「真实跑过、时长不足」的证据，
不构成 M9 达标。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.metrics.collectors.runtime_sampler import SelfRunSampleReader
from app.metrics.rules.m9 import M9Thresholds, M9TrustPolicy
from app.runtime.self_run import SelfRunTracker

MAX_INTERVAL_SECONDS = 120


def _hours(seconds: float) -> str:
    return f"{seconds / 3600.0:.4f}h"


def evaluate(sample_path: Path) -> dict:
    reader = SelfRunSampleReader(sample_path)
    samples = reader.latest_n(2000)
    now = datetime.now(timezone.utc)
    thresholds = M9Thresholds()
    verdict = M9TrustPolicy(thresholds).evaluate(samples, now)
    latest = samples[-1] if samples else {}
    continuous = float(latest.get("continuous_seconds") or 0.0)
    target = float(thresholds.min_continuous_seconds)
    return {
        "trusted": verdict.trusted,
        "reason": verdict.reason,
        "label": verdict.label,
        "samples": len(samples),
        "origin": latest.get("origin"),
        "continuous_seconds": continuous,
        "continuous_hours": round(continuous / 3600.0, 4),
        "interruptions": int(latest.get("interruptions") or 0),
        "manual_interventions": int(latest.get("manual_interventions") or 0),
        "target_seconds": target,
        "shortfall_seconds": round(max(0.0, target - continuous), 1),
        "evaluated_at": now.isoformat(),
        "verdict_evidence": verdict.evidence,
    }


def write_summary(summary_path: Path, result: dict, started: datetime, ended: datetime, sample_path: Path) -> None:
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 真实时钟短跑观察证据",
        "",
        f"- 开始（UTC）：{started.isoformat()}",
        f"- 结束（UTC）：{ended.isoformat()}",
        f"- 采样文件：`{sample_path.as_posix()}`",
        f"- origin：`{result['origin']}`",
        f"- 采样条数：{result['samples']}",
        f"- 实测连续时长：{result['continuous_seconds']:.0f} 秒（{result['continuous_hours']} 小时）",
        f"- 中断次数：{result['interruptions']}",
        f"- 人工干预次数：{result['manual_interventions']}",
        f"- 代码阈值：{result['target_seconds']:.0f} 秒",
        f"- 差额：{result['shortfall_seconds']} 秒",
        "",
        "## M9 判定",
        "",
        f"- 可信：{result['trusted']}",
        f"- 原因码：`{result['reason'] or '-'}`",
        f"- 说明：{result['label'] or '真实连续运行具备可信证据'}",
        "",
        "## 口径边界",
        "",
        "本证据证明采样链路在真实时钟、真实 origin 下可用，且如实记录连续时长。",
        "未达 86400 秒，因此 M9 仍为未验证，不得据此声称达标。",
        "",
    ]
    summary_path.write_text("\n".join(lines), encoding="utf-8")
    summary_path.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="真实时钟短跑观察（origin=runtime）")
    parser.add_argument("--duration-seconds", type=int, default=7200)
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--sample-path", default=str(ROOT / ".evidence" / "self-run-short" / "self_run_samples.jsonl"))
    parser.add_argument("--summary-path", default=str(ROOT / ".evidence" / "self-run-short" / "summary.md"))
    args = parser.parse_args(argv)

    if args.duration_seconds <= 0:
        print("FAIL: duration-seconds 必须为正")
        return 2
    if not 0 < args.interval_seconds <= MAX_INTERVAL_SECONDS:
        print(f"FAIL: interval-seconds 必须在 1..{MAX_INTERVAL_SECONDS} 之间（M9 采样间隔上限）")
        return 2

    sample_path = Path(args.sample_path)
    reader = SelfRunSampleReader(sample_path)
    tracker = SelfRunTracker(origin="runtime")

    started = datetime.now(timezone.utc)
    tracker.heartbeat()
    reader.append(tracker.sample().to_dict())
    written = 1
    elapsed = 0

    print(f"start origin=runtime duration={args.duration_seconds}s interval={args.interval_seconds}s sample={sample_path}", flush=True)

    while elapsed < args.duration_seconds:
        step = min(args.interval_seconds, args.duration_seconds - elapsed)
        time.sleep(step)
        elapsed += step
        tracker.heartbeat()
        reader.append(tracker.sample().to_dict())
        written += 1
        print(
            f"t={elapsed}s continuous={tracker.continuous_seconds():.0f}s "
            f"interruptions={tracker.interruptions()} healthy={tracker.is_healthy()}",
            flush=True,
        )

    ended = datetime.now(timezone.utc)
    result = evaluate(sample_path)
    result["samples_written"] = written
    write_summary(Path(args.summary_path), result, started, ended, sample_path)

    print(f"continuous={result['continuous_seconds']:.0f}s interruptions={result['interruptions']}", flush=True)
    print(f"m9_trusted={result['trusted']} reason={result['reason'] or '-'}", flush=True)
    print(f"summary={args.summary_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())