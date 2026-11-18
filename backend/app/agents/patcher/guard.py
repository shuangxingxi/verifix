from __future__ import annotations

import re
from dataclasses import dataclass

from app.agents.patcher.templates import WEAK_PATTERNS, PatchCandidate
from app.api.envelope import ErrorCode

COMMENT_ONLY = re.compile(r"^\+\s*#")


@dataclass(frozen=True)
class GuardIssue:
    code: ErrorCode
    rule: str
    detail: str


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    issues: tuple[GuardIssue, ...]
    lines_changed: int
    files_changed: int
    strength: float
    weak_pattern_hits: tuple[str, ...]

    @property
    def first_code(self) -> ErrorCode | None:
        return self.issues[0].code if self.issues else None


def score_strength(candidate: PatchCandidate) -> tuple[float, tuple[str, ...]]:
    added_lines = [line[1:] for line in candidate.diff.splitlines() if line.startswith("+") and not line.startswith("+++")]
    hits = tuple(pattern for pattern in WEAK_PATTERNS if any(pattern in line for line in added_lines))
    if hits:
        return 0.35, hits
    if candidate.fix_paradigm.value == "VERSION_UPGRADE":
        return 0.95, ()
    return candidate.strength, ()


def detect_smuggling(candidate: PatchCandidate, target_files: set[str]) -> tuple[GuardIssue, ...]:
    issues: list[GuardIssue] = []
    if candidate.files_changed > len(target_files):
        issues.append(GuardIssue(ErrorCode.AUDIT_HIT, "R6", "patch touched files outside target"))
    for line in candidate.diff.splitlines():
        if line.startswith("---") or line.startswith("+++"):
            continue
        if COMMENT_ONLY.match(line):
            issues.append(GuardIssue(ErrorCode.AUDIT_HIT, "SMUGGLE-COMMENT", f"unrelated comment added: {line[1:].strip()}"))
        if line.startswith("+") and re.search(r"^\+import (?!os\b|subprocess\b|pathlib\b|sys\b)", line):
            issues.append(GuardIssue(ErrorCode.AUDIT_HIT, "SMUGGLE-IMPORT", f"unexpected import added: {line[1:].strip()}"))
        if line.startswith("+") and re.search(r"(?i)(black|isort|autopep8|格式化)", line):
            issues.append(GuardIssue(ErrorCode.AUDIT_HIT, "SMUGGLE-FORMAT", f"formatting change detected: {line[1:].strip()}"))
    return tuple(issues)


def evaluate(
    candidate: PatchCandidate,
    max_lines: int = 30,
    max_files: int = 3,
    strength_min: float = 0.60,
    target_files: set[str] | None = None,
) -> GuardResult:
    issues: list[GuardIssue] = []
    if candidate.lines_changed > max_lines:
        issues.append(
            GuardIssue(ErrorCode.PATCH_OVERSIZED, "R6", f"lines_changed {candidate.lines_changed} > {max_lines}")
        )
    if candidate.files_changed > max_files:
        issues.append(
            GuardIssue(ErrorCode.PATCH_OVERSIZED, "R6", f"files_changed {candidate.files_changed} > {max_files}")
        )
    strength, hits = score_strength(candidate)
    if strength < strength_min:
        issues.append(
            GuardIssue(ErrorCode.PATCH_WEAK, "STRENGTH", f"patch_strength {strength:.2f} < {strength_min:.2f}")
        )
    if hits:
        issues.append(GuardIssue(ErrorCode.PATCH_WEAK, "WEAK-PATTERN", f"blacklist-style filtering: {', '.join(hits)}"))
    if target_files is not None:
        issues.extend(detect_smuggling(candidate, target_files))
    return GuardResult(
        ok=not issues,
        issues=tuple(issues),
        lines_changed=candidate.lines_changed,
        files_changed=candidate.files_changed,
        strength=strength,
        weak_pattern_hits=hits,
    )