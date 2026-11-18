from __future__ import annotations

import ast
import difflib
import re
from dataclasses import dataclass, field

from app.domain.enums import DefectClass, FixParadigm
from app.domain.models import Alert, Issue

GUARD_STRENGTH: dict[FixParadigm, float] = {
    FixParadigm.VERSION_UPGRADE: 0.95,
    FixParadigm.PARAMETERIZED_QUERY: 0.90,
    FixParadigm.PARAMETERIZED_COMMAND: 0.90,
    FixParadigm.CREDENTIAL_EXTERNALIZATION: 0.85,
}

WEAK_PATTERNS = ("replace(", "escape(", "sanitize(", "strip(")
PLACEHOLDER_PATTERN = re.compile(r"['\"]?%[sd]['\"]?")


class PatchGenerationError(Exception):
    pass


@dataclass(frozen=True)
class PatchCandidate:
    files: dict[str, str]
    diff: str
    lines_changed: int
    files_changed: int
    fix_paradigm: FixParadigm
    strength: float
    rationale: str
    referenced_files: tuple[str, ...] = field(default_factory=tuple)


def _unified_diff(old_files: dict[str, str], new_files: dict[str, str]) -> tuple[str, int]:
    chunks: list[str] = []
    changed = 0
    for path in sorted(set(old_files) | set(new_files)):
        old = old_files.get(path, "").splitlines(keepends=True)
        new = new_files.get(path, "").splitlines(keepends=True)
        if old == new:
            continue
        for line in difflib.unified_diff(old, new, fromfile=f"a/{path}", tofile=f"b/{path}"):
            if line.startswith("---") or line.startswith("+++"):
                chunks.append(line)
                continue
            if line.startswith("+") or line.startswith("-"):
                changed += 1
            chunks.append(line)
    return "".join(chunks), changed


def _finalize(old_files: dict[str, str], new_files: dict[str, str], paradigm: FixParadigm, rationale: str,
              changed_files: tuple[str, ...]) -> PatchCandidate:
    diff, lines_changed = _unified_diff(old_files, new_files)
    return PatchCandidate(
        files=new_files,
        diff=diff,
        lines_changed=lines_changed,
        files_changed=len(set(changed_files)),
        fix_paradigm=paradigm,
        strength=GUARD_STRENGTH[paradigm],
        rationale=rationale,
        referenced_files=changed_files,
    )


def _smallest_assign(tree: ast.AST, line: int) -> ast.Assign | ast.AnnAssign | None:
    candidates = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and node.lineno <= line <= getattr(node, "end_lineno", node.lineno)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda node: getattr(node, "end_lineno", node.lineno) - node.lineno)


def _find_execute(node: ast.AST) -> ast.Call | None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr == "execute":
            return node
        return _find_execute(node.func.value)
    if isinstance(node, ast.Attribute):
        return _find_execute(node.value)
    if isinstance(node, ast.Call):
        return _find_execute(node.func)
    return None


def _tail(node: ast.AST, stop: ast.AST) -> str:
    parts: list[str] = []
    current: ast.AST = node
    while current is not stop:
        if isinstance(current, ast.Call) and isinstance(current.func, ast.Attribute):
            parts.append(f".{current.func.attr}()")
            current = current.func.value
        elif isinstance(current, ast.Attribute):
            parts.append(f".{current.attr}")
            current = current.value
        else:
            break
    return "".join(reversed(parts))


def _flatten_add(node: ast.AST) -> list[ast.AST]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _flatten_add(node.left) + _flatten_add(node.right)
    return [node]


def _sql_and_params(expr: ast.AST) -> tuple[str, list[str]]:
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Mod):
        if not isinstance(expr.left, ast.Constant) or not isinstance(expr.left.value, str):
            raise PatchGenerationError("unsupported % formatting")
        text = expr.left.value
        count = len(PLACEHOLDER_PATTERN.findall(text))
        text = PLACEHOLDER_PATTERN.sub("?", text)
        right = expr.right
        if isinstance(right, ast.Tuple):
            params = [ast.unparse(item) for item in right.elts]
        else:
            params = [ast.unparse(right)]
        if count and len(params) != count:
            raise PatchGenerationError("placeholder/parameter count mismatch")
        return text, params

    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
        parts = _flatten_add(expr)
        sql_parts: list[str] = []
        params: list[str] = []
        previous_name = False
        for part in parts:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                text = part.value
                if previous_name and text.startswith("'"):
                    text = text[1:]
                sql_parts.append(text)
                previous_name = False
            elif isinstance(part, (ast.Name, ast.Attribute, ast.Subscript)):
                if sql_parts and sql_parts[-1].endswith("'"):
                    sql_parts[-1] = sql_parts[-1][:-1]
                sql_parts.append("?")
                params.append(ast.unparse(part))
                previous_name = True
            else:
                raise PatchGenerationError("unsupported concatenation operand")
        sql = "".join(sql_parts)
        sql = re.sub(r"'%\?%'", "?", sql)
        sql = re.sub(r"'\?%'|'%\?'", "?", sql)
        return sql, params

    if isinstance(expr, ast.JoinedStr):
        text_parts: list[str] = []
        params: list[str] = []
        for value in expr.values:
            if isinstance(value, ast.Constant):
                text_parts.append(str(value.value))
            elif isinstance(value, ast.FormattedValue):
                text_parts.append("?")
                params.append(ast.unparse(value.value))
        return "".join(text_parts), params

    raise PatchGenerationError("unsupported SQL expression")


