from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from app.domain.models import Event
from app.tools.errors import ForbiddenBranchError

BRANCH_NAMESPACE = "verifix/"
RELEASE_AUTO_BRANCH = "release/auto"
PROTECTED_BRANCHES = frozenset({"main", "master"})


@dataclass(frozen=True)
class BranchRef:
    branch: str
    base_sha: str


@dataclass(frozen=True)
class CommitRef:
    branch: str
    commit_sha: str
    files: tuple[str, ...]


@dataclass(frozen=True)
class PullRequestRef:
    number: int
    source: str
    target: str
    title: str


@dataclass(frozen=True)
class MergeResult:
    source: str
    target: str
    merged: bool


@dataclass(frozen=True)
class DeletionResult:
    branch: str
    deleted: bool
    existed: bool


@dataclass(frozen=True)
class ContentFingerprint:
    path: str
    sha256: str


class CodeArtsRepoPort(Protocol):
    def create_branch(self, repo: str, branch: str, base_sha: str) -> BranchRef: ...

    def commit_files(self, repo: str, branch: str, files: dict[str, str], message: str) -> CommitRef: ...

    def get_diff(self, repo: str, base_sha: str, head_sha: str) -> str: ...

    def open_pull_request(self, repo: str, source: str, target: str, title: str, body: str) -> PullRequestRef: ...

    def merge_to_release_auto(self, repo: str, source: str) -> MergeResult: ...

    def delete_branch(self, repo: str, branch: str) -> DeletionResult: ...

    def get_file_fingerprint(self, repo: str, ref: str, path: str) -> ContentFingerprint: ...


@dataclass
class LocalRepoAdapter:
    base_files: dict[str, str] = field(default_factory=dict)
    branches: dict[str, dict[str, str]] = field(default_factory=dict)
    branch_base: dict[str, str] = field(default_factory=dict)
    pull_requests: list[PullRequestRef] = field(default_factory=list)
    merged: list[MergeResult] = field(default_factory=list)
    violations: list[dict[str, str]] = field(default_factory=list)

    def _check_branch(self, branch: str) -> None:
        if branch in PROTECTED_BRANCHES:
            self.violations.append({"branch": branch, "reason": "protected branch"})
            raise ForbiddenBranchError(branch, "main is never writable by the robot")
        if not branch.startswith(BRANCH_NAMESPACE) and branch != RELEASE_AUTO_BRANCH:
            self.violations.append({"branch": branch, "reason": "namespace"})
            raise ForbiddenBranchError(branch, f"branch must use {BRANCH_NAMESPACE}")

    def create_branch(self, repo: str, branch: str, base_sha: str) -> BranchRef:
        del repo
        self._check_branch(branch)
        self.branches[branch] = dict(self.base_files)
        self.branch_base[branch] = base_sha
        return BranchRef(branch=branch, base_sha=base_sha)

    def commit_files(self, repo: str, branch: str, files: dict[str, str], message: str) -> CommitRef:
        del repo, message
        self._check_branch(branch)
        if branch not in self.branches:
            raise ForbiddenBranchError(branch, "branch has not been created")
        self.branches[branch].update(files)
        digest = hashlib.sha256("".join(sorted(files)).encode("utf-8")).hexdigest()[:12]
        return CommitRef(branch=branch, commit_sha=f"sha-{digest}", files=tuple(sorted(files)))

    def get_diff(self, repo: str, base_sha: str, head_sha: str) -> str:
        del repo
        branch = next((name for name, sha in self.branch_base.items() if sha == base_sha), None)
        if branch is None:
            return ""
        current = self.branches.get(branch, {})
        chunks: list[str] = []
        for path in sorted(current):
            old = self.base_files.get(path, "").splitlines(keepends=True)
            new = current[path].splitlines(keepends=True)
            if old == new:
                continue
            chunks.extend(difflib.unified_diff(old, new, fromfile=f"a/{path}", tofile=f"b/{path}"))
        del head_sha
        return "".join(chunks)

    def open_pull_request(self, repo: str, source: str, target: str, title: str, body: str) -> PullRequestRef:
        del repo
        self._check_branch(source)
        if target in PROTECTED_BRANCHES and target != "main":
            raise ForbiddenBranchError(target)
        reference = PullRequestRef(number=len(self.pull_requests) + 1, source=source, target=target, title=title)
        self.pull_requests.append(reference)
        del body
        return reference

    def merge_to_release_auto(self, repo: str, source: str) -> MergeResult:
        del repo
        if source in PROTECTED_BRANCHES:
            self.violations.append({"branch": source, "reason": "auto merge to protected"})
            raise ForbiddenBranchError(source, "main is never auto-merged")
        if not source.startswith(BRANCH_NAMESPACE):
            raise ForbiddenBranchError(source, f"automated merge source must use {BRANCH_NAMESPACE}")
        result = MergeResult(source=source, target=RELEASE_AUTO_BRANCH, merged=True)
        self.merged.append(result)
        return result

    def delete_branch(self, repo: str, branch: str) -> DeletionResult:
        del repo
        self._check_branch(branch)
        existed = branch in self.branches
        self.branches.pop(branch, None)
        self.branch_base.pop(branch, None)
        return DeletionResult(branch=branch, deleted=True, existed=existed)

    def get_file_fingerprint(self, repo: str, ref: str, path: str) -> ContentFingerprint:
        del repo
        files = self.branches.get(ref, self.base_files)
        content = files.get(path, "")
        return ContentFingerprint(path=path, sha256=hashlib.sha256(content.encode("utf-8")).hexdigest())

    def load_from_directory(self, root: Path) -> None:
        root = Path(root)
        for path in sorted(root.rglob("*")):
            if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts:
                self.base_files[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8", errors="replace")

    def record_violation(self, event: Event) -> None:
        self.violations.append({"event_id": event.event_id, "run_id": event.run_id})