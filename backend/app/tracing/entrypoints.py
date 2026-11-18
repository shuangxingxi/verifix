from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

SKIP_PARTS = frozenset({".git", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache"})
HTTP_DECORATORS = frozenset({"route", "get", "post", "put", "delete", "patch", "websocket"})
SCHEDULER_DECORATORS = frozenset({"task", "shared_task", "periodic_task", "scheduled_job", "cron"})
CONSUMER_DECORATORS = frozenset({"consumer", "kafka_consumer", "rabbit_listener", "subscribe", "on_message"})


class EntryKind(str, Enum):
    HTTP_ROUTE = "HTTP_ROUTE"
    SCHEDULER = "SCHEDULER"
    CONSUMER = "CONSUMER"


@dataclass(frozen=True)
class EntryPoint:
    kind: EntryKind
    file: str
    function: str
    line: int
    route: str = ""

    @property
    def node_hint(self) -> str:
        suffix = f" [{self.route}]" if self.route else ""
        return f"{self.file}:{self.function}{suffix}"


def _decorator_name(node: ast.expr) -> tuple[str | None, str]:
    if isinstance(node, ast.Call):
        func = node.func
        route = ""
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            route = node.args[0].value
        if isinstance(func, ast.Attribute):
            return func.attr, route
        if isinstance(func, ast.Name):
            return func.id, route
        return None, route
    if isinstance(node, ast.Attribute):
        return node.attr, ""
    if isinstance(node, ast.Name):
        return node.id, ""
    return None, ""


def _classify(name: str | None) -> EntryKind | None:
    if name is None:
        return None
    lowered = name.lower()
    if lowered in HTTP_DECORATORS:
        return EntryKind.HTTP_ROUTE
    if lowered in SCHEDULER_DECORATORS:
        return EntryKind.SCHEDULER
    if lowered in CONSUMER_DECORATORS:
        return EntryKind.CONSUMER
    return None


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def discover_entrypoints(root: Path) -> tuple[list[EntryPoint], list[str]]:
    root = Path(root).resolve()
    entrypoints: list[EntryPoint] = []
    errors: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as exc:
            errors.append(f"{_relative(path, root)}: {exc.msg}")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                name, route = _decorator_name(decorator)
                kind = _classify(name)
                if kind is None:
                    continue
                entrypoints.append(
                    EntryPoint(
                        kind=kind,
                        file=_relative(path, root),
                        function=node.name,
                        line=node.lineno,
                        route=route,
                    )
                )
    return entrypoints, errors