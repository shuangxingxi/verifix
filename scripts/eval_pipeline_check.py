from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.eval.leak_scan import LeakScanner


@dataclass(frozen=True)
class Mutation:
    key: str
    path: Path
    old: str
    new: str
    test_module: str


MUTATIONS = {
    "M-01": Mutation(
        "M-01",
        ROOT / "backend" / "app" / "eval" / "runner.py",
        "        self.guard.self_check()\n",
        "        pass  # mutated: self check disabled\n",
        "backend.tests.test_eval_runner",
    ),
    "M-02": Mutation(
        "M-02",
        ROOT / "backend" / "app" / "eval" / "runner.py",
        '            "observations": [item.model_dump(mode="json") for item in self.results],\n',
        '            "verdict_agrees": False,\n            "observations": [item.model_dump(mode="json") for item in self.results],\n',
        "backend.tests.test_eval_runner",
    ),
    "M-03": Mutation(
        "M-03",
        ROOT / "backend" / "app" / "eval" / "runner.py",
        '        if manifest.get("binding_digest") != binding:\n            raise ApiError(ErrorCode.EVAL_DIGEST_MISMATCH, "绑定摘要不符")\n',
        '        if False:  # mutated\n            raise ApiError(ErrorCode.EVAL_DIGEST_MISMATCH, "绑定摘要不符")\n',
        "backend.tests.test_eval_runner",
    ),
    "M-04": Mutation(
        "M-04",
        ROOT / "backend" / "app" / "metrics" / "rules" / "m9.py",
        '        if str(latest.get("origin") or "fixture") != "runtime":\n',
        "        if False:  # mutated\n",
        "backend.tests.test_metrics_m9_trust",
    ),
    "M-05": Mutation(
        "M-05",
        ROOT / "backend" / "app" / "metrics" / "eval_special_report.py",
        '            rows.append({"metric_id": metric_id.value, "ref": f"{main.record.report_id}#{metric_id.value}"})\n',
        '            rows.append({"metric_id": metric_id.value, "ref": f"{main.record.report_id}#{metric_id.value}", "value": 0.0})\n',
        "backend.tests.test_eval_adjudication",
    ),
    "M-06": Mutation(
        "M-06",
        ROOT / "backend" / "app" / "metrics" / "publisher.py",
        "                history_digest = self.history_guard.verify()\n",
        "                history_digest = None  # mutated\n",
        "backend.tests.test_metrics_consistency",
    ),
    "M-07": Mutation(
        "M-07",
        ROOT / "backend" / "app" / "eval" / "isolation.py",
        "        if not _within(resolved, self.cases_dir):\n",
        "        if False:  # mutated\n",
        "backend.tests.test_eval_isolation",
    ),
    "M-08": Mutation(
        "M-08",
        ROOT / "backend" / "app" / "metrics" / "report.py",
        '    if value is None:\n        return "-"\n',
        '    if value is None:\n        return "0"\n',
        "backend.tests.test_metrics_report",
    ),
}

BASELINE_MODULES = (
    "backend.tests.test_eval_runner",
    "backend.tests.test_eval_split",
    "backend.tests.test_eval_isolation",
    "backend.tests.test_eval_adjudication",
    "backend.tests.test_eval_leak",
    "backend.tests.test_metrics_m9_trust",
    "backend.tests.test_metrics_consistency",
    "backend.tests.test_metrics_history_guard",
    "backend.tests.test_metrics_report",
)


def _run_modules(modules: tuple[str, ...] | list[str]) -> int:
    command = [sys.executable, "-m", "unittest", *modules]
    return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace").returncode


def _mutate(key: str) -> int:
    mutation = MUTATIONS[key]
    original = mutation.path.read_text(encoding="utf-8")
    if mutation.old not in original:
        print(f"FAIL: 变异锚点不存在 {key}")
        return 2
    try:
        mutation.path.write_text(original.replace(mutation.old, mutation.new, 1), encoding="utf-8")
        code = _run_modules([mutation.test_module])
    finally:
        mutation.path.write_text(original, encoding="utf-8")
    if code != 0:
        print(f"CAPTURED {key} by {mutation.test_module}")
        return 0
    print(f"MISSED {key} not caught by {mutation.test_module}")
    return 1


def _scan() -> int:
    scanner = LeakScanner()
    targets = [
        scanner.scan_directory(ROOT / "eval" / "cases"),
        scanner.scan_directory(ROOT / "eval" / "runs", "*.jsonl"),
        scanner.scan_paths([ROOT / "docs" / "devlog" / "eval-report.md"]),
    ]
    hits = sum(item.hits for item in targets)
    for item in targets:
        if item.hits:
            print(f"HIT fields={item.hit_fields}")
    print(f"scan_hits={hits}")
    return 0 if hits == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="评测链路变异探针与合规扫描")
    parser.add_argument("--mutate", default=None, choices=["none", *MUTATIONS])
    parser.add_argument("--scan", action="store_true")
    args = parser.parse_args(argv)
    if args.scan:
        return _scan()
    if args.mutate is None:
        parser.error("需要 --mutate 或 --scan")
    if args.mutate == "none":
        code = _run_modules(BASELINE_MODULES)
        print("BASELINE_PASS" if code == 0 else "BASELINE_FAIL")
        return 0 if code == 0 else 1
    return _mutate(args.mutate)


if __name__ == "__main__":
    raise SystemExit(main())