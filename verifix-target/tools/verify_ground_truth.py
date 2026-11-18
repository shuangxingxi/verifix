from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GROUND_TRUTH = ROOT / "ground_truth.json"
EXPECTED_COUNTS = {"C01": 3, "C02": 6, "C03": 4, "C05": 2}


def verify() -> list[str]:
    problems: list[str] = []
    data = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
    items = data["items"]
    counts: dict[str, int] = {}
    for item in items:
        counts[item["defect_class"]] = counts.get(item["defect_class"], 0) + 1
        path = ROOT / item["file"]
        if not path.is_file():
            problems.append(f"{item['id']}: file missing {item['file']}")
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        line_no = item.get("line")
        if line_no is not None:
            if not 1 <= line_no <= len(lines):
                problems.append(f"{item['id']}: line {line_no} out of range")
                continue
            needle = item.get("needle", "")
            if needle and needle not in lines[line_no - 1]:
                problems.append(f"{item['id']}: line {line_no} does not contain {needle!r}")
        component = item.get("component")
        if component:
            version = item["version"]
            if f"{component}=={version}" not in "\n".join(lines):
                problems.append(f"{item['id']}: {component}=={version} not declared")
    if counts != EXPECTED_COUNTS:
        problems.append(f"category distribution mismatch: {counts} != {EXPECTED_COUNTS}")
    if len(items) != sum(EXPECTED_COUNTS.values()):
        problems.append(f"item count mismatch: {len(items)}")
    return problems


if __name__ == "__main__":
    failures = verify()
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        sys.exit(1)
    print("ground_truth verified")