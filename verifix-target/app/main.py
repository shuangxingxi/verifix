from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path

from flask import Flask, jsonify, request

from app.config import SECRET_KEY

DEFAULT_DB = Path(__file__).resolve().parents[1] / "target.db"


def create_app(db_path: str | None = None) -> Flask:
    app = Flask(__name__)
    app.secret_key = SECRET_KEY
    database = Path(db_path or os.environ.get("VERIFIX_TARGET_DB", DEFAULT_DB))

    def connect() -> sqlite3.Connection:
        return sqlite3.connect(database)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "target": "verifix-target"})

    @app.get("/user")
    def user():
        uid = request.args.get("uid", "")
        conn = connect()
        rows = conn.execute("SELECT id, name FROM users WHERE id = '%s'" % uid).fetchall()
        conn.close()
        return jsonify(rows)

    @app.post("/login")
    def login():
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        conn = connect()
        rows = conn.execute(
            "SELECT id FROM users WHERE name = '" + username + "' AND password = '" + password + "'"
        ).fetchall()
        conn.close()
        return jsonify({"matched": len(rows)})

    @app.get("/search")
    def search():
        keyword = request.args.get("q", "")
        conn = connect()
        rows = conn.execute("SELECT id, name FROM users WHERE name LIKE '%" + keyword + "%'").fetchall()
        conn.close()
        return jsonify(rows)

    @app.get("/order")
    def order():
        order_id = request.args.get("order_id", "")
        conn = connect()
        rows = conn.execute("SELECT id, amount FROM orders WHERE id = " + order_id).fetchall()
        conn.close()
        return jsonify(rows)

    @app.get("/report")
    def report():
        day = request.args.get("day", "")
        conn = connect()
        rows = conn.execute("SELECT COUNT(*) FROM orders WHERE created_at = '" + day + "'").fetchall()
        conn.close()
        return jsonify(rows)

    @app.get("/profile")
    def profile():
        user_id = request.args.get("id", "")
        conn = connect()
        rows = conn.execute(f"SELECT user_id, email FROM profiles WHERE user_id = {user_id}").fetchall()
        conn.close()
        return jsonify(rows)

    @app.get("/ping")
    def ping():
        host = request.args.get("host", "127.0.0.1")
        output = os.popen("ping -c 1 " + host).read()
        return jsonify({"output": output})

    @app.get("/convert")
    def convert():
        name = request.args.get("name", "sample.png")
        result = subprocess.call("convert " + name + " out.jpg", shell=True)
        return jsonify({"exit_code": result})

    @app.get("/backup")
    def backup():
        folder = request.args.get("folder", "data")
        output = os.popen("tar czf backup.tgz " + folder).read()
        return jsonify({"output": output})

    @app.post("/deploy")
    def deploy():
        env = request.form.get("env", "staging")
        completed = subprocess.run("deploy.sh " + env, shell=True, capture_output=True, text=True)
        return jsonify({"stdout": completed.stdout, "stderr": completed.stderr})

    return app


app = create_app()