from __future__ import annotations

import ast
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

SKIP_PARTS = frozenset({".git", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache"})
DYNAMIC_CALLS = frozenset({"getattr", "setattr", "eval", "exec", "__import__", "import_module", "globals", "locals"})
IGNORED_CALLS = frozenset(
    {
        "print",
        "len",
        "range",
        "str",
        "int",
        "float",
        "bool",
        "list",
        "dict",
        "set",
        "tuple",
        "open",
        "enumerate",
        "zip",
        "sorted",
        "min",
        "max",
        "sum",
        "isinstance",
        "jsonify",
        "render_template",
        "connect",
        "fetchall",
        "execute",
    }
)


@dataclass(frozen=True)
class FunctionNode:
    node_id: str
    file: str
    name: str
    line_start: int
    line_end: int
    calls: tuple[str, ...] = ()
    dynamic: bool = False


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _parse_path(args: tuple[str, str]) -> tuple[list[FunctionNode], str | None]:
    raw_path, raw_root = args
    path = Path(raw_path)
    root = Path(raw_root)
    relative = _relative(path, root)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError as exc:
        return ([], f"{relative}: {exc.msg}")
    nodes: list[FunctionNode] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls: set[str] = set()
        dynamic = False
        for child in ast.walk(node):
            if not isinstance(child, ast.Call):
                continue
            name = _call_name(child)
            if name is None:
                continue
            if name in DYNAMIC_CALLS:
                dynamic = True
                continue
            if name in IGNORED_CALLS:
                continue
            calls.add(name)
        end_line = getattr(node, "end_lineno", node.lineno)
        nodes.append(
            FunctionNode(
                node_id=f"{relative}:{node.name}:{node.lineno}",
                file=relative,
                name=node.name,
                line_start=node.lineno,
                line_end=int(end_line),
                calls=tuple(sorted(calls)),
                dynamic=dynamic,
            )
        )
    return (nodes, None)


@dataclass
class CallGraph:
    root: Path
    nodes: dict[str, FunctionNode] = field(default_factory=dict)
    edges: dict[str, set[str]] = field(default_factory=dict)
    by_name: dict[str, list[str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    build_seconds: float = 0.0
    used_process_pool: bool = False

    def callees(self, node_id: str) -> set[str]:
        return set(self.edges.get(node_id, set()))

    def node_for_file_line(self, file: str, line: int | None) -> str | None:
        if line is None:
            return None
        matches = [
            node
            for node in self.nodes.values()
            if node.file == file and node.line_start <= line <= node.line_end
        ]
        if not matches:
            return None
        return min(matches, key=lambda node: node.line_end - node.line_start).node_id

    def node_for_function(self, file: str, function: str) -> str | None:
        for node in self.nodes.values():
            if node.file == file and node.name == function:
                return node.node_id
        return None

    def function_count(self) -> int:
        return len(self.nodes)

    def has_dynamic_calls(self) -> bool:
        return any(node.dynamic for node in self.nodes.values())


def _resolve_edges(graph: CallGraph) -> None:
    for node in graph.nodes.values():
        targets: set[str] = set()
        for callee_name in node.calls:
            candidates = graph.by_name.get(callee_name, [])
            if not candidates:
                continue
            same_file = [candidate for candidate in candidates if graph.nodes[candidate].file == node.file]
            if same_file:
                targets.update(same_file)
            elif len(candidates) == 1:
                targets.add(candidates[0])
            else:
                targets.update(candidates)
        graph.edges[node.node_id] = targets


def build_callgraph(root: Path, use_process_pool: bool = False, pool_threshold: int = 50) -> CallGraph:
    started = time.monotonic()
    root = Path(root).resolve()
    graph = CallGraph(root=root)
    paths = [
        path
        for path in sorted(root.rglob("*.py"))
        if not any(part in SKIP_PARTS for part in path.parts)
    ]
    payloads = [(str(path), str(root)) for path in paths]
    results: list[tuple[list[FunctionNode], str | None]]
    if use_process_pool and len(payloads) >= pool_threshold:
        graph.used_process_pool = True
        with ProcessPoolExecutor() as pool:
            results = list(pool.map(_parse_path, payloads))
    else:
        results = [_parse_path(payload) for payload in payloads]
    for nodes, error in results:
        if error:
            graph.errors.append(error)
        for node in nodes:
            graph.nodes[node.node_id] = node
            graph.by_name.setdefault(node.name, []).append(node.node_id)
    _resolve_edges(graph)
    graph.build_seconds = time.monotonic() - started
    return graph