from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import uvicorn

CERT_DIR = ROOT / "deploy" / "certs"


def main() -> int:
    cert = CERT_DIR / "server.crt"
    key = CERT_DIR / "server.key"
    if not cert.is_file() or not key.is_file():
        print(f"missing certificate: {cert} / {key}")
        print("run: bash scripts/gen_self_signed_cert.sh")
        return 1
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8443,
        ssl_certfile=str(cert),
        ssl_keyfile=str(key),
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())