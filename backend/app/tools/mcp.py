from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from app.tools.errors import ForbiddenBranchError, ToolArgumentError, ToolNotFoundError
from app.tools.workspace import LocalRepoPublisher, LocalWorkspace

TOOL_VERSION = "1.0.0"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    tool_id: str
    version: str
    handler: Callable[[dict[str, Any]], dict[str, Any]]


class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: int | str | None = None
    method: str
    params: dict[str, Any] = {}


class JsonRpcError(BaseModel):
    code: int
    message: str


class JsonRpcResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: int | str | None = None
    result: dict[str, Any] | None = None
    error: JsonRpcError | None = None


ALLOWED_TOOLS: tuple[str, ...] = (
    "repo.read_tree",
    "repo.read_file",
    "repo.search_symbol",
    "workspace.write_file",
    "workspace.run_tests",
    "workspace.diff",
    "repo.publish_branch",
    "repo.open_pr",
)


class McpServer:
    def __init__(self, workspace: LocalWorkspace, publisher: LocalRepoPublisher):
        self.workspace = workspace
        self.publisher = publisher
        self._tools: dict[str, ToolSpec] = {}
        self._register_builtin()

    def _register_builtin(self) -> None:
        specs = [
            ToolSpec("repo.read_tree", "TOOL-01", TOOL_VERSION, self._read_tree),
            ToolSpec("repo.read_file", "TOOL-02", TOOL_VERSION, self._read_file),
            ToolSpec("repo.search_symbol", "TOOL-03", TOOL_VERSION, self._search_symbol),
            ToolSpec("workspace.write_file", "TOOL-04", TOOL_VERSION, self._write_file),
            ToolSpec("workspace.run_tests", "TOOL-05", TOOL_VERSION, self._run_tests),
            ToolSpec("workspace.diff", "TOOL-06", TOOL_VERSION, self._diff),
            ToolSpec("repo.publish_branch", "TOOL-07", TOOL_VERSION, self._publish_branch),
            ToolSpec("repo.open_pr", "TOOL-08", TOOL_VERSION, self._open_pr),
        ]
        for spec in specs:
            self._tools[spec.name] = spec

    def tools(self) -> list[dict[str, str]]:
        return [
            {"name": spec.name, "tool_id": spec.tool_id, "tool_version": spec.version}
            for spec in self._tools.values()
        ]

    def invoke(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        spec = self._tools.get(name)
        if spec is None:
            raise ToolNotFoundError(name)
        return spec.handler(params)

    def handle(self, request: JsonRpcRequest) -> JsonRpcResponse:
        try:
            if request.method == "tools/list":
                return JsonRpcResponse(id=request.id, result={"tools": self.tools()})
            if request.method != "tools/call":
                if request.method in self._tools:
                    return JsonRpcResponse(id=request.id, result=self.invoke(request.method, request.params))
                return JsonRpcResponse(id=request.id, error=JsonRpcError(code=-32601, message=f"method not found: {request.method}"))
            name = str(request.params.get("name", ""))
            arguments = request.params.get("arguments") or {}
            if not isinstance(arguments, dict):
                raise ToolArgumentError(name, "arguments must be an object")
            return JsonRpcResponse(id=request.id, result=self.invoke(name, arguments))
        except ToolNotFoundError as exc:
            return JsonRpcResponse(id=request.id, error=JsonRpcError(code=-32601, message=str(exc)))
        except ToolArgumentError as exc:
            return JsonRpcResponse(id=request.id, error=JsonRpcError(code=-32602, message=str(exc)))
        except ForbiddenBranchError as exc:
            return JsonRpcResponse(id=request.id, error=JsonRpcError(code=-32003, message=str(exc)))

    def _read_tree(self, params: dict[str, Any]) -> dict[str, Any]:
        subdir = str(params.get("subdir", "."))
        return {"entries": self.workspace.read_tree(subdir)}

    def _read_file(self, params: dict[str, Any]) -> dict[str, Any]:
        path = str(params.get("path", ""))
        if not path:
            raise ToolArgumentError("repo.read_file", "path is required")
        return {"path": path, "content": self.workspace.read_file(path)}

    def _search_symbol(self, params: dict[str, Any]) -> dict[str, Any]:
        symbol = str(params.get("symbol", ""))
        return {"hits": self.workspace.search_symbol(symbol, str(params.get("subdir", ".")))}

    def _write_file(self, params: dict[str, Any]) -> dict[str, Any]:
        path = str(params.get("path", ""))
        content = str(params.get("content", ""))
        if not path:
            raise ToolArgumentError("workspace.write_file", "path is required")
        return self.workspace.write_file(path, content)

    def _run_tests(self, params: dict[str, Any]) -> dict[str, Any]:
        test_path = str(params.get("test_path", ""))
        if not test_path:
            raise ToolArgumentError("workspace.run_tests", "test_path is required")
        result = self.workspace.run_tests(test_path, str(params.get("source_dir", ".")))
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_ms": result.duration_ms,
            "timed_out": result.timed_out,
            "policy_digest": result.policy_digest,
        }

    def _diff(self, params: dict[str, Any]) -> dict[str, Any]:
        base = params.get("base_dir")
        if not base:
            raise ToolArgumentError("workspace.diff", "base_dir is required")
        summary = self.workspace.diff(Path(str(base)))
        return {
            "diff": summary.text,
            "files_changed": summary.files_changed,
            "lines_added": summary.lines_added,
            "lines_removed": summary.lines_removed,
            "lines_changed": summary.lines_changed,
        }

    def _publish_branch(self, params: dict[str, Any]) -> dict[str, Any]:
        branch = str(params.get("branch", ""))
        message = str(params.get("commit_message", ""))
        diff_ref = str(params.get("diff_ref", ""))
        if not branch or not diff_ref:
            raise ToolArgumentError("repo.publish_branch", "branch and diff_ref are required")
        return self.publisher.publish_branch(branch, message, diff_ref)

    def _open_pr(self, params: dict[str, Any]) -> dict[str, Any]:
        branch = str(params.get("branch", ""))
        if not branch:
            raise ToolArgumentError("repo.open_pr", "branch is required")
        return self.publisher.open_pr(
            branch,
            str(params.get("title", "")),
            str(params.get("body_ref", "")),
            str(params.get("base", "main")),
        )