import ast
import re
import traceback

SENSITIVE_NAME = re.compile(r"(SECRET|PASSWORD|PASSWD|TOKEN|API_KEY|PRIVATE_KEY)", re.IGNORECASE)
PIN_PATTERN = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*==\s*([0-9][0-9A-Za-z_.\-]*)\s*$")
MAX_SNIPPET = 160
SQL_RULE = "C02-SQL"
CMD_RULE = "C03-CMD"
DEP_RULE = "C01-DEP"
CRED_RULE = "C05-CRED"


def _call_name(node):
    parts = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def _is_dynamic(expr):
    if isinstance(expr, ast.JoinedStr):
        return True
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, (ast.Add, ast.Mod)):
        return True
    if isinstance(expr, ast.Call) and _call_name(expr.func).endswith(".format"):
        return True
    if isinstance(expr, ast.Call) and _call_name(expr.func) == "format":
        return True
    return False


def _snippet(lines, lineno):
    if 1 <= lineno <= len(lines):
        text = lines[lineno - 1].strip()
        return text[:MAX_SNIPPET]
    return ""


def _sql_hits(tree, lines):
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _call_name(node.func).endswith("execute"):
            continue
        if not node.args:
            continue
        argument = node.args[0]
        if _is_dynamic(argument):
            hits.append(
                {
                    "line": argument.lineno,
                    "rule_id": SQL_RULE,
                    "defect_class": "C02",
                    "snippet_masked": _snippet(lines, argument.lineno),
                    "rule_basis": "CWE-89",
                }
            )
    return hits


def _cmd_hits(tree, lines):
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func)
        shell_true = any(
            keyword.arg == "shell"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in node.keywords
        )
        if name in {"os.popen", "os.system", "popen"}:
            if node.args and _is_dynamic(node.args[0]):
                hits.append(
                    {
                        "line": node.args[0].lineno,
                        "rule_id": CMD_RULE,
                        "defect_class": "C03",
                        "snippet_masked": _snippet(lines, node.args[0].lineno),
                        "rule_basis": "CWE-78",
                    }
                )
        elif name in {"subprocess.call", "subprocess.run", "subprocess.Popen", "call", "run", "Popen"}:
            if not shell_true:
                continue
            if node.args and _is_dynamic(node.args[0]):
                hits.append(
                    {
                        "line": node.args[0].lineno,
                        "rule_id": CMD_RULE,
                        "defect_class": "C03",
                        "snippet_masked": _snippet(lines, node.args[0].lineno),
                        "rule_basis": "CWE-78:shell=True",
                    }
                )
    return hits


def _cred_hits(tree, lines):
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        value = node.value
        if not SENSITIVE_NAME.search(name):
            continue
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            continue
        if len(value.value) < 6:
            continue
        hits.append(
            {
                "line": node.lineno,
                "rule_id": CRED_RULE,
                "defect_class": "C05",
                "snippet_masked": name + ' = "***"',
                "rule_basis": "CWE-798",
            }
        )
    return hits


def _regex_sql(lines):
    hits = []
    pattern = re.compile(r"execute\s*\(\s*(f\"|f'|\"[^\"]*\"\s*%|'[^']*'\s*%|\"[^\"]*\"\s*\+|'[^']*'\s*\+)")
    for index, text in enumerate(lines, start=1):
        if pattern.search(text):
            hits.append(
                {
                    "line": index,
                    "rule_id": SQL_RULE,
                    "defect_class": "C02",
                    "snippet_masked": text.strip()[:MAX_SNIPPET],
                    "rule_basis": "CWE-89:regex-fallback",
                }
            )
    return hits


def _regex_cmd(lines):
    hits = []
    pattern = re.compile(r"(os\.popen\s*\([^)]*\+|subprocess\.(call|run|Popen)\s*\([^)]*\+.*shell\s*=\s*True)")
    for index, text in enumerate(lines, start=1):
        if pattern.search(text):
            hits.append(
                {
                    "line": index,
                    "rule_id": CMD_RULE,
                    "defect_class": "C03",
                    "snippet_masked": text.strip()[:MAX_SNIPPET],
                    "rule_basis": "CWE-78:regex-fallback",
                }
            )
    return hits


def _scan_python(path, relative, lines, findings):
    source = "\n".join(lines)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        for hit in _regex_sql(lines) + _regex_cmd(lines):
            hit["file"] = relative
            findings.append(hit)
        return
    for hit in _sql_hits(tree, lines) + _cmd_hits(tree, lines) + _cred_hits(tree, lines):
        hit["file"] = relative
        findings.append(hit)


def _scan_requirements(path, relative, lines, advisories, findings):
    for index, text in enumerate(lines, start=1):
        match = PIN_PATTERN.match(text)
        if not match:
            continue
        name, version = match.group(1), match.group(2)
        for advisory in advisories:
            component = advisory["component"] if isinstance(advisory, dict) else advisory.component
            affected = advisory["affected"] if isinstance(advisory, dict) else advisory.affected
            cve = advisory["cve"] if isinstance(advisory, dict) else advisory.cve
            source_ref = advisory["source_ref"] if isinstance(advisory, dict) else advisory.source_ref
            if str(name).lower() != str(component).lower():
                continue
            if _version_tuple(version) != _version_tuple(affected):
                continue
            findings.append(
                {
                    "file": relative,
                    "line": index,
                    "rule_id": DEP_RULE,
                    "defect_class": "C01",
                    "snippet_masked": name + "==" + version,
                    "rule_basis": str(cve) + " " + str(source_ref),
                }
            )


def _version_tuple(value):
    parts = []
    for chunk in re.split(r"[.\-+]", str(value)):
        parts.append(int(chunk) if chunk.isdigit() else 0)
    return tuple(parts)


def scan_tree(root, advisories, exec_location="CONTAINER"):
    root_path = str(root)
    findings = []
    try:
        index = __import__("os").walk(root_path)
        for current, _dirs, files in index:
            for name in sorted(files):
                path = __import__("os").path.join(current, name)
                relative = __import__("os").path.relpath(path, root_path).replace("\\", "/")
                if name.endswith(".py"):
                    with open(path, "r", encoding="utf-8", errors="replace") as handle:
                        lines = handle.read().splitlines()
                    _scan_python(path, relative, lines, findings)
                elif name == "requirements.txt":
                    with open(path, "r", encoding="utf-8", errors="replace") as handle:
                        lines = handle.read().splitlines()
                    _scan_requirements(path, relative, lines, advisories, findings)
    except OSError:
        return []
    for finding in findings:
        finding["source_kind"] = "REAL_CONTAINER"
        finding["exec_location"] = exec_location
    findings.sort(key=lambda item: (item["file"], item["line"], item["rule_id"]))
    return findings


def scan_tree_safe(root, advisories, exec_location="CONTAINER"):
    try:
        return scan_tree(root, advisories, exec_location)
    except Exception:
        traceback.print_exc()
        return []