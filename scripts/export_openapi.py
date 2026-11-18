from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.main import create_app

TARGET = ROOT / "docs" / "openapi.json"


def main() -> int:
    schema = create_app().openapi()
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"openapi written: {TARGET} ({len(schema.get('paths', {}))} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())