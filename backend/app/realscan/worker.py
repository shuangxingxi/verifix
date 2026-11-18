from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

RULES_PATH = Path(__file__).with_name("rules.py")
SCANNER_PATH = Path(__file__).with_name("scanner.py")
DYNAMIC_PATH = Path(__file__).with_name("dynamic.py")

BUNDLE_PRELUDE = """import ast
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
"""

BUNDLE_MAIN = '''

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
'''


class WorkerBundleError(RuntimeError):
    pass


def _strip(relative: Path) -> str:
    text = relative.read_text(encoding="utf-8")
    if "from __future__" in text:
        raise WorkerBundleError(f"{relative.name} must stay free of __future__ imports for bundle inlining")
    return text


def build_worker_bundle(payload: dict[str, object]) -> str:
    parts: list[str] = [BUNDLE_PRELUDE]
    for relative in (RULES_PATH, SCANNER_PATH, DYNAMIC_PATH):
        parts.append("\n# ---- inlined from " + relative.name + " ----\n")
        parts.append(_strip(relative))
    bundle = "".join(parts) + BUNDLE_MAIN
    encoded = json.dumps(payload, ensure_ascii=False)
    header = "# VF_WORKER_PAYLOAD " + json.dumps(payload, ensure_ascii=True) + "\n"
    return header + "import os\nos.environ.setdefault(\"VF_WORKER_PAYLOAD\", " + repr(encoded) + ")\n" + bundle


def parse_events(stdout: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for line in stdout.splitlines():
        text = line.strip()
        if not text.startswith("{"):
            continue
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "event" in value:
            events.append(value)
    return events


def worker_payload(
    *,
    listen_port: int = 0,
    port_retries: int = 3,
    request_timeout: float = 5.0,
    request_retries: int = 3,
    advisories: Sequence[dict[str, object]] = (),
    scope_classes: Sequence[str] = ("C01", "C02", "C03", "C05"),
) -> dict[str, object]:
    return {
        "listen_port": int(listen_port),
        "port_retries": int(port_retries),
        "request_timeout": float(request_timeout),
        "request_retries": int(request_retries),
        "db_path": "/tmp/target.db",
        "port_source": "DYNAMIC",
        "advisories": list(advisories),
        "scope_classes": list(scope_classes),
    }