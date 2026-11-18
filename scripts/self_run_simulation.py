from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.runtime.self_run import SelfRunTracker

REPORT = ROOT / "docs" / "devlog" / "m4-self-run-report.md"


def main() -> int:
    now = [0.0]
    tracker = SelfRunTracker(heartbeat_timeout_seconds=120, clock=lambda: now[0])

    heartbeats = 0
    for _ in range(60):
        now[0] += 60
        tracker.heartbeat()
        heartbeats += 1
    continuous_before = tracker.continuous_seconds()

    now[0] += 600
    tracker.heartbeat()
    interrupted_hours = tracker.continuous_seconds()
    interruptions = tracker.interruptions()

    now[0] += 60
    tracker.heartbeat()
    resumed_seconds = tracker.continuous_seconds()

    idle_tracker = SelfRunTracker(heartbeat_timeout_seconds=120, clock=lambda: 1_000_000.0)
    idle_seconds = idle_tracker.continuous_seconds()

    checks = {
        "continuous_after_60_heartbeats": continuous_before,
        "after_interruption": interrupted_hours,
        "interruptions": interruptions,
        "after_resume": resumed_seconds,
        "idle_never_counts": idle_seconds,
    }
    ok = (
        continuous_before >= 59 * 60
        and interrupted_hours == 0.0
        and interruptions == 1
        and 0.0 < resumed_seconds <= 60.0
        and idle_seconds == 0.0
    )

    lines = [
        "# M4 自运行计数加速模拟报告",
        "",
        f"- 生成时间：{datetime.now(timezone.utc).isoformat()}",
        "- 方式：受控时钟加速模拟（1 步 = 1 分钟），**非真实 24 小时观察**",
        "",
        f"- 心跳次数：{heartbeats}",
        f"- 连续计数（中断前）：{continuous_before:.0f} 秒",
        f"- 中断后计数：{interrupted_hours:.0f} 秒（应为 0）",
        f"- 中断次数：{interruptions}",
        f"- 恢复后计数：{resumed_seconds:.0f} 秒（从恢复起点重算）",
        f"- 无心跳场景计数：{idle_seconds:.0f} 秒（禁止虚增）",
        "",
        f"结论：{'PASS' if ok else 'FAIL'}",
        "",
        "真实 24 小时无人干预观察需在部署环境执行，本报告不能替代 8.5 的验收证据。",
        "",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")

    print(f"continuous_before={continuous_before:.0f}s interruptions={interruptions} resumed={resumed_seconds:.0f}s idle={idle_seconds:.0f}s")
    print(f"report={REPORT}")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())