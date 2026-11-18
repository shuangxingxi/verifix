from __future__ import annotations

import re
from dataclasses import dataclass, field

_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")
_FILE_HEADER = re.compile(r"^\+\+\+ b/(.+)$")
_OLD_HEADER = re.compile(r"^--- a/(.+)$")


@dataclass(frozen=True)
class DiffLine:
    kind: str
    content: str
    file: str
    line_no: int | None


@dataclass
class DiffAnalysis:
    files: list[str] = field(default_factory=list)
    added: list[DiffLine] = field(default_factory=list)
    removed: list[DiffLine] = field(default_factory=list)
    context: list[DiffLine] = field(default_factory=list)
    renames: list[tuple[str, str]] = field(default_factory=list)

    @property
    def files_changed(self) -> int:
        return len(self.files)

    @property
    def lines_added(self) -> int:
        return len(self.added)

    @property
    def lines_removed(self) -> int:
        return len(self.removed)

    @property
    def lines_changed(self) -> int:
        return self.lines_added + self.lines_removed

    def added_text(self) -> str:
        return "\n".join(line.content for line in self.added)

    def removed_text(self) -> str:
        return "\n".join(line.content for line in self.removed)


class DiffAnalyzer:
    def parse(self, text: str) -> DiffAnalysis:
        analysis = DiffAnalysis()
        current_file = ""
        old_file = ""
        new_line = 0
        for raw in text.splitlines():
            if raw.startswith("--- "):
                match = _OLD_HEADER.match(raw)
                if match:
                    old_file = match.group(1)
                continue
            if raw.startswith("+++ "):
                match = _FILE_HEADER.match(raw)
                if match:
                    current_file = match.group(1)
                    if current_file not in analysis.files:
                        analysis.files.append(current_file)
                    if old_file and old_file != current_file:
                        analysis.renames.append((old_file, current_file))
                continue
            if _HUNK_HEADER.match(raw):
                new_line = 0
                continue
            if raw.startswith("\\"):
                continue
            if not current_file:
                continue
            if raw.startswith("+"):
                analysis.added.append(DiffLine("+", raw[1:], current_file, None))
            elif raw.startswith("-"):
                analysis.removed.append(DiffLine("-", raw[1:], current_file, None))
            elif raw.startswith(" "):
                analysis.context.append(DiffLine(" ", raw[1:], current_file, None))

        located = self._locate(text)
        if located:
            analysis.added = located["added"]
            analysis.removed = located["removed"]
            analysis.context = located["context"]
        return analysis

    def _locate(self, text: str) -> dict[str, list[DiffLine]] | None:
        result: dict[str, list[DiffLine]] = {"added": [], "removed": [], "context": []}
        current_file = ""
        new_line = 0
        old_line = 0
        hunk = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
        for raw in text.splitlines():
            if raw.startswith("+++ "):
                match = _FILE_HEADER.match(raw)
                if match:
                    current_file = match.group(1)
                continue
            match = hunk.match(raw)
            if match:
                old_line = int(match.group(1))
                new_line = int(match.group(2))
                continue
            if not current_file or raw.startswith(("---", "diff ", "index ", "\\")):
                continue
            if raw.startswith("+"):
                result["added"].append(DiffLine("+", raw[1:], current_file, new_line))
                new_line += 1
            elif raw.startswith("-"):
                result["removed"].append(DiffLine("-", raw[1:], current_file, old_line))
                old_line += 1
            elif raw.startswith(" "):
                result["context"].append(DiffLine(" ", raw[1:], current_file, new_line))
                old_line += 1
                new_line += 1
        return result if result["added"] or result["removed"] or result["context"] else None

    def adds_conditional(self, analysis: DiffAnalysis) -> bool:
        keywords = ("if ", "elif ", "else:", "switch ", "case ", "match ", "unless ")
        return any(any(keyword in line.content for keyword in keywords) for line in analysis.added)

    def adds_io_or_network(self, analysis: DiffAnalysis) -> bool:
        patterns = (
            "open(",
            "requests.",
            "urllib",
            "socket",
            "http://",
            "https://",
            "os.environ",
            "getenv(",
            "subprocess",
            "system(",
            "pathlib.Path",
        )
        return any(any(pattern in line.content for pattern in patterns) for line in analysis.added)

    def adds_string_const_cmp(self, analysis: DiffAnalysis) -> bool:
        pattern = re.compile(r"""(==|!=)\s*["'][^"']{4,}["']|["'][^"']{4,}["']\s*(==|!=)""")
        return any(pattern.search(line.content) for line in analysis.added)

    def touches_auth_constants(self, analysis: DiffAnalysis) -> bool:
        pattern = re.compile(
            r"\b(SECRET|PASSWORD|PASSWD|TOKEN|AUTH|CRYPTO?|KEY|SALT)[A-Z0-9_]*\s*=\s*['\"]"
        )
        return any(pattern.search(line.content) for line in analysis.added + analysis.removed)