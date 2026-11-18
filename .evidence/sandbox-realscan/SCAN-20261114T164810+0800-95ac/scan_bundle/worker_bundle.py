# VF_WORKER_PAYLOAD {"listen_port": 0, "port_retries": 3, "request_timeout": 5.0, "request_retries": 3, "db_path": "/tmp/target.db", "port_source": "DYNAMIC", "advisories": [], "scope_classes": ["C01", "C02", "C03", "C05"]}
import os
os.environ.setdefault("VF_WORKER_PAYLOAD", '{"listen_port": 0, "port_retries": 3, "request_timeout": 5.0, "request_retries": 3, "db_path": "/tmp/target.db", "port_source": "DYNAMIC", "advisories": [], "scope_classes": ["C01", "C02", "C03", "C05"]}')
import ast
import builtins
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, "/src")

TRUTH_MARKERS = ("ground" + "_truth", "exp" + "ected")
TRUTH_READS = {"count": 0}
_real_open = builtins.open


def _guarded_open(file, *args, **kwargs):
    try:
        candidate = str(file)
    except Exception:
        candidate = ""
    lowered = candidate.lower()
    for marker in TRUTH_MARKERS:
        if marker in lowered:
            TRUTH_READS["count"] += 1
            break
    return _real_open(file, *args, **kwargs)


builtins.open = _guarded_open

# ---- inlined from rules.py ----
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    rule_id: str
    defect_class: str
    anchor: str
    severity: str
    cve_ref: str
    source_ref: str
    mask_output: bool = False


@dataclass(frozen=True)
class Advisory:
    component: str
    affected: str
    fixed: str
    cve: str
    source_ref: str


RULES = (
    Rule(
        rule_id="C02-SQL",
        defect_class="C02",
        anchor="ast.Call(func=execute)",
        severity="high",
        cve_ref="",
        source_ref="CWE-89",
    ),
    Rule(
        rule_id="C03-CMD",
        defect_class="C03",
        anchor="os.popen|subprocess(shell=True)",
        severity="high",
        cve_ref="",
        source_ref="CWE-78",
    ),
    Rule(
        rule_id="C01-DEP",
        defect_class="C01",
        anchor="requirements.pin",
        severity="medium",
        cve_ref="see ADVISORIES",
        source_ref="public advisory table",
    ),
    Rule(
        rule_id="C05-CRED",
        defect_class="C05",
        anchor="ast.Assign(upper_sensitive_name, constant)",
        severity="high",
        cve_ref="",
        source_ref="CWE-798",
        mask_output=True,
    ),
)

ADVISORIES = (
    Advisory("requests", "2.19.1", "2.20.0", "CVE-2018-18074", "NVD:CVE-2018-18074"),
    Advisory("PyYAML", "5.1", "5.3.1", "CVE-2020-1747", "NVD:CVE-2020-1747"),
    Advisory("Jinja2", "2.10.1", "2.11.3", "CVE-2020-28493", "NVD:CVE-2020-28493"),
)

SENSITIVE_NAME = re.compile(r"(SECRET|PASSWORD|PASSWD|TOKEN|API_KEY|PRIVATE_KEY)", re.IGNORECASE)
CVE_PATTERN = re.compile(r"^CVE-\d{4}-\d{4,}$")
PIN_PATTERN = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*==\s*([0-9][0-9A-Za-z_.\-]*)\s*$")


def version_tuple(value):
    parts = []
    for chunk in re.split(r"[.\-+]", str(value)):
        if chunk.isdigit():
            parts.append(int(chunk))
        else:
            parts.append(0)
    return tuple(parts)


def verify_advisories(advisories=None):
    errors = []
    for advisory in advisories or ADVISORIES:
        if not advisory.component:
            errors.append("advisory component must not be empty")
        if not CVE_PATTERN.match(advisory.cve):
            errors.append("advisory cve format invalid: " + str(advisory.cve))
        if not advisory.source_ref:
            errors.append("advisory source_ref must not be empty")
        if version_tuple(advisory.affected) >= version_tuple(advisory.fixed):
            errors.append("advisory version range must be increasing: " + advisory.component)
    return errors


def match_pin(name, version, advisories=None):
    hits = []
    for advisory in advisories or ADVISORIES:
        if advisory.component.lower() != str(name).lower():
            continue
        if version_tuple(version) == version_tuple(advisory.affected):
            hits.append(advisory)
        elif version_tuple(version) < version_tuple(advisory.affected):
            hits.append(advisory)
    return hits
