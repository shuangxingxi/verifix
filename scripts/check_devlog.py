from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEVLOG = ROOT / "docs" / "devlog"

STEPS: tuple[tuple[str, str, str], ...] = (
    ("01-requirement.md", "[step-1/requirement]", "需求理解"),
    ("02-codegen.md", "[step-2/codegen]", "代码生成"),
    ("03-build.md", "[step-3/build]", "项目构建"),
    ("04-bootstrap.md", "[step-4/bootstrap]", "问题修复"),
    ("05-release.md", "[step-5/release]", "部署上线"),
)

RECORDED_AT = re.compile(r"^-\s*记录时间：\s*(\d{4}-\d{2}-\d{2})", re.MULTILINE)
STATUS = re.compile(r"^-\s*状态：\s*(.+)$", re.MULTILINE)
NOT_EXECUTED = ("未执行", "阻塞", "UNVERIFIED")


@dataclass
class StepResult:
    step: str
    file: str
    exists: bool
    recorded_at: str = ""
    status: str = ""
    blocking: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blocking


@dataclass
class Report:
    steps: list[StepResult]
    global_blocking: list[str]
    git_commits: dict[str, int]

    @property
    def blocking_total(self) -> int:
        return sum(len(item.blocking) for item in self.steps) + len(self.global_blocking)

    @property
    def passed(self) -> bool:
        return self.blocking_total == 0


def _parse_step(name: str, prefix: str, label: str, devlog: Path | None = None) -> StepResult:
    path = (devlog or DEVLOG) / name
    try:
        shown = str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        shown = str(path).replace("\\", "/")
    result = StepResult(step=f"{label} {prefix}", file=shown, exists=path.is_file())
    if not result.exists:
        result.blocking.append("记录文件缺失")
        return result
    text = path.read_text(encoding="utf-8", errors="replace")
    recorded = RECORDED_AT.search(text)
    if recorded is None:
        result.blocking.append("缺少记录时间（- 记录时间：YYYY-MM-DD）")
    else:
        result.recorded_at = recorded.group(1)
        try:
            date.fromisoformat(result.recorded_at)
        except ValueError:
            result.blocking.append(f"记录时间格式非法：{result.recorded_at}")
    status = STATUS.search(text)
    result.status = status.group(1).strip() if status else ""
    if not result.status:
        result.blocking.append("缺少状态声明（- 状态：...）")
    elif any(token in result.status for token in NOT_EXECUTED):
        result.blocking.append(f"环节未执行：{result.status}")
    if prefix not in text:
        result.blocking.append(f"记录正文未出现提交前缀 {prefix}")
    return result


def _git_commits() -> dict[str, int]:
    if not (ROOT / ".git").exists():
        return {}
    try:
        completed = subprocess.run(
            ["git", "log", "--format=%s"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if completed.returncode != 0:
        return {}
    subjects = [line for line in completed.stdout.splitlines() if line.strip()]
    counts: dict[str, int] = {}
    for _name, prefix, _label in STEPS:
        counts[prefix] = sum(1 for subject in subjects if subject.startswith(prefix))
    return counts


def build_report(devlog: Path | None = None, skip_git: bool = False) -> Report:
    steps = [_parse_step(name, prefix, label, devlog) for name, prefix, label in STEPS]
    global_blocking: list[str] = []

    dates = [date.fromisoformat(item.recorded_at) for item in steps if item.recorded_at and item.ok]
    for previous, current in zip(dates, dates[1:]):
        if current < previous:
            global_blocking.append(f"时间序列倒退：{previous.isoformat()} -> {current.isoformat()}")

    commits = {} if skip_git else _git_commits()
    if skip_git:
        pass
    elif not commits:
        global_blocking.append("非 Git 仓库或无法读取提交历史，提交前缀完整性无法校验（不视为通过）")
    else:
        for prefix, count in commits.items():
            if count < 1:
                global_blocking.append(f"缺少带前缀 {prefix} 的提交")
    return Report(steps=steps, global_blocking=global_blocking, git_commits=commits)


def render_text(report: Report) -> str:
    lines = ["五步留痕自检", "=" * 40]
    for item in report.steps:
        marker = "OK" if item.ok else "BLOCKED"
        lines.append(f"[{marker}] {item.step} -> {item.file}")
        if item.recorded_at:
            lines.append(f"        记录时间：{item.recorded_at}")
        if item.status:
            lines.append(f"        状态：{item.status}")
        for reason in item.blocking:
            lines.append(f"        阻塞：{reason}")
    if report.git_commits:
        lines.append("提交前缀统计：")
        for prefix, count in report.git_commits.items():
            lines.append(f"        {prefix}: {count}")
    if report.global_blocking:
        lines.append("全局阻塞：")
        for reason in report.global_blocking:
            lines.append(f"        - {reason}")
    lines.append("-" * 40)
    lines.append(f"阻塞项合计：{report.blocking_total}")
    lines.append("结论：" + ("通过" if report.passed else "未通过（存在阻塞项）"))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查 CodeArts 五步留痕：存在性、时间序列、提交前缀")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出")
    parser.add_argument("--strict", action="store_true", help="存在任何阻塞项即返回 2")
    parser.add_argument("--devlog", default=None, help="留痕目录（默认 docs/devlog）")
    parser.add_argument("--skip-git-check", action="store_true", help="仅脚本自测：跳过 Git 提交前缀校验")
    args = parser.parse_args(argv)
    report = build_report(Path(args.devlog) if args.devlog else None, skip_git=args.skip_git_check)
    if args.json:
        payload = {
            "steps": [asdict(item) | {"ok": item.ok} for item in report.steps],
            "git_commits": report.git_commits,
            "global_blocking": report.global_blocking,
            "blocking_total": report.blocking_total,
            "passed": report.passed,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_text(report))
    return 0 if report.passed else 2


if __name__ == "__main__":
    sys.exit(main())