def rewrite_sql_execute(source: str, line: int) -> tuple[int, int, str]:
    tree = ast.parse(source)
    assign = _smallest_assign(tree, line)
    if isinstance(assign, ast.AnnAssign):
        raise PatchGenerationError("annotated assignment not supported")
    if assign is None or not assign.targets:
        raise PatchGenerationError("no assignment found around reported line")
    execute = _find_execute(assign.value)
    if execute is None or not execute.args:
        raise PatchGenerationError("no execute call found")
    sql, params = _sql_and_params(execute.args[0])
    if not params:
        raise PatchGenerationError("no injectable parameter detected")
    if "LIKE" in sql.upper():
        params = [f'"%" + {param} + "%"' for param in params]
    tail = _tail(assign.value, execute)
    target = ast.unparse(assign.targets[0])
    indent = " " * assign.col_offset
    param_tuple = "(" + ", ".join(params) + ("," if len(params) == 1 else "") + ")"
    new_statement = f"{indent}{target} = conn.execute({sql!r}, {param_tuple}){tail}"
    return assign.lineno, getattr(assign, "end_lineno", assign.lineno), new_statement


def _replace_lines(source: str, start: int, end: int, replacement: str) -> str:
    lines = source.splitlines()
    lines[start - 1 : end] = replacement.splitlines()
    return "\n".join(lines) + ("\n" if source.endswith("\n") else "")


def _command_argv(expr: ast.AST) -> list[ast.AST]:
    parts = _flatten_add(expr)
    argv: list[ast.AST] = []
    for part in parts:
        if isinstance(part, ast.Constant) and isinstance(part.value, str):
            argv.extend(ast.Constant(value=token) for token in part.value.split())
        elif isinstance(part, (ast.Name, ast.Attribute, ast.Subscript)):
            argv.append(part)
        else:
            raise PatchGenerationError("unsupported command operand")
    if not argv:
        raise PatchGenerationError("empty command argv")
    return argv


def rewrite_command_call(source: str, line: int) -> tuple[int, int, str]:
    tree = ast.parse(source)
    assign = _smallest_assign(tree, line)
    if isinstance(assign, ast.AnnAssign):
        raise PatchGenerationError("annotated assignment not supported")
    if assign is None or not assign.targets:
        raise PatchGenerationError("no assignment found around reported line")

    shell_call: ast.Call | None = None
    for node in ast.walk(assign.value):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"popen", "call", "run", "check_output"} and node.args:
                shell_call = node
                break
    if shell_call is None:
        raise PatchGenerationError("no shell command call found")

    argv = _command_argv(shell_call.args[0])
    argv_source = "[" + ", ".join(ast.unparse(node) for node in argv) + "]"
    tail = _tail(assign.value, shell_call)
    target = ast.unparse(assign.targets[0])
    indent = " " * assign.col_offset
    base = f"{target} = subprocess.run({argv_source}, capture_output=True, text=True)"
    if tail.endswith(".read()"):
        new_statement = f"{indent}{base}.stdout"
    elif tail.endswith(".returncode"):
        new_statement = f"{indent}{base}.returncode"
    else:
        new_statement = f"{indent}{base}"
    return assign.lineno, getattr(assign, "end_lineno", assign.lineno), new_statement


def hardcoded_secret_files(issue: Issue) -> None:
    del issue


def render_patch(
    issue: Issue,
    alert: Alert,
    target_root,
    fixed_version: str | None = None,
) -> PatchCandidate:
    from pathlib import Path

    root = Path(target_root)
    relative = alert.location.file
    path = root / relative
    if not path.is_file():
        raise PatchGenerationError(f"target file not found: {relative}")
    original = path.read_text(encoding="utf-8")
    line = alert.location.line or 1

    if issue.defect_class is DefectClass.SQL_INJECTION:
        start, end, statement = rewrite_sql_execute(original, line)
        updated = _replace_lines(original, start, end, statement)
        return _finalize({relative: original}, {relative: updated}, FixParadigm.PARAMETERIZED_QUERY,
                         "参数化查询替换字符串拼接", (relative,))

    if issue.defect_class is DefectClass.COMMAND_INJECTION:
        start, end, statement = rewrite_command_call(original, line)
        updated = _replace_lines(original, start, end, statement)
        return _finalize({relative: original}, {relative: updated}, FixParadigm.PARAMETERIZED_COMMAND,
                         "参数列表替换 shell 拼接", (relative,))

    if issue.defect_class is DefectClass.HARDCODED_SECRET:
        lines = original.splitlines()
        target_line = lines[line - 1]
        match = re.match(r"^(\s*)([A-Za-z_][A-Za-z0-9_]*)\s*=\s*['\"].*['\"]\s*$", target_line)
        if not match:
            raise PatchGenerationError("target line is not a literal secret assignment")
        indent, name = match.group(1), match.group(2)
        lines[line - 1] = f'{indent}{name} = os.environ.get("{name}", "")'
        if not any(item.strip() in {"import os", "import os as _os"} for item in lines):
            lines.insert(0, "import os")
        updated = "\n".join(lines) + "\n"
        return _finalize({relative: original}, {relative: updated}, FixParadigm.CREDENTIAL_EXTERNALIZATION,
                         "凭据外置到环境变量", (relative,))

    if issue.defect_class is DefectClass.DEPENDENCY_CVE:
        component = alert.location.component or ""
        current = alert.location.component_version or ""
        if not component or not current or not fixed_version:
            raise PatchGenerationError("dependency patch requires component, current version and fixed version")
        if current in original and f"{component}=={current}" in original:
            updated = original.replace(f"{component}=={current}", f"{component}=={fixed_version}")
        else:
            raise PatchGenerationError(f"declaration {component}=={current} not found")
        return _finalize({relative: original}, {relative: updated}, FixParadigm.VERSION_UPGRADE,
                         f"依赖升级 {component} {current} -> {fixed_version}", (relative,))

    raise PatchGenerationError(f"unsupported defect class: {issue.defect_class}")