# ---- inlined from scanner.py ----
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
# ---- inlined from dynamic.py ----
import ast
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request

SQL_RULE = "C02-SQL"
CMD_RULE = "C03-CMD"
NORMAL_CMDS = {
    "/ping": "127.0.0.1",
    "/convert": "sample.png",
    "/backup": "data",
    "/deploy": "staging",
}
INJECT_SUFFIX = "; echo VF_INJECTED"


def _call_name(node):
    parts = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def _request_param(body):
    for node in ast.walk(body):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func)
        if name in {"request.args.get", "request.form.get", "request.values.get", "request.json.get"}:
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                kind = "form" if "form" in name else "args"
                return node.args[0].value, kind
    return "", "args"


def _sink(body):
    for node in ast.walk(body):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func)
        if name.endswith("execute"):
            return "C02", node.lineno if not node.args else node.args[0].lineno
        shell_true = any(
            keyword.arg == "shell"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in node.keywords
        )
        if name in {"os.popen", "os.system"} or (name.startswith("subprocess.") and shell_true):
            return "C03", node.lineno if not node.args else node.args[0].lineno
    return "", 0


def discover_routes(root):
    routes = []
    path = root + "/app/main.py"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            source = handle.read()
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return routes
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            name = _call_name(decorator.func)
            if name not in {"app.get", "app.post", "app.route"}:
                continue
            if not decorator.args or not isinstance(decorator.args[0], ast.Constant):
                continue
            endpoint = decorator.args[0].value
            method = decorator.func.attr.upper()
            if method == "ROUTE":
                method = "GET"
            kind, line = _sink(node)
            if kind not in {"C02", "C03"}:
                continue
            param, param_kind = _request_param(node)
            routes.append(
                {
                    "endpoint": endpoint,
                    "method": method,
                    "param": param,
                    "param_kind": param_kind,
                    "kind": kind,
                    "line": line,
                    "file": "app/main.py",
                }
            )
    routes.sort(key=lambda item: (item["endpoint"], item["method"]))
    return routes


def _values(route):
    kind = route["kind"]
    endpoint = route["endpoint"]
    param = route["param"]
    if kind == "C02":
        if endpoint == "/login":
            return {"username": "alice", "password": "alice-pass"}, {
                "username": "alice' OR '1'='1' --",
                "password": "x",
            }
        return {param: "1"}, {param: "1' OR '1'='1"}
    normal = NORMAL_CMDS.get(endpoint, "sample")
    return {param: normal}, {param: normal + INJECT_SUFFIX}


def _digest(text):
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _numeric_max(data):
    best = 0
    if isinstance(data, bool):
        return 0
    if isinstance(data, (int, float)):
        return data
    if isinstance(data, list):
        for item in data:
            best = max(best, _numeric_max(item))
    elif isinstance(data, dict):
        for item in data.values():
            best = max(best, _numeric_max(item))
    return best


def _row_count(data):
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        if "matched" in data and isinstance(data["matched"], int):
            return int(data["matched"])
        return sum(_row_count(item) for item in data.values())
    return 0


def _shape(text):
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return 0, 0
    return _row_count(data), _numeric_max(data)


