from __future__ import annotations

import argparse
import dis
import importlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

DEFAULT_TARGETS = (
    "app/orchestration",
    "app/agents/gatekeeper",
    "app/agents/critic",
    "app/agents/patcher",
)
DEFAULT_TESTS = (
    "backend.tests.test_state_machine",
    "backend.tests.test_gate",
    "backend.tests.test_patcher",
    "backend.tests.test_repo_and_service",
    "backend.tests.test_guards",
    "backend.tests.test_state_machine_paths",
    "backend.tests.test_patcher_gateway",
)


def _executable_lines(code) -> set[int]:
    lines = {lineno for _offset, lineno in dis.findlinestarts(code) if lineno}
    for const in code.co_consts:
        if hasattr(const, "co_code"):
            lines |= _executable_lines(const)
    return lines


class _Tracer:
    def __init__(self, roots: list[str]) -> None:
        self.roots = [str(Path(root).resolve()) for root in roots]
        self.hits: dict[str, set[int]] = {}

    def __call__(self, frame, event, arg):
        filename = str(Path(frame.f_code.co_filename).resolve())
        if not any(filename.startswith(root) for root in self.roots):
            return None
        if event == "line":
            self.hits.setdefault(filename, set()).add(frame.f_lineno)
        return self


def _module_files(_modules: list[str], roots: list[str]) -> list[Path]:
    files: set[Path] = set()
    for root in roots:
        for path in Path(root).resolve().rglob("*.py"):
            if path.is_file() and "__pycache__" not in path.parts:
                files.add(path)
    return sorted(files)


def measure(targets: list[str], tests: list[str]) -> dict[str, object]:
    roots = [str(ROOT / "backend" / name) for name in targets]
    tracer = _Tracer(roots)
    suite = unittest.defaultTestLoader.loadTestsFromNames(tests)
    sys.settrace(tracer)
    try:
        result = unittest.TextTestRunner(verbosity=0).run(suite)
    finally:
        sys.settrace(None)
    files = _module_files(targets, roots)
    modules: dict[str, object] = {}
    total_exec = 0
    total_hit = 0
    for path in files:
        try:
            code = compile(path.read_text(encoding="utf-8"), str(path), "exec")
        except (OSError, SyntaxError):
            continue
        executable = _executable_lines(code)
        hit = executable.intersection(tracer.hits.get(str(path), set()))
        total_exec += len(executable)
        total_hit += len(hit)
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        modules[rel] = {
            "executable_lines": len(executable),
            "covered_lines": len(hit),
            "line_coverage": round(len(hit) / len(executable), 4) if executable else 1.0,
        }
    total = round(total_hit / total_exec, 4) if total_exec else 1.0
    return {
        "metric": "line_coverage",
        "branch_coverage_available": False,
        "branch_coverage_note": "coverage.py 不可用（PyPI 不可达），以 sys.settrace 行覆盖替代",
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "total_executable_lines": total_exec,
        "total_covered_lines": total_hit,
        "total_line_coverage": total,
        "threshold": 0.8,
        "passed": total >= 0.8,
        "modules": modules,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="核心判定模块行覆盖率度量（标准库实现）")
    parser.add_argument("--target", action="append", default=None, help="被测模块前缀，可重复")
    parser.add_argument("--test", action="append", default=None, help="测试模块名，可重复")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = measure(args.target or list(DEFAULT_TARGETS), args.test or list(DEFAULT_TESTS))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("核心判定模块覆盖率（行覆盖替代分支覆盖）")
        print("=" * 52)
        for name, item in report["modules"].items():
            print(f"{item['line_coverage']:.1%}  {item['covered_lines']:>4}/{item['executable_lines']:<4}  {name}")
        print("-" * 52)
        print(f"总计：{report['total_line_coverage']:.1%}  阈值：{report['threshold']:.0%}")
        print(f"测试：{report['tests_run']} 运行，失败 {report['failures']}，错误 {report['errors']}")
        print("结论：" + ("达标" if report["passed"] else "未达标（需补用例）"))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())