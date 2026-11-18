from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.config import load_config
from app.tools.mcp import JsonRpcRequest, JsonRpcResponse, McpServer
from app.tools.sandbox import SandboxPolicy, SandboxRunner
from app.tools.workspace import LocalRepoPublisher, LocalWorkspace


def build_server(root: Path | None = None) -> McpServer:
    config = load_config()
    workspace_root = Path(root) if root is not None else Path(os.environ.get("VERIFIX_WORKSPACE_ROOT", "."))
    runner = SandboxRunner(SandboxPolicy.from_config(config))
    return McpServer(LocalWorkspace(workspace_root, runner), LocalRepoPublisher())


def serve(stream_in, stream_out) -> int:
    server = build_server()
    for line in stream_in:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            request = JsonRpcRequest(**json.loads(stripped))
        except Exception as exc:
            error = JsonRpcResponse(id=None, error={"code": -32700, "message": f"parse error: {exc}"})
            stream_out.write(error.model_dump_json() + "\n")
            stream_out.flush()
            continue
        response = server.handle(request)
        stream_out.write(response.model_dump_json() + "\n")
        stream_out.flush()
    return 0


def main() -> int:
    return serve(sys.stdin, sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())