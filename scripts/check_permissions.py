from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.adapters.repo import ForbiddenBranchError, LocalRepoAdapter
from app.realscan.evidence import EvidenceScrubber

SCAN_ROOTS = ("backend/app", "scripts", "deploy")
SCAN_SUFFIXES = {".py", ".yml", ".yaml", ".sh", ".json", ".conf", ".env"}
SKIP_NAMES = {".env.example", ".env"}
SKIP_DIRS = {"__pycache__", ".git", "certs"}
DETECTOR_FILES = {"backend/app/tools/redactor.py", "backend/app/realscan/evidence.py"}
SENSITIVE_ENV_TOKENS = ("SECRET", "TOKEN", "PASSWORD", "KEY", "HOST", "ENDPOINT", "DSN")


def check_branch_guard() -> list[str]:
    problems: list[str] = []
    adapter = LocalRepoAdapter()
    attempts = (
        ("create_branch", lambda: adapter.create_branch("repo", "main", "sha-base")),
        ("commit_files", lambda: adapter.commit_files("repo", "main", {"a.py": "x"}, "msg")),
        ("merge_to_release_auto", lambda: adapter.merge_to_release_auto("repo", "main")),
    )
    for name, action in attempts:
        try:
            action()
        except ForbiddenBranchError:
            continue
        problems.append(f"{name}: 对 main 的写入未被拒绝")
    allowed = LocalRepoAdapter()
    try:
        allowed.create_branch("repo", "verifix/ISS-0001", "sha-base")
        allowed.create_branch("repo", "release/auto", "sha-base")
    except ForbiddenBranchError as exc:
        problems.append(f"合法分支被误拒：{exc}")
    return problems


def scan_secrets(roots: list[str] | None = None) -> list[dict[str, str]]:
    scrubber = EvidenceScrubber()
    hits: list[dict[str, str]] = []
    for root_name in roots or SCAN_ROOTS:
        root = Path(root_name)
        if not root.is_absolute():
            root = ROOT / root
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in SCAN_SUFFIXES:
                continue
            try:
                relative = str(path.relative_to(ROOT)).replace("\\", "/")
            except ValueError:
                relative = str(path).replace("\\", "/")
            if path.name in SKIP_NAMES or relative in DETECTOR_FILES:
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for lineno, line in enumerate(lines, start=1):
                if "environ" in line or "getenv" in line:
                    continue
                verdict = scrubber.redact(line)
                if not verdict.redacted:
                    continue
                if all(rule in {"password_assignment", "secret_key_assignment"} for rule in verdict.hits):
                    if not __import__("re").search(r"['\"][^'\"]{6,}['\"]", line):
                        continue
                if True:
                    hits.append(
                        {
                            "file": relative,
                            "line": str(lineno),
                            "rules": ",".join(verdict.hits),
                        }
                    )
    return hits


def check_env_example() -> list[str]:
    problems: list[str] = []
    path = ROOT / ".env.example"
    if not path.is_file():
        return [".env.example 缺失"]
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("VERIFIX_") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if not any(token in key for token in SENSITIVE_ENV_TOKENS):
            continue
        if value.strip() and value.strip() != "change-me":
            problems.append(f".env.example 敏感项含非占位值：{key}")
    return problems


def build_report(scan_roots: list[str] | None = None) -> dict[str, object]:
    branch = check_branch_guard()
    secrets = scan_secrets(scan_roots)
    env = check_env_example()
    blocking = len(branch) + len(secrets) + len(env)
    return {
        "branch_guard": {"ok": not branch, "problems": branch},
        "secret_scan": {"ok": not secrets, "hits": secrets},
        "env_example": {"ok": not env, "problems": env},
        "blocking_total": blocking,
        "passed": blocking == 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="权限基线检查：main 禁写、仓库明文凭据、环境样例占位")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--scan-root", action="append", default=None, help="额外扫描目录（可重复）")
    args = parser.parse_args(argv)
    report = build_report(args.scan_root)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("权限基线检查")
        print("=" * 40)
        print(f"[{'OK' if report['branch_guard']['ok'] else 'BLOCKED'}] main 禁写与分支命名空间")
        for item in report["branch_guard"]["problems"]:
            print(f"        阻塞：{item}")
        print(f"[{'OK' if report['secret_scan']['ok'] else 'BLOCKED'}] 明文凭据扫描")
        for item in report["secret_scan"]["hits"]:
            print(f"        命中：{item['file']} -> {item['rules']}")
        print(f"[{'OK' if report['env_example']['ok'] else 'BLOCKED'}] .env.example 占位")
        for item in report["env_example"]["problems"]:
            print(f"        阻塞：{item}")
        print("-" * 40)
        print(f"阻塞项合计：{report['blocking_total']}")
        print("结论：" + ("通过" if report["passed"] else "未通过（存在阻塞项）"))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())