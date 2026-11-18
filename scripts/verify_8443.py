from __future__ import annotations

import json
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://127.0.0.1:8443"


def fetch(path: str, context: ssl.SSLContext) -> tuple[int, str]:
    with urllib.request.urlopen(BASE + path, context=context, timeout=5) as response:
        return response.status, response.read().decode("utf-8", "replace")


def main() -> int:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    process = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "run_local_8443.py")],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        reachable = False
        for _ in range(40):
            time.sleep(0.5)
            try:
                status, _ = fetch("/healthz", context)
                reachable = status == 200
                break
            except Exception:
                continue

        if not reachable:
            print("FAIL: https://127.0.0.1:8443 not reachable")
            return 1

        results = []
        for path in ("/healthz", "/readyz", "/"):
            status, body = fetch(path, context)
            results.append((path, status, body))
            print(f"{path} -> HTTP {status} ({len(body)} bytes)")

        readiness = json.loads(results[1][2])
        dependencies = readiness["data"]["dependencies"]
        html = results[2][2].lower()
        console_ok = "id=\"app\"" in html or "<!doctype html" in html
        print(f"readyz status={readiness['data']['status']} dependencies={len(dependencies)}")
        print(f"console html={console_ok}")
        ok = all(status == 200 for _, status, _ in results) and len(dependencies) == 5 and console_ok
        print("PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    raise SystemExit(main())