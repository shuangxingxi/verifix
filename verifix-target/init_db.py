from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent / "target.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT, password TEXT);
CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, amount REAL, created_at TEXT);
CREATE TABLE IF NOT EXISTS profiles (user_id INTEGER PRIMARY KEY, email TEXT);
"""

SEED = [
    ("INSERT INTO users (id, name, password) VALUES (1, 'alice', 'alice-pass')", None),
    ("INSERT INTO users (id, name, password) VALUES (2, 'bob', 'bob-pass')", None),
    ("INSERT INTO orders (id, amount, created_at) VALUES (1, 19.9, '2026-11-01')", None),
    ("INSERT INTO orders (id, amount, created_at) VALUES (2, 88.0, '2026-11-02')", None),
    ("INSERT INTO profiles (user_id, email) VALUES (1, 'alice@example.com')", None),
    ("INSERT INTO profiles (user_id, email) VALUES (2, 'bob@example.com')", None),
]


def create(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    for statement, _ in SEED:
        conn.execute(statement)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB
    create(target)
    print(f"seeded {target}")