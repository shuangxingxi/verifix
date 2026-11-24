from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_devlog.py"

STEPS = (
    ("01-requirement.md", "[step-1/requirement]", "2026-11-11"),
    ("02-codegen.md", "[step-2/codegen]", "2026-11-11"),
    ("03-build.md", "[step-3/build]", "2026-11-11"),
    ("04-bootstrap.md", "[step-4/bootstrap]", "2026-11-14"),
    ("05-release.md", "[step-5/release]", "2026-11-14"),
)


def _write_step(root: Path, name: str, prefix: str, day: str, status: str = "已归档") -> None:
    (root / name).write_text(
        f"# {name}\n\n- 记录时间：{day}\n- 状态：{status}\n- 对应提交前缀：`{prefix}`\n",
        encoding="utf-8",
    )


def _run(devlog: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--devlog", str(devlog), *extra],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(ROOT),
        timeout=60,
        check=False,
    )


class CheckDevlogTest(unittest.TestCase):
    def test_all_steps_archived_passes_with_git_check_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, prefix, day in STEPS:
                _write_step(root, name, prefix, day)
            result = _run(root, "--skip-git-check")
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn("结论：通过", result.stdout)

    def test_missing_step_file_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, prefix, day in STEPS:
                _write_step(root, name, prefix, day)
            (root / "03-build.md").unlink()
            result = _run(root, "--skip-git-check")
            self.assertEqual(result.returncode, 2)
            self.assertIn("记录文件缺失", result.stdout)

    def test_unexecuted_step_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, prefix, day in STEPS:
                _write_step(root, name, prefix, day)
            _write_step(root, "05-release.md", "[step-5/release]", "2026-11-14", status="未执行（阻塞）")
            result = _run(root, "--skip-git-check")
            self.assertEqual(result.returncode, 2)
            self.assertIn("环节未执行", result.stdout)

    def test_time_regression_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, prefix, day in STEPS:
                _write_step(root, name, prefix, day)
            _write_step(root, "02-codegen.md", "[step-2/codegen]", "2026-11-20")
            result = _run(root, "--skip-git-check")
            self.assertEqual(result.returncode, 2)
            self.assertIn("时间序列倒退", result.stdout)

    def test_missing_prefix_in_body_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, prefix, day in STEPS:
                _write_step(root, name, prefix, day)
            (root / "02-codegen.md").write_text("# 02\n\n- 记录时间：2026-11-11\n- 状态：已归档\n", encoding="utf-8")
            result = _run(root, "--skip-git-check")
            self.assertEqual(result.returncode, 2)
            self.assertIn("未出现提交前缀", result.stdout)

    def test_real_repository_reports_blocking_not_pass(self) -> None:
        result = _run(ROOT / "docs" / "devlog")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertNotIn("非 Git 仓库", result.stdout)
        self.assertIn("问题修复", result.stdout)
        self.assertIn("部署上线", result.stdout)
        self.assertNotIn("缺少带前缀 [step-4/bootstrap] 的提交", result.stdout)
        self.assertIn("缺少带前缀 [step-5/release] 的提交", result.stdout)
        self.assertIn("阻塞项合计：6", result.stdout)


if __name__ == "__main__":
    unittest.main()