from __future__ import annotations


class ToolError(Exception):
    pass


class ToolNotFoundError(ToolError):
    def __init__(self, tool: str):
        self.tool = tool
        super().__init__(f"tool not allowed or unknown: {tool}")


class ToolArgumentError(ToolError):
    def __init__(self, tool: str, detail: str):
        self.tool = tool
        super().__init__(f"{tool}: {detail}")


class ForbiddenBranchError(ToolError):
    def __init__(self, branch: str, reason: str = "protected branch"):
        self.branch = branch
        super().__init__(f"protected branch rejected: {branch} ({reason})")


class PathEscapeError(ToolError):
    def __init__(self, path: str):
        self.path = path
        super().__init__(f"path escapes workspace root: {path}")