def _request(opener, base_url, endpoint, method, values, timeout):
    encoded = urllib.parse.urlencode(values)
    if method == "POST":
        request = urllib.request.Request(base_url + endpoint, data=encoded.encode("utf-8"), method="POST")
    else:
        request = urllib.request.Request(base_url + endpoint + "?" + encoded, method="GET")
    with opener.open(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace"), int(getattr(response, "status", 200))


def _fetch(opener, base_url, route, values, timeout, retries):
    attempts = 0
    last_error = ""
    while attempts < max(1, retries):
        attempts += 1
        try:
            return _request(opener, base_url, route["endpoint"], route["method"], values, timeout), attempts, ""
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            last_error = type(exc).__name__
            time.sleep(0.05)
    return ("", 0), attempts, last_error


def _judge(route, normal_text, injected_text):
    if route["kind"] == "C02":
        normal_rows, normal_num = _shape(normal_text)
        injected_rows, injected_num = _shape(injected_text)
        return injected_rows > normal_rows or injected_num > normal_num
    if route["endpoint"] == "/convert":
        try:
            normal_code = int(json.loads(normal_text).get("exit_code", 0))
            injected_code = int(json.loads(injected_text).get("exit_code", -1))
        except (ValueError, TypeError, AttributeError):
            return False
        return normal_code != 0 and injected_code == 0
    return "VF_INJECTED" in injected_text and "VF_INJECTED" not in normal_text


def run_plan(base_url, plan, timeout=5.0, retries=3, opener=None):
    opener = opener or urllib.request.build_opener()
    results = []
    for route in plan:
        started = time.time()
        normal_values, injected_values = _values(route)
        (normal_text, normal_status), normal_attempts, normal_error = _fetch(
            opener, base_url, route, normal_values, timeout, retries
        )
        (injected_text, injected_status), injected_attempts, injected_error = _fetch(
            opener, base_url, route, injected_values, timeout, retries
        )
        diff = _judge(route, normal_text, injected_text)
        reproducible = bool(normal_status and injected_status and diff)
        if normal_error or injected_error:
            conclusion = "NOT_REPRODUCIBLE"
        else:
            conclusion = "REPRODUCIBLE" if reproducible else "NOT_REPRODUCIBLE"
        results.append(
            {
                "endpoint": route["endpoint"],
                "method": route["method"],
                "kind": route["kind"],
                "file": route["file"],
                "line": route["line"],
                "normal_digest": _digest(normal_text),
                "injected_digest": _digest(injected_text),
                "behavior_diff": reproducible,
                "conclusion": conclusion,
                "duration_ms": int((time.time() - started) * 1000),
                "retries": normal_attempts + injected_attempts - 2,
            }
        )
    return results

PAYLOAD = json.loads(os.environ.get("VF_WORKER_PAYLOAD", "{}"))


def _emit(event, **fields):
    record = {"event": event}
    record.update(fields)
    print(json.dumps(record, sort_keys=True, default=str), flush=True)


def _start_target():
    from pathlib import Path as _Path
    from init_db import create as _create

    db_path = PAYLOAD.get("db_path", "/tmp/target.db")
    try:
        _create(_Path(db_path))
    except Exception as exc:
        _emit("target_ready", ok=False, reason="DB_NOT_WRITABLE", detail=type(exc).__name__)
        return None, None
    os.environ["VERIFIX_TARGET_DB"] = db_path
    try:
        from app.main import create_app
        from werkzeug.serving import make_server
    except Exception as exc:
        _emit("target_ready", ok=False, reason="MISSING_DEPENDENCY", detail=type(exc).__name__)
        return None, None
    app = create_app(db_path)
    server = None
    last_error = ""
    for _attempt in range(int(PAYLOAD.get("port_retries", 3))):
        try:
            server = make_server("127.0.0.1", int(PAYLOAD.get("listen_port", 0)), app, threaded=True)
            break
        except OSError as exc:
            last_error = type(exc).__name__
            time.sleep(0.2)
    if server is None:
        _emit("target_ready", ok=False, reason="PORT_UNAVAILABLE", detail=last_error)
        return None, None
    port = int(server.server_port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    started = time.time()
    ready = False
    for _try in range(150):
        try:
            with urllib.request.urlopen("http://127.0.0.1:" + str(port) + "/health", timeout=1) as response:
                ready = int(getattr(response, "status", 0)) == 200
                break
        except Exception:
            time.sleep(0.1)
    _emit(
        "target_ready",
        ok=ready,
        port=port,
        port_source=PAYLOAD.get("port_source", "DYNAMIC"),
        db_path=db_path,
        health_elapsed_ms=int((time.time() - started) * 1000),
        reason="" if ready else "HEALTH_TIMEOUT",
    )
    return server, port


def main():
    server, port = _start_target()
    if server is None:
        return 1
    findings = scan_tree_safe("/src", PAYLOAD.get("advisories", []), "CONTAINER")
    for finding in findings:
        _emit("detection", **finding)
    plan = discover_routes("/src")
    checks = run_plan(
        "http://127.0.0.1:" + str(port),
        plan,
        timeout=float(PAYLOAD.get("request_timeout", 5)),
        retries=int(PAYLOAD.get("request_retries", 3)),
    )
    for check in checks:
        _emit("dynamic", **check)
    _emit(
        "summary",
        detections=len(findings),
        dynamic=len(checks),
        plan=len(plan),
        truth_reads=int(TRUTH_READS["count"]),
        port=port,
    )
    try:
        server.shutdown()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
