from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.tools.errors import ForbiddenBranchError, PathEscapeError, ToolArgumentError
from app.tools.sandbox import SandboxResult, SandboxRunner

BRANCH_NAMESPACE = "verifix/"
RELEASE_AUTO_BRANCH = "release/auto"
PROTECTED_BRANCHES = frozenset({"main", "master"})
SKIP_DIRS = frozenset({".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv"})


@dataclass(frozen=True)
class DiffSummary:
    text: str
    files_changed: int
    lines_added: int
    lines_removed: int

    @property
    def lines_changed(self) -> int:
        return self.lines_added + self.lines_removed


class LocalWorkspace:
    def __init__(self, root: Path, sandbox: SandboxRunner):
        self.root = Path(root).resolve()
        self.sandbox = sandbox

    def _resolve(self, relative: str) -> Path:
        candidate = (self.root / relative).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise PathEscapeError(relative)
        return candidate

    def read_tree(self, subdir: str = ".") -> list[str]:
        base = self._resolve(subdir)
        if not base.exists():
            raise ToolArgumentError("repo.read_tree", f"{subdir} not found")
        entries: list[str] = []
        for path in sorted(base.rglob("*")):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.is_file():
                entries.append(path.relative_to(self.root).as_posix())
        return entries

    def read_file(self, relative: str) -> str:
        path = self._resolve(relative)
        if not path.is_file():
            raise ToolArgumentError("repo.read_file", f"{relative} is not a file")
        return path.read_text(encoding="utf-8", errors="replace")

    def search_symbol(self, symbol: str, subdir: str = ".") -> list[dict[str, int | str]]:
        if not symbol:
            raise ToolArgumentError("repo.search_symbol", "symbol must not be empty")
        base = self._resolve(subdir)
        hits: list[dict[str, int | str]] = []
        for path in sorted(base.rglob("*.py")):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
                if symbol in line:
                    hits.append({"file": path.relative_to(self.root).as_posix(), "line": line_no})
        return hits

    def write_file(self, relative: str, content: str) -> dict[str, str | int]:
        path = self._resolve(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8")
        path.write_bytes(data)
        return {
            "file": relative,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
        }

    def run_tests(self, test_path: str, source_dir: str = ".") -> SandboxResult:
        source = self._resolve(source_dir)
        return self.sandbox.run_tests(source, test_path)

    def diff(self, base_dir: Path) -> DiffSummary:
        base = Path(base_dir).resolve()
        chunks: list[str] = []
        files_changed = 0
        added = 0
        removed = 0
        for path in sorted(self.root.rglob("*")):
            if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
                continue
            relative = path.relative_to(self.root)
            old_path = base / relative
            old_lines = (
                old_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
                if old_path.is_file()
                else []
            )
            new_lines = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            if old_lines == new_lines:
                continue
            files_changed += 1
            file_diff = list(
                difflib.unified_diff(
                    old_lines,
                    new_lines,
                    fromfile=f"a/{relative.as_posix()}",
                    tofile=f"b/{relative.as_posix()}",
                )
            )
            for line in file_diff:
                if line.startswith("+") and not line.startswith("+++"):
                    added += 1
                elif line.startswith("-") and not line.startswith("---"):
                    removed += 1
            chunks.extend(file_diff)
        return DiffSummary(text="".join(chunks), files_changed=files_changed, lines_added=added, lines_removed=removed)


class LocalRepoPublisher:
    def __init__(self) -> None:
        self.branches: dict[str, dict[str, str]] = {}
        self.pull_requests: list[dict[str, str]] = []
        self.merged: list[str] = []

    def publish_branch(self, branch: str, commit_message: str, diff_ref: str) -> dict[str, str]:
        if branch in PROTECTED_BRANCHES:
            raise ForbiddenBranchError(branch, "main is never writable by the robot")
        if not branch.startswith(BRANCH_NAMESPACE):
            raise ForbiddenBranchError(branch, f"branch must use {BRANCH_NAMESPACE}")
        self.branches[branch] = {"commit_message": commit_message, "diff_ref": diff_ref}
        return {"branch": branch, "diff_ref": diff_ref}

    def open_pr(self, branch: str, title: str, body_ref: str, base: str = "main") -> dict[str, str]:
        if branch not in self.branches:
            raise ToolArgumentError("repo.open_pr", f"branch {branch} has not been published")
        if base in PROTECTED_BRANCHES and base != "main":
            raise ForbiddenBranchError(base)
        record = {"branch": branch, "base": base, "title": title, "body_ref": body_ref}
        self.pull_requests.append(record)
        return record

    def merge_release_auto(self, branch: str) -> dict[str, str]:
        if branch in PROTECTED_BRANCHES:
            raise ForbiddenBranchError(branch, "main is never auto-merged")
        if branch != RELEASE_AUTO_BRANCH:
            raise ForbiddenBranchError(branch, f"automated merge is restricted to {RELEASE_AUTO_BRANCH}")
        self.merged.append(branch)
        return {"merged_into": RELEASE_AUTO_BRANCH, "branch": branch}

    def delete_branch(self, branch: str) -> dict[str, bool]:
        if branch in PROTECTED_BRANCHES:
            raise ForbiddenBranchError(branch)
        existed = self.branches.pop(branch, None) is not None
        return {"branch": branch, "deleted": True, "existed": existed}