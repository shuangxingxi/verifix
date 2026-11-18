from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.orchestration.guards import ConcurrencyController

REPORT = ROOT / "docs" / "devlog" / "m4-concurrency-report.md"


async def run_batch(concurrency: int, tasks: int) -> dict:
    controller = ConcurrencyController(max_concurrency=concurrency)

    async def worker() -> int:
        async with controller.slot():
            await asyncio.sleep(0.02)
            return 1

    started = time.monotonic()
    results = await asyncio.gather(*(worker() for _ in range(tasks)))
    duration = time.monotonic() - started
    return {
        "concurrency": concurrency,
        "tasks": tasks,
        "completed": sum(results),
        "duration": duration,
        "max_active": controller.max_concurrency,
    }


async def file_conflict() -> dict:
    controller = ConcurrencyController(max_concurrency=3)

    async def hold() -> None:
        async with controller.file_lock("verifix-target", "app/main.py"):
            await asyncio.sleep(0.3)

    holder = asyncio.create_task(hold())
    await asyncio.sleep(0.05)
    queued = False
    message = ""
    try:
        async with controller.file_lock("verifix-target", "app/main.py"):
            pass
    except RuntimeError as exc:
        queued = True
        message = str(exc)
    await holder
    return {"queued": queued, "message": message}


async def main_async() -> int:
    batches = [await run_batch(size, 12) for size in (3, 6, 8)]
    conflict = await file_conflict()
    lines = [
        "# M4 并发压测报告",
        "",
        f"- 生成时间：{datetime.now(timezone.utc).isoformat()}",
        "- 执行方式：asyncio 并发沿 ConcurrencyController 槽位调度（无 Docker）",
        "",
        "| 并发上限 | 任务数 | 完成 | 用时(s) |",
        "|---|---|---|---|",
    ]
    ok = True
    for item in batches:
        lines.append(
            f"| {item['concurrency']} | {item['tasks']} | {item['completed']} | {item['duration']:.3f} |"
        )
        if item["completed"] != item["tasks"]:
            ok = False
    lines.extend(
        [
            "",
            f"- 文件冲突排队：{'是' if conflict['queued'] else '否'}；提示：{conflict['message']}",
            f"- 结论：{'PASS' if ok and conflict['queued'] else 'FAIL'}",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    for item in batches:
        print(f"concurrency={item['concurrency']} tasks={item['tasks']} completed={item['completed']} duration={item['duration']:.3f}s")
    print(f"file_conflict_queued={conflict['queued']} message={conflict['message']}")
    print(f"report={REPORT}")
    if not ok or not conflict["queued"]:
        print("FAIL")
        return 1
    print("PASS")
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())