from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "devlog" / "m4-gray-release-report.md"


@dataclass
class Slot:
    version: str
    traffic: int = 0
    healthy: bool = True


@dataclass
class ReleaseTrail:
    events: list[str] = field(default_factory=list)

    def record(self, message: str) -> None:
        self.events.append(message)


def health(version: str) -> bool:
    return "bad" not in version


def run_release(target: str, steps: list[int], trail: ReleaseTrail, previous: Slot) -> tuple[Slot, bool]:
    slot = Slot(version=target, traffic=0, healthy=health(target))
    for percentage in steps:
        slot.traffic = percentage
        trail.record(f"{target} 灰度 {percentage}% 健康={slot.healthy}")
        if not slot.healthy:
            slot.traffic = 0
            previous.traffic = 100
            trail.record(f"灰度失败，回滚到 {previous.version} 100%")
            return slot, False
    trail.record(f"{target} 发布完成，流量 100%")
    return slot, True


def main() -> int:
    trail = ReleaseTrail()
    stable = Slot(version="v1", traffic=100)
    stable, ok_v2 = run_release("v2", [5, 50, 100], trail, stable)
    broken, ok_v3 = run_release("v3-bad", [5, 50, 100], trail, stable)

    lines = [
        "# M4 灰度与回滚演练报告",
        "",
        f"- 生成时间：{datetime.now(timezone.utc).isoformat()}",
        "- 演练方式：本地模拟流量分档与健康检查（不依赖云资源）",
        "",
        "## 演练记录",
        "",
    ]
    lines.extend(f"- {event}" for event in trail.events)
    lines.extend(
        [
            "",
            f"- v2 发布结果：{'成功' if ok_v2 else '失败'}",
            f"- v3-bad 发布结果：{'成功' if ok_v3 else '失败（已回滚）'}",
            f"- 回滚后稳定版本：{stable.version} {stable.traffic}%",
            "",
            f"结论：{'PASS' if ok_v2 and not ok_v3 and stable.traffic == 100 else 'FAIL'}",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines), encoding="utf-8")

    print(f"v2={ok_v2} v3_bad={ok_v3} stable={stable.version}@{stable.traffic}%")
    print(f"report={REPORT}")
    if ok_v2 and not ok_v3 and stable.traffic == 100:
        print("PASS")
        return 0
    print("FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())