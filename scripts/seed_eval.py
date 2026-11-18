from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

TARGET = ROOT / "verifix-target"
OUT_DIR = ROOT / "eval"


def load_ground_truth() -> list[dict]:
    payload = json.loads((TARGET / "ground_truth.json").read_text(encoding="utf-8"))
    return [item for item in payload["items"] if item["defect_class"] in {"C02", "C03"}]


def make_case(index: int, category: str, item: dict, overrides: dict) -> dict:
    body = {
        "case_id": f"EVAL-{index:04d}",
        "category": category,
        "location": {
            "file": item["file"],
            "line": item["line"],
            "component": None,
            "component_version": None,
        },
        "rule_id": "py/sql-injection" if item["defect_class"] == "C02" else "py/command-injection",
        "severity": "HIGH",
        "ground_truth": {
            "reachable": True,
            "fixable": True,
            "expected_fix_kind": "PARAMETERIZED_QUERY" if item["defect_class"] == "C02" else "PARAMETERIZED_COMMAND",
            "should_reject": False,
        },
        "proof_test_path": None,
        "proof_pre_patch": None,
        "proof_post_patch": None,
    }
    body["ground_truth"].update(overrides.pop("ground_truth", {}))
    body.update(overrides)
    digest_source = {key: value for key, value in body.items() if key != "content_digest"}
    body["content_digest"] = hashlib.sha256(
        json.dumps(digest_source, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return body


def main() -> int:
    items = load_ground_truth()
    if not items:
        print("FAIL: ground_truth has no injection items")
        return 1

    cases: list[dict] = []
    index = 1

    for offset in range(20):
        item = items[offset % len(items)]
        cases.append(
            make_case(
                index,
                "POSITIVE",
                item,
                {
                    "proof_test_path": f"tests/security/test_eval_{index:04d}.py",
                    "proof_pre_patch": "FAIL",
                    "proof_post_patch": "PASS",
                },
            )
        )
        index += 1

    for offset in range(15):
        item = items[offset % len(items)]
        cases.append(
            make_case(
                index,
                "NEGATIVE",
                item,
                {
                    "ground_truth": {
                        "reachable": False,
                        "fixable": False,
                        "expected_fix_kind": "PARAMETERIZED_QUERY",
                        "should_reject": False,
                    },
                    "rule_id": "py/path-traversal",
                },
            )
        )
        index += 1

    for offset in range(10):
        item = items[offset % len(items)]
        cases.append(make_case(index, "BOUNDARY", item, {}))
        index += 1

    for offset in range(5):
        item = items[offset % len(items)]
        cases.append(
            make_case(
                index,
                "ADVERSARIAL",
                item,
                {
                    "ground_truth": {
                        "reachable": True,
                        "fixable": True,
                        "expected_fix_kind": "PARAMETERIZED_QUERY",
                        "should_reject": True,
                    }
                },
            )
        )
        index += 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    existing = OUT_DIR / "eval_set.json"
    if existing.is_file() and not ({"--force", "--rebuild-legacy"} & set(sys.argv[1:])):
        print(
            "REFUSED: eval/eval_set.json 已存在且已退役。该文件是只读历史产物，"
            "重建会改变整文件摘要并破坏退役登记。确需重建请显式传 --force，"
            "并随后重新执行 scripts/split_eval.py。"
        )
        raise SystemExit(1)
    payload = {
        "version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases": cases,
    }
    target = OUT_DIR / "eval_set.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    digest = hashlib.sha256(
        json.dumps(cases, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    (OUT_DIR / "eval_set.sha256").write_text(
        json.dumps({"sha256": digest, "count": len(cases)}, indent=2), encoding="utf-8"
    )
    (OUT_DIR / ".gitignore").write_text("*\n", encoding="utf-8")

    print("WARNING: 本脚本只用于重建历史单文件夹具；产物必须经 scripts/split_eval.py 拆分，"
          "不得直接用于评测运行（运行期装载会返回 VF-8002）。")
    print(f"cases={len(cases)} digest={digest[:12]}…")
    for name in ("POSITIVE", "NEGATIVE", "BOUNDARY", "ADVERSARIAL"):
        count = sum(1 for case in cases if case["category"] == name)
        print(f"  {name}={count} ({count / len(cases):.0%})")
    print(f"written: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())