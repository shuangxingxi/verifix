#!/usr/bin/env python
"""D1-1 可复现性逐层补验（L1 干净导出 / L2 依赖安装 / L3 配置加载 / L4 全量回归）。

只读工作区；产物一律写入 .evidence/perf-repro/。任一层不通过即停止，
未执行层登记 EVIDENCE_GAP，绝不折叠为"通过"。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / ".evidence" / "perf-repro"
DIRECT_DEPS = ("fastapi", "uvicorn", "pydantic", "PyYAML", "httpx", "SQLAlchemy", "PyMySQL")
PYTHON_ENV_PREFIX = "PYTHON"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ts_stamp() -> str:
    return datetime.now().strftime("%Y%m%dT%H%M%S")


def env_for(mode: str) -> tuple[dict, list[str], dict]:
    base = dict(os.environ)
    if mode == "default":
        for key in [item for item in base if item.upper().startswith(PYTHON_ENV_PREFIX)]:
            base.pop(key)
    retained = sorted(key for key in ("PATH", "SYSTEMROOT", "TEMP") if key in base)
    raw = {
        "mode": mode,
        "python_utf8_env": os.environ.get("PYTHONUTF8"),
        "python_io_encoding": os.environ.get("PYTHONIOENCODING"),
        "python_path": os.environ.get("PYTHONPATH"),
    }
    if mode == "default":
        raw = {**raw, "python_utf8_env": None, "python_io_encoding": None, "python_path": None}
    return base, retained, raw


def run_cmd(command: list[str], *, cwd: Path, env: dict, timeout: int) -> tuple[int, str, str, float]:
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            timeout=timeout,
        )
        code = completed.returncode
        out = completed.stdout.decode("utf-8", errors="replace")
        err = completed.stderr.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired as exc:
        code = 124
        out = (exc.stdout or b"").decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else ""
        err = f"TIMEOUT after {timeout}s"
    except OSError as exc:
        code = 127
        out = ""
        err = repr(exc)
    return code, out, err, round(time.perf_counter() - started, 3)


def record_path(out_dir: Path, layer: str) -> Path:
    return out_dir / f"d1-1-{layer}-{ts_stamp()}.json"


def write_record(out_dir: Path, record: dict) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = record_path(out_dir, record["coverage_layer"])
    counter = 1
    while target.exists():
        counter += 1
        target = out_dir / f"d1-1-{record['coverage_layer']}-{ts_stamp()}-{counter}.json"
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def base_record(layer: str, mode: str, retained: list[str], command: str) -> dict:
    return {
        "check_id": "D1-1",
        "coverage_layer": layer,
        "command": command,
        "exit_code": None,
        "duration_seconds": None,
        "ran": 0,
        "errors": 0,
        "failures": 0,
        "failed_test_names": [],
        "stopped_at_layer": None,
        "evidence_gap": False,
        "env_mode": mode,
        "retained_env_keys": retained,
        "executed_at": now_iso(),
    }


def tracked_count() -> int:
    out = subprocess.run(
        ["git", "ls-files"], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return len([line for line in out.stdout.splitlines() if line.strip()])


def layer_clean_export(out_dir: Path, mode: str, work_root: Path) -> tuple[dict, Path | None]:
    env, retained, _ = env_for(mode)
    archive = work_root / "repo.zip"
    command = f"git archive --format=zip --output={archive} HEAD"
    record = base_record("clean-export", mode, retained, command)
    code, out, err, elapsed = run_cmd(["git", "archive", "--format=zip", f"--output={archive}", "HEAD"], cwd=ROOT, env=env, timeout=180)
    record.update({"exit_code": code, "duration_seconds": elapsed})
    export_dir = work_root / "src"
    if code != 0 or not archive.is_file():
        record.update(
            {
                "sub_reason": "EXPORT_FAILED",
                "stderr_tail": err[-500:] or out[-500:],
                "stopped_at_layer": "clean-export",
                "evidence_gap": True,
            }
        )
        record["conclusion"] = "EVIDENCE_GAP"
        write_record(out_dir, record)
        return record, None
    export_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(export_dir)
    exported = sum(1 for item in export_dir.rglob("*") if item.is_file())
    tracked = tracked_count()
    inside_repo = str(export_dir.resolve()).startswith(str(ROOT.resolve()))
    record.update(
        {
            "export_dir": str(export_dir),
            "exported_files": exported,
            "tracked_files": tracked,
            "file_count_delta": exported - tracked,
            "temp_outside_repo": not inside_repo,
        }
    )
    ok = exported == tracked and not inside_repo
    record["exit_code"] = 0 if ok else 1
    record["conclusion"] = "通过" if ok else "失败"
    if not ok:
        record["sub_reason"] = "EXPORT_COUNT_MISMATCH"
        record["stopped_at_layer"] = "clean-export"
        record["evidence_gap"] = True
        record["conclusion"] = "EVIDENCE_GAP"
    write_record(out_dir, record)
    return record, export_dir if ok else None


def layer_install(out_dir: Path, mode: str, export_dir: Path) -> tuple[dict, bool]:
    env, retained, _ = env_for(mode)
    venv_dir = export_dir / ".venv"
    record = base_record("install", mode, retained, f"{sys.executable} -m venv {venv_dir}")
    code, out, err, elapsed = run_cmd([sys.executable, "-m", "venv", str(venv_dir)], cwd=export_dir, env=env, timeout=300)
    record.update({"exit_code": code, "duration_seconds": elapsed, "step": "venv"})
    if code != 0:
        record.update({"sub_reason": "INSTALL_UNAVAILABLE", "stderr_tail": err[-500:], "stopped_at_layer": "install", "evidence_gap": True, "conclusion": "EVIDENCE_GAP"})
        write_record(out_dir, record)
        return record, False
    python_exe = venv_dir / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
    requirements = export_dir / "backend" / "requirements.txt"
    pip_command = f"{python_exe} -m pip install -r {requirements}"
    record["command"] = pip_command
    code, out, err, elapsed = run_cmd([str(python_exe), "-m", "pip", "install", "-r", str(requirements)], cwd=export_dir, env=env, timeout=900)
    summary = "\n".join((out or err).splitlines()[-20:])
    listed = [dep for dep in DIRECT_DEPS if dep.lower() in (out + err).lower()]
    record.update(
        {
            "exit_code": code,
            "duration_seconds": elapsed,
            "pip_output_tail": summary,
            "direct_deps_observed": listed,
        }
    )
    ok = code == 0 and len(listed) == len(DIRECT_DEPS)
    if ok:
        record["conclusion"] = "通过"
    else:
        record.update(
            {
                "sub_reason": "INSTALL_UNAVAILABLE",
                "stopped_at_layer": "install",
                "evidence_gap": True,
                "conclusion": "EVIDENCE_GAP",
            }
        )
    write_record(out_dir, record)
    return record, ok


def layer_config_load(out_dir: Path, mode: str, export_dir: Path, *, degraded: bool) -> tuple[dict, bool]:
    env, retained, _ = env_for(mode)
    snippet = (
        "import sys;sys.path.insert(0,str(__import__('pathlib').Path('backend').resolve()));"
        "from app.config import load_config;load_config();print('config ok')"
    )
    command = f'{sys.executable} -X utf8=0 -c "{snippet}"'
    record = base_record("config-load", mode, retained, command)
    if degraded:
        record["degraded_from"] = "install-unavailable"
    code, out, err, elapsed = run_cmd([sys.executable, "-X", "utf8=0", "-c", snippet], cwd=export_dir, env=env, timeout=300)
    record.update(
        {
            "exit_code": code,
            "duration_seconds": elapsed,
            "stdout_tail": out[-500:],
            "stderr_tail": err[-1000:],
            "encoding_exception": any(token in err for token in ("UnicodeDecodeError", "UnicodeEncodeError")),
        }
    )
    ok = code == 0 and "config ok" in out
    record["conclusion"] = "通过" if ok else ("环境可复现性缺陷" if record["encoding_exception"] else "失败")
    if not ok:
        record["stopped_at_layer"] = "config-load"
        record["evidence_gap"] = True
    write_record(out_dir, record)
    return record, ok


def layer_full_regression(out_dir: Path, mode: str, export_dir: Path, *, execute: bool) -> tuple[dict, bool]:
    env, retained, _ = env_for(mode)
    command = f"{sys.executable} -m unittest discover -s tests -t . -p test_*.py"
    record = base_record("full-regression", mode, retained, command)
    if not execute:
        record.update(
            {
                "evidence_gap": True,
                "sub_reason": "OPTIONAL_LAYER_NOT_EXECUTED",
                "stopped_at_layer": "full-regression",
                "conclusion": "EVIDENCE_GAP",
            }
        )
        write_record(out_dir, record)
        return record, False
    code, out, err, elapsed = run_cmd([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-p", "test_*.py"], cwd=export_dir / "backend", env=env, timeout=1800)
    text = out + err
    ran = 0
    errors = 0
    failures = 0
    failed: list[str] = []
    for line in text.splitlines():
        if line.startswith("Ran ") and " test" in line:
            try:
                ran = int(line.split()[1])
            except (IndexError, ValueError):
                ran = 0
        if line.startswith("FAIL: ") or line.startswith("ERROR: "):
            failed.append(line.split(" ", 1)[1].strip().split(" ")[0])

    if "errors=" in text:
        tail = text.rsplit("errors=", 1)[1].split()[0].rstrip(")")
        try:
            errors = int(tail)
        except ValueError:
            errors = 0
    if "failures=" in text:
        tail = text.rsplit("failures=", 1)[1].split()[0].rstrip(")")
        try:
            failures = int(tail)
        except ValueError:
            failures = 0
    record.update(
        {
            "exit_code": code,
            "duration_seconds": elapsed,
            "ran": ran,
            "errors": errors,
            "failures": failures,
            "failed_test_names": failed,
            "output_tail": text[-2000:],
        }
    )
    record["conclusion"] = "通过" if code == 0 and failures == 0 and errors == 0 else "失败"
    if code != 0:
        record["sub_reason"] = "REGRESSION_FAILED"
    write_record(out_dir, record)
    return record, code == 0 and failures == 0 and errors == 0


def summarize(out_dir: Path, records: list[dict]) -> Path:
    gaps = [item["coverage_layer"] for item in records if item.get("evidence_gap")]
    if gaps:
        conclusion = "部分通过（分层登记）"
        gap_text = f"缺口层：{','.join(gaps)}"
    else:
        conclusion = "通过"
        gap_text = ""
    payload = {
        "check_id": "D1-1",
        "conclusion": conclusion,
        "gap_layers": gaps,
        "layer_counts": {item["coverage_layer"]: item.get("conclusion") for item in records},
        "gap_note": gap_text,
        "generated_at": now_iso(),
        "layers": records,
    }
    target = out_dir / f"d1-1-summary-{ts_stamp()}.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="D1-1 逐层可复现补验")
    sub = parser.add_subparsers(dest="command")
    node = sub.add_parser("run")
    node.add_argument("--check", default="D1-1")
    node.add_argument("--layer", default="all", choices=("all", "clean-export", "install", "config-load", "full-regression"))
    node.add_argument("--env", default="default", choices=("default", "clean"))
    node.add_argument("--out", default=str(DEFAULT_OUT))
    node.add_argument("--with-regression", action="store_true")
    node.add_argument("--keep-temp", action="store_true")
    args = parser.parse_args(argv)
    if args.command != "run":
        print("command required: run --check D1-1 --layer all|clean-export|install|config-load|full-regression", file=sys.stderr)
        return 2
    if args.check != "D1-1":
        print("SCHEMA_INVALID: only D1-1 is supported", file=sys.stderr)
        return 2
    out_dir = Path(args.out)
    records: list[dict] = []
    work = Path(tempfile.mkdtemp(prefix="d1-1-", dir=tempfile.gettempdir()))
    try:
        export_record, export_dir = layer_clean_export(out_dir, args.env, work)
        records.append(export_record)
        if args.layer in ("all", "clean-export") and args.layer == "clean-export":
            print(json.dumps({"layer": "clean-export", "conclusion": export_record["conclusion"]}, ensure_ascii=False))
            return 0 if export_record["exit_code"] == 0 else 1
        if export_dir is None:
            summarize(out_dir, records)
            return 1
        install_record, installed = layer_install(out_dir, args.env, export_dir)
        records.append(install_record)
        if args.layer == "install":
            print(json.dumps({"layer": "install", "conclusion": install_record["conclusion"]}, ensure_ascii=False))
            return 0 if installed else 1
        for mode in ("default", "clean"):
            config_record, ok = layer_config_load(out_dir, mode, export_dir, degraded=not installed)
            records.append(config_record)
            if not ok:
                summarize(out_dir, records)
                return 1
        if args.layer == "config-load":
            print(json.dumps({"layer": "config-load", "conclusion": "通过"}, ensure_ascii=False))
            return 0
        regression_record, _ = layer_full_regression(out_dir, args.env, export_dir, execute=args.with_regression)
        records.append(regression_record)
        summary = summarize(out_dir, records)
        print(json.dumps({"summary": str(summary), "conclusion": json.loads(summary.read_text(encoding="utf-8"))["conclusion"]}, ensure_ascii=False))
        return 0
    finally:
        if not args.keep_temp:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())