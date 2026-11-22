#!/usr/bin/env python
"""PERF-02/metrics-capture 取证探针。

本脚本只测量、不修改被测实现，不 import backend/tests 下的任何模块。
证据统一写入 .evidence/perf-repro/，对不可变载体一律拒绝写入。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

DEFAULT_OUT = ROOT / ".evidence" / "perf-repro"
THRESHOLD_MS = 200
CASE_ID = "PERF-02/metrics-capture"
PYTHON_ENV_PREFIX = "PYTHON"
ENV_RETAINED_SAMPLE = ("PATH", "SYSTEMROOT", "TEMP")
SCOPE_KEYS = ("container_copy", "field_redaction", "serialization", "digest_compute", "disk_write")
STOPPED_ROOTS = ("docs/devlog/selfcheck", ".evidence/git-baseline", ".evidence/perf-repro/.immutable")

immutable = (
    "docs/devlog/m13-analysis-plan.md",
    "docs/devlog/m13-selfcheck-report.md",
    "docs/devlog/m12-closure-and-blockers.md",
    "docs/devlog/vcs-baseline.md",
    "docs/devlog/metrics-report.md",
    "README.md",
    "backend/tests/test_metrics_perf.py",
    "backend/tests/test_check_devlog.py",
    "backend/app/metrics/snapshot.py",
    "backend/app/config.py",
)


class ProbeError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def fail(code: str, message: str) -> None:
    raise ProbeError(code, message)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ts_stamp() -> str:
    return datetime.now().strftime("%Y%m%dT%H%M%S")


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def immutable_paths() -> list[str]:
    paths = list(immutable)
    selfcheck = ROOT / "docs" / "devlog" / "selfcheck"
    for archive in sorted(selfcheck.glob("SC-*")):
        for name in ("report.md", "selfcheck.json"):
            candidate = archive / name
            if candidate.is_file():
                paths.append(rel(candidate))
    index = selfcheck / "index.json"
    if index.is_file():
        paths.append(rel(index))
    for item in sorted((ROOT / ".evidence" / "git-baseline").glob("**/*")):
        if item.is_file():
            paths.append(rel(item))
    return sorted(set(paths))


def is_readonly_target(path: Path) -> bool:
    try:
        target = rel(path)
    except ValueError:
        return False
    if target in set(immutable_paths()):
        return True
    return any(target.startswith(root + "/") or target == root for root in STOPPED_ROOTS)


def append_record(path: Path, record: dict, *, kind: str) -> None:
    if is_readonly_target(path):
        fail("READONLY_VIOLATION", f"refuse to write immutable carrier: {path}")
    validate_record(record, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".jsonl":
        payload = json.dumps(record, ensure_ascii=False, sort_keys=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(payload + "\n")
        return
    if path.exists():
        fail("OUTPUT_EXISTS", f"record already exists: {path}")
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


REQUIRED = {
    "EnvironmentDeclaration": (
        "mode",
        "os_name",
        "os_release",
        "python_version",
        "python_utf8_env",
        "python_io_encoding",
        "python_path",
        "retained_env_keys",
        "concurrent_load",
        "declared_at",
    ),
    "PerfSampleRecord": ("sample_index", "case_id", "measurement_object", "elapsed_ms", "over_threshold", "collected_at"),
    "MeasurementRecord": (
        "case_id",
        "measurement_object",
        "measurement_scope",
        "data_scale",
        "samples",
        "median_ms",
        "max_ms",
        "over_budget_count",
        "threshold_ms",
        "evidence_level",
        "fingerprint_sha256",
        "environment",
        "ledger",
    ),
    "WriteBlockRecord": (
        "case_id",
        "baseline_p50_ms",
        "baseline_p95_ms",
        "baseline_max_ms",
        "interference_p50_ms",
        "interference_p95_ms",
        "interference_max_ms",
        "delta_p95_ms",
        "thread_model_note",
        "evidence_level",
        "measurement_scope",
        "environment",
    ),
    "ReproducibilityRecord": (
        "check_id",
        "coverage_layer",
        "command",
        "exit_code",
        "duration_seconds",
        "ran",
        "errors",
        "failures",
        "failed_test_names",
        "stopped_at_layer",
        "evidence_gap",
        "env_mode",
        "retained_env_keys",
    ),
    "CloseoutDecisionRecord": (
        "topic",
        "decision_class",
        "spec_refs",
        "original_text_refs",
        "evidence_paths",
        "immutable_carriers",
        "effective_date",
    ),
    "RelatedFindingRecord": (
        "finding_id",
        "title",
        "reproduce_command",
        "stability",
        "ownership",
        "blocking_relation",
        "suggestion",
    ),
    "SemanticsLedger": ("requirement_text_ref", "design_text_ref", "assertion_text_ref", "captured_at"),
}

# 新增记录类型独立于 REQUIRED：既有 8 项 schema 与 --selftest 计数保持不变。
EXTRA_REQUIRED = {
    "SegmentedSampleRecord": (
        "sample_index",
        "round_index",
        "case_id",
        "write_block_ms",
        "capture_ms",
        "capture_total_ms",
        "segment_ms",
        "encode_count",
        "over_capture_budget",
        "collected_at",
    ),
    "SegmentedMeasurementRecord": (
        "case_id",
        "round_index",
        "samples",
        "data_scale",
        "write_ops",
        "write_block_p50_ms",
        "write_block_p95_ms",
        "write_block_max_ms",
        "capture_total_p50_ms",
        "capture_total_p95_ms",
        "capture_total_max_ms",
        "over_capture_budget_count",
        "encode_count",
        "measurement_scope",
        "environment",
        "fingerprint_sha256",
        "evidence_level",
        "generated_at",
    ),
    "PerfRoundRecord": (
        "case_id",
        "round_index",
        "samples_path",
        "measure_path",
        "write_block_path",
        "regression_path",
        "samples_sha256",
        "measure_sha256",
        "write_block_sha256",
        "regression_sha256",
        "passed",
        "reasons",
        "generated_at",
    ),
}

ROUND_RULES = {
    "rounds_required": 3,
    "samples_required": 5,
    "write_block_budget_ms": THRESHOLD_MS,
    "delta_p95_budget_ms": THRESHOLD_MS,
    "regression_failures": 0,
    "encode_count": 1,
}


def validate_record(record: dict, kind: str) -> None:
    schema = REQUIRED.get(kind) or EXTRA_REQUIRED.get(kind)
    if schema is None:
        fail("SCHEMA_INVALID", f"unknown record kind: {kind}")
    missing = [name for name in schema if name not in record]
    if missing:
        fail("SCHEMA_INVALID", f"{kind} missing fields: {','.join(missing)}")
    if kind == "RelatedFindingRecord":
        if not str(record["finding_id"]).startswith("RF-"):
            fail("SCHEMA_INVALID", "RelatedFindingRecord.finding_id must start with RF-")
        if record["ownership"] not in ("本项范围", "范围外"):
            fail("SCHEMA_INVALID", "RelatedFindingRecord.ownership out of enum")
    if kind == "ReproducibilityRecord" and record["check_id"] != "D1-1":
        fail("SCHEMA_INVALID", "ReproducibilityRecord.check_id must be D1-1")


def _python_env_keys() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key.upper().startswith(PYTHON_ENV_PREFIX)}


def strip_python_env() -> list[str]:
    removed = sorted(_python_env_keys())
    for key in removed:
        os.environ.pop(key, None)
    return removed


def declare_env(mode: str | None, *, concurrent_load: bool = False) -> dict:
    if mode not in ("default", "clean"):
        fail("ENV_DECLARATION_INVALID", "environment mode is required: --env default|clean")
    stripped: list[str] = []
    if mode == "default":
        stripped = strip_python_env()
        leftover = _python_env_keys()
        if leftover:
            fail("ENV_DECLARATION_INVALID", f"PYTHON* still present after strip: {sorted(leftover)}")
    raw = _python_env_keys()
    if mode == "default":
        for key in ("PYTHONUTF8", "PYTHONIOENCODING", "PYTHONPATH"):
            if raw.get(key) is not None:
                fail("ENV_DECLARATION_INVALID", f"{key} still visible in default mode")
    declaration = {
        "mode": mode,
        "os_name": platform.system(),
        "os_release": platform.release(),
        "python_version": platform.python_version(),
        "python_utf8_env": raw.get("PYTHONUTF8"),
        "python_io_encoding": raw.get("PYTHONIOENCODING"),
        "python_path": raw.get("PYTHONPATH"),
        "retained_env_keys": sorted(key for key in ENV_RETAINED_SAMPLE if key in os.environ),
        "concurrent_load": concurrent_load,
        "declared_at": now_iso(),
        "stripped_env_keys": stripped,
    }
    if mode == "clean" and not declaration["retained_env_keys"]:
        fail("ENV_DECLARATION_INVALID", "clean mode requires non-empty retained_env_keys")
    validate_record(declaration, "EnvironmentDeclaration")
    return declaration


def build_scale(*, issues: int = 1000, repro_failed: int = 100, events_per_run: int = 12):
    from datetime import timedelta

    from app.domain.enums import (
        DefectClass,
        DispositionLevel,
        FixParadigm,
        GateOutcome,
        IssueStatus,
        MetricChannel,
        ProofResult,
        ReproductionAttemptStatus,
        Severity,
        SourceKind,
        VerdictConclusion,
    )
    from app.domain.models import (
        Alert,
        Disposition,
        DispositionHistoryEntry,
        EnvSnapshot,
        GateAttempt,
        Issue,
        Location,
        Patch,
        PatchAttempt,
        Proof,
        ReproductionAttempt,
        Run,
        Verdict,
    )
    from app.domain.enums import EventType
    from app.domain.models import Event
    from app.repo.memory import MemoryStore

    observed = datetime(2026, 12, 5, 10, 0, tzinfo=timezone.utc)
    store = MemoryStore()

    def make_issue(issue_id: str, channel=MetricChannel.MAIN) -> None:
        issue = Issue(
            issue_id=issue_id,
            repo="verifix-target",
            code_version="abc123",
            defect_class=DefectClass.SQL_INJECTION,
            severity=Severity.HIGH,
            status=IssueStatus.RECEIVED,
            fingerprint=hashlib.sha256(issue_id.encode("utf-8")).hexdigest(),
            occurred_at=observed,
            channel=channel,
        )
        store.add(issue)
        store.link_alert(
            issue_id,
            Alert(
                alert_ref=f"check:{issue_id}",
                source_kind=SourceKind.CHECK,
                rule_id="py/sql-injection",
                location=Location(file="app/main.py", line=31),
                raw_severity=Severity.HIGH,
                snippet_fingerprint="s" * 64,
                defect_class=DefectClass.SQL_INJECTION,
                observed_at=observed,
            ),
        )

    for index in range(issues):
        issue_id = f"ISF-{index + 1:03d}"
        make_issue(issue_id)
        store.update(store.get(issue_id).model_copy(update={"status": IssueStatus.DISPOSED_L1}))
        store.add_verdict(
            Verdict(
                verdict_id=f"V-{issue_id}",
                issue_id=issue_id,
                conclusion=VerdictConclusion.REACHABLE,
                confidence=0.9,
                taint_path=["app/main.py:user"],
                basis="static path",
                decided_by="tracer",
                decided_at=observed,
            )
        )
        proof = Proof(
            proof_id=f"P-{issue_id}",
            issue_id=issue_id,
            test_path="tests/security/test_sql.py",
            pre_patch_result=ProofResult.FAIL,
            fingerprint=("a" * 63) + issue_id[-1],
            env_snapshot=EnvSnapshot(),
            generated_marker="AUTOGENERATED",
            created_at=observed,
        )
        store.add_proof(proof)
        store.record_reproduction(
            ReproductionAttempt(
                attempt_id=f"RA-{issue_id}#1",
                issue_id=issue_id,
                attempt_index=1,
                status=ReproductionAttemptStatus.PROVEN,
                proof_id=proof.proof_id,
                created_at=observed,
            )
        )
        patch = Patch(
            patch_id=f"PA-{issue_id}",
            issue_id=issue_id,
            proof_id=proof.proof_id,
            branch=f"verifix/{issue_id}",
            diff_ref="sha256:" + "b" * 64,
            lines_changed=2,
            files_changed=1,
            fix_paradigm=FixParadigm.PARAMETERIZED_QUERY,
            patch_strength=0.8,
            created_at=observed,
        )
        store.add_patch(patch)
        store.record_patch(
            PatchAttempt(
                attempt_id=f"PA-{issue_id}#1",
                issue_id=issue_id,
                attempt_index=1,
                patch_id=patch.patch_id,
                created_at=observed,
            )
        )
        store.record_gate(
            GateAttempt(
                attempt_id=f"GA-{patch.patch_id}#1",
                patch_id=patch.patch_id,
                issue_id=issue_id,
                outcome=GateOutcome.PASSED,
                red_green_paired=True,
                regression_zero_fail=True,
                coverage_delta_pp=0.0,
                observed_at=observed,
            )
        )
        ready_at = observed + timedelta(minutes=30)
        store.add_disposition(
            Disposition(
                disposition_id=f"D-{issue_id}",
                issue_id=issue_id,
                level=DispositionLevel.L1,
                action="open pr #1",
                evidence_ref="pipeline/run-1",
                reason_code="GATE_PASSED",
                decided_at=ready_at,
                gate_outcome=GateOutcome.PASSED,
                ready_at=ready_at,
            )
        )
        store.record_disposition(
            DispositionHistoryEntry(
                attempt_id=f"PA-{issue_id}#1",
                issue_id=issue_id,
                level=DispositionLevel.L1,
                gate_outcome=GateOutcome.PASSED,
                decided_at=ready_at,
                ready_at=ready_at,
            )
        )

    for index in range(repro_failed):
        issue_id = f"ISR-{index + 1:03d}"
        make_issue(issue_id)
        store.update(store.get(issue_id).model_copy(update={"status": IssueStatus.REPRO_FAILED}))
        store.add_verdict(
            Verdict(
                verdict_id=f"V-{issue_id}",
                issue_id=issue_id,
                conclusion=VerdictConclusion.REACHABLE,
                confidence=0.8,
                taint_path=["app/main.py:user"],
                basis="static path",
                decided_by="tracer",
                decided_at=observed,
            )
        )
        store.record_reproduction(
            ReproductionAttempt(
                attempt_id=f"RA-{issue_id}#1",
                issue_id=issue_id,
                attempt_index=1,
                status=ReproductionAttemptStatus.REPRO_FAILED,
                created_at=observed,
            )
        )

    created = 0
    for index in range(issues):
        issue_id = f"ISF-{index + 1:03d}"
        run = Run(
            run_id=f"RUN-{issue_id}",
            issue_id=issue_id,
            started_at=datetime(2027, 1, 6, 10, 0, tzinfo=timezone.utc),
            deadline_at=datetime(2027, 1, 6, 12, 0, tzinfo=timezone.utc),
        )
        store.add_run(run)
        for seq in range(events_per_run):
            store.append(
                Event(
                    event_id=f"E-{issue_id}-{seq}",
                    run_id=run.run_id,
                    seq=seq + 1,
                    event_type=EventType.INGEST,
                    actor="perf",
                )
            )
            created += 1
    return store, {"issues": issues + repro_failed, "events": created}


def collect_ledger() -> dict:
    specs = {
        "requirement_text_ref": (".codeartsdoer/specs/metrics_recalc/spec.md", "读操作开销"),
        "design_text_ref": (".codeartsdoer/specs/metrics_recalc/design.md", "465"),
        "assertion_text_ref": ("backend/tests/test_metrics_perf.py", "104"),
    }
    ledger: dict = {}
    for key, (path, line_no) in specs.items():
        target = ROOT / path
        if not target.is_file():
            fail("LEDGER_INCOMPLETE", f"missing ledger source: {path}")
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        index = int(line_no) - 1 if line_no.isdigit() else 0
        if not line_no.isdigit():
            index = next((i for i, text in enumerate(lines) if line_no in text), -1)
        if index < 0 or index >= len(lines) or not lines[index].strip():
            fail("LEDGER_INCOMPLETE", f"line not found: {path}:{line_no}")
        ledger[key] = {"path": path, "line": line_no, "text": lines[index].strip()}
    ledger["captured_at"] = now_iso()
    validate_record(ledger, "SemanticsLedger")
    return ledger


def measure_capture(*, env_mode: str, out_dir: Path, samples: int = 5) -> dict:
    from app.evidence.store import LocalEvidenceStore
    from app.domain.enums import StageTier
    from app.metrics.snapshot import SnapshotBuilder

    if samples < 5:
        fail("SAMPLE_COUNT_INSUFFICIENT", f"samples must be >= 5, got {samples}")
    environment = declare_env(env_mode)
    store, scale = build_scale()
    stamp = ts_stamp()
    out_dir.mkdir(parents=True, exist_ok=True)
    sample_path = out_dir / f"samples-metrics-capture-{stamp}.jsonl"
    elapsed_values: list[float] = []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        builder = SnapshotBuilder(store, LocalEvidenceStore(Path(tmp) / "evidence"))
        for index in range(1, samples + 1):
            started = time.perf_counter()
            envelope = builder.capture("2026-12", StageTier.PRELIMINARY)
            elapsed = (time.perf_counter() - started) * 1000.0
            elapsed_values.append(elapsed)
            append_record(
                sample_path,
                {
                    "sample_index": index,
                    "case_id": CASE_ID,
                    "measurement_object": "SnapshotBuilder.capture 端到端耗时",
                    "elapsed_ms": round(elapsed, 3),
                    "over_threshold": elapsed > THRESHOLD_MS,
                    "collected_at": now_iso(),
                },
                kind="PerfSampleRecord",
            )
        if envelope.ref.event_count != scale["events"]:
            fail("SUT_EXCEPTION", f"event count mismatch: {envelope.ref.event_count} != {scale['events']}")
    record = {
        "case_id": CASE_ID,
        "measurement_object": "SnapshotBuilder.capture 端到端耗时",
        "measurement_scope": {
            "container_copy": True,
            "field_redaction": True,
            "serialization": True,
            "digest_compute": True,
            "disk_write": True,
            "note": "端到端包含加工与 I/O，不得作为 spec 4.1-2 写阻塞判据",
        },
        "data_scale": scale,
        "samples": samples,
        "median_ms": round(statistics.median(elapsed_values), 3),
        "max_ms": round(max(elapsed_values), 3),
        "over_budget_count": sum(1 for value in elapsed_values if value > THRESHOLD_MS),
        "threshold_ms": THRESHOLD_MS,
        "evidence_level": "L2",
        "semantics_consistent": False,
        "semantics_note": (
            "spec 4.1-2 约束对象是'复算对主流程的读取不得阻塞主流程写入超过 200 毫秒'；"
            "协议 A 测得的是 capture 端到端耗时，含容器拷贝、脱敏、序列化、摘要与落盘，"
            "不构成写阻塞判据（design D-01）"
        ),
        "fingerprint_sha256": hashlib.sha256(
            json.dumps([round(value, 3) for value in elapsed_values], sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "environment": environment,
        "ledger": collect_ledger(),
        "elapsed_ms_series": [round(value, 3) for value in elapsed_values],
        "out_dir": str(out_dir),
        "generated_at": now_iso(),
    }
    validate_record(record, "MeasurementRecord")
    append_record(out_dir / f"measure-metrics-capture-{stamp}.json", record, kind="MeasurementRecord")
    record["samples_path"] = str(sample_path)
    return record


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = min(len(ordered) - 1, max(0, int(round(ratio * (len(ordered) - 1)))))
    return ordered[position]


def measure_write_block(*, env_mode: str, out_dir: Path, write_ops: int = 200, round_index: int = 0) -> dict:
    import threading as _threading

    from app.domain.enums import EventType, StageTier
    from app.domain.models import Event
    from app.evidence.store import LocalEvidenceStore
    from app.metrics.snapshot import SnapshotBuilder

    environment = declare_env(env_mode, concurrent_load=True)
    baseline_store, scale = build_scale()
    event_ids = [f"WB-{index + 1:03d}" for index in range(write_ops)]
    baseline: list[float] = []
    baseline_ids: list[str] = []
    for event_id in event_ids:
        started = time.perf_counter()
        baseline_store.append(
            Event(event_id=event_id, run_id="RUN-ISF-001", seq=9000, event_type=EventType.INGEST, actor="perf-wb")
        )
        baseline.append((time.perf_counter() - started) * 1000.0)
        baseline_ids.append(event_id)

    interference_store, _ = build_scale()
    stop = _threading.Event()
    barrier_errors: list[str] = []

    def load() -> None:
        try:
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                builder = SnapshotBuilder(interference_store, LocalEvidenceStore(Path(tmp) / "evidence"))
                while not stop.is_set():
                    builder.capture("2026-12", StageTier.PRELIMINARY)
        except Exception as exc:  # noqa: BLE001 - 记录并发线程异常，由主流程判定
            barrier_errors.append(repr(exc))

    worker = _threading.Thread(target=load, daemon=True)
    interference: list[float] = []
    interference_ids: list[str] = []
    try:
        worker.start()
        time.sleep(0.05)
        for event_id in event_ids:
            started = time.perf_counter()
            interference_store.append(
                Event(event_id=event_id, run_id="RUN-ISF-001", seq=9000, event_type=EventType.INGEST, actor="perf-wb")
            )
            interference.append((time.perf_counter() - started) * 1000.0)
            interference_ids.append(event_id)
    finally:
        stop.set()
        worker.join(timeout=60)
    if barrier_errors:
        fail("THREAD_UNAVAILABLE", "; ".join(barrier_errors))
    if baseline_ids != interference_ids:
        fail("THREAD_UNAVAILABLE", "write sequence differs between baseline and interference segments")
    record = {
        "case_id": CASE_ID,
        "baseline_p50_ms": round(_percentile(baseline, 0.50), 4),
        "baseline_p95_ms": round(_percentile(baseline, 0.95), 4),
        "baseline_max_ms": round(max(baseline), 4),
        "interference_p50_ms": round(_percentile(interference, 0.50), 4),
        "interference_p95_ms": round(_percentile(interference, 0.95), 4),
        "interference_max_ms": round(max(interference), 4),
        "delta_p95_ms": round(_percentile(interference, 0.95) - _percentile(baseline, 0.95), 4),
        "baseline_ops": len(baseline),
        "interference_ops": len(interference),
        "event_id_set_equal": baseline_ids == interference_ids,
        "thread_model_note": (
            "内存实现（MemoryStore，无锁）；CPython GIL 下阻塞表现为调度延迟，"
            "不得外推至 MySQL/持久化后端"
        ),
        "evidence_level": "L3",
        "measurement_scope": {
            "container_copy": False,
            "field_redaction": False,
            "serialization": False,
            "digest_compute": False,
            "disk_write": False,
            "note": "仅测主流程写入延迟增量，不含落盘写入",
        },
        "data_scale": scale,
        "environment": environment,
        "generated_at": now_iso(),
    }
    validate_record(record, "WriteBlockRecord")
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = f"-r{round_index}" if round_index else ""
    append_record(out_dir / f"write-block-metrics-capture-{ts_stamp()}{suffix}.json", record, kind="WriteBlockRecord")
    return record


def judge(record: dict, ledger: dict) -> dict:
    for key in ("requirement_text_ref", "design_text_ref", "assertion_text_ref"):
        if not ledger.get(key):
            fail("LEDGER_INCOMPLETE", f"ledger missing {key}")
    if record.get("samples", 0) < 5:
        return {"decision_class": "证据不足", "decision_reason": "样本数小于 5 或环境声明缺项"}
    if record.get("noncompliant_change_set"):
        return {"decision_class": "不合规", "decision_reason": "变更集含阈值调大 / sleep / skip / 数据量下降"}
    if record.get("semantics_consistent") is False:
        return {"decision_class": "阈值口径问题", "decision_reason": "测量对象或判定语义与需求条款不一致"}
    over = int(record.get("over_budget_count", 0))
    if over >= 4 and record.get("scale_monotonic", True):
        return {"decision_class": "性能缺陷", "decision_reason": "语义一致且 4/5 以上超门槛并随规模单调恶化"}
    if over <= 1 and record.get("only_under_load", False):
        return {"decision_class": "偶发抖动", "decision_reason": "语义一致、仅并发或冷启动场景偶发超门槛"}
    if over > 0 and not record.get("observable_marker", False):
        return {"decision_class": "实现缺口", "decision_reason": "抓取超预算且无任何可观测标记（IF-01）"}
    return {"decision_class": "证据不足", "decision_reason": "统计特征不足以落入任一裁定类别"}


def _p50_p95_max(values: list[float]) -> tuple[float, float, float]:
    if not values:
        return 0.0, 0.0, 0.0
    return (
        round(statistics.median(values), 4),
        round(_percentile(values, 0.95), 4),
        round(max(values), 4),
    )


def write_new_json(path: Path, payload: dict) -> None:
    if is_readonly_target(path):
        fail("READONLY_VIOLATION", f"refuse to write immutable carrier: {path}")
    if path.exists():
        fail("OUTPUT_EXISTS", f"record already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def measure_capture_segmented(
    *,
    case: str,
    env_mode: str,
    out_dir: Path,
    rounds: int = 3,
    samples: int = 5,
    write_ops: int = 200,
) -> dict:
    from app.domain.enums import StageTier
    from app.evidence.store import LocalEvidenceStore
    from app.metrics.snapshot import SnapshotBuilder

    if case != CASE_ID:
        fail("INVALID_CASE_ID", f"case must be {CASE_ID}")
    if rounds < ROUND_RULES["rounds_required"]:
        fail("ROUNDS_INSUFFICIENT", f"rounds must be >= 3, got {rounds}")
    if samples < ROUND_RULES["samples_required"]:
        fail("SAMPLE_COUNT_INSUFFICIENT", f"samples must be >= 5, got {samples}")
    environment = declare_env(env_mode)
    stamp = ts_stamp()
    out_dir.mkdir(parents=True, exist_ok=True)
    produced: list[dict] = []
    for round_index in range(1, rounds + 1):
        store, scale = build_scale()
        if scale["issues"] != 1100 or scale["events"] != 12000:
            fail("SUT_EXCEPTION", f"data scale mismatch: {scale}")
        sample_path = out_dir / f"samples-metrics-capture-segmented-{stamp}-r{round_index}.jsonl"
        write_values: list[float] = []
        total_values: list[float] = []
        encode_counts: list[int] = []
        over_count = 0
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            builder = SnapshotBuilder(store, LocalEvidenceStore(Path(tmp) / "evidence"))
            for index in range(1, samples + 1):
                envelope = builder.capture("2026-12", StageTier.PRELIMINARY)
                ref = envelope.ref
                over = ref.capture_total_ms > ref.capture_budget_ms
                over_count += 1 if over else 0
                write_values.append(float(ref.write_block_ms))
                total_values.append(float(ref.capture_total_ms))
                encode_counts.append(int(ref.encode_count))
                append_record(
                    sample_path,
                    {
                        "sample_index": index,
                        "round_index": round_index,
                        "case_id": CASE_ID,
                        "write_block_ms": ref.write_block_ms,
                        "capture_ms": ref.capture_ms,
                        "capture_total_ms": ref.capture_total_ms,
                        "segment_ms": ref.segment_ms,
                        "encode_count": ref.encode_count,
                        "over_capture_budget": over,
                        "collected_at": now_iso(),
                    },
                    kind="SegmentedSampleRecord",
                )
        if any(value != ROUND_RULES["encode_count"] for value in encode_counts):
            fail("SUT_EXCEPTION", f"encode_count drifted in round {round_index}: {encode_counts}")
        wb_p50, wb_p95, wb_max = _p50_p95_max(write_values)
        total_p50, total_p95, total_max = _p50_p95_max(total_values)
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "write_block_ms": write_values,
                    "capture_total_ms": total_values,
                    "encode_count": encode_counts,
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        measure = {
            "case_id": CASE_ID,
            "round_index": round_index,
            "samples": samples,
            "data_scale": scale,
            "write_ops": write_ops,
            "write_block_p50_ms": wb_p50,
            "write_block_p95_ms": wb_p95,
            "write_block_max_ms": wb_max,
            "capture_total_p50_ms": total_p50,
            "capture_total_p95_ms": total_p95,
            "capture_total_max_ms": total_max,
            "over_capture_budget_count": over_count,
            "encode_count": ROUND_RULES["encode_count"],
            "measurement_scope": {
                "write_block_judged": True,
                "capture_end_to_end_judged": False,
                "note": (
                    "200ms 仅判 write_block_ms（capture 临界段）；"
                    "capture_total_ms 超过 capture_budget_ms 只产生 CAPTURE_SLOW 非阻断告警"
                ),
            },
            "environment": environment,
            "fingerprint_sha256": fingerprint,
            "evidence_level": "L3",
            "samples_path": str(sample_path),
            "stamp": stamp,
            "generated_at": now_iso(),
        }
        measure_path = out_dir / f"measure-metrics-capture-segmented-{stamp}-r{round_index}.json"
        append_record(measure_path, measure, kind="SegmentedMeasurementRecord")
        produced.append({"round_index": round_index, "measure": measure_path, "samples": sample_path})
    return {"stamp": stamp, "rounds": produced, "samples": samples, "write_ops": write_ops}


def evaluate_round(*, round_index: int, measure: dict, write_block: dict, regression: dict, samples: list[dict]) -> dict:
    reasons: list[str] = []
    if any(int(item.get("write_block_ms", 0)) > ROUND_RULES["write_block_budget_ms"] for item in samples):
        reasons.append("write_block_ms")
    if float(write_block.get("delta_p95_ms", 0.0) or 0.0) > ROUND_RULES["delta_p95_budget_ms"]:
        reasons.append("delta_p95_ms")
    if int(regression.get("failures", 0)) > ROUND_RULES["regression_failures"] or int(
        regression.get("errors", 0)
    ) > ROUND_RULES["regression_failures"]:
        reasons.append("regression_failures")
    counts = [int(item.get("encode_count", 0)) for item in samples]
    counts.append(int(measure.get("encode_count", 0)))
    if any(value != ROUND_RULES["encode_count"] for value in counts):
        reasons.append("encode_count")
    return {"round_index": round_index, "passed": not reasons, "reasons": reasons}


def _latest_by_round(out_dir: Path, prefix: str, round_index: int, suffix: str = ".json") -> Path | None:
    pattern = f"{prefix}*-r{round_index}{suffix}"
    candidates = sorted(p for p in out_dir.glob(pattern) if p.is_file())
    return candidates[-1] if candidates else None


def round_summary(*, case: str, out_dir: Path) -> dict:
    if case != CASE_ID:
        fail("INVALID_CASE_ID", f"case must be {CASE_ID}")
    rounds: list[dict] = []
    for round_index in range(1, ROUND_RULES["rounds_required"] + 1):
        measure_path = _latest_by_round(out_dir, "measure-metrics-capture-segmented-", round_index)
        samples_path = _latest_by_round(out_dir, "samples-metrics-capture-segmented-", round_index, ".jsonl")
        write_path = _latest_by_round(out_dir, "write-block-metrics-capture-", round_index)
        reg_path = _latest_by_round(out_dir, "regression-", round_index)
        missing = [
            name
            for name, path in (
                ("measure", measure_path),
                ("samples", samples_path),
                ("write_block", write_path),
                ("regression", reg_path),
            )
            if path is None
        ]
        if missing:
            fail("EVIDENCE_MISSING", f"round {round_index} missing: {','.join(missing)}")
        measure = json.loads(measure_path.read_text(encoding="utf-8"))
        samples = [
            json.loads(line)
            for line in samples_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        write_block = json.loads(write_path.read_text(encoding="utf-8"))
        regression = json.loads(reg_path.read_text(encoding="utf-8"))
        if len(samples) < ROUND_RULES["samples_required"]:
            fail("SAMPLE_COUNT_INSUFFICIENT", f"round {round_index} samples={len(samples)}")
        verdict = evaluate_round(
            round_index=round_index,
            measure=measure,
            write_block=write_block,
            regression=regression,
            samples=samples,
        )
        round_record = {
            "case_id": CASE_ID,
            "round_index": round_index,
            "samples_path": rel(samples_path),
            "measure_path": rel(measure_path),
            "write_block_path": rel(write_path),
            "regression_path": rel(reg_path),
            "samples_sha256": sha256_file(samples_path),
            "measure_sha256": sha256_file(measure_path),
            "write_block_sha256": sha256_file(write_path),
            "regression_sha256": sha256_file(reg_path),
            "passed": verdict["passed"],
            "reasons": verdict["reasons"],
            "generated_at": now_iso(),
        }
        validate_record(round_record, "PerfRoundRecord")
        rounds.append(round_record)
    failed = [item for item in rounds if not item["passed"]]
    if failed:
        reasons = sorted({reason for item in failed for reason in item["reasons"]})
        decision_class = "不通过"
        decision_reason = "第 " + ",".join(str(item["round_index"]) for item in failed) + " 轮未达标：" + ",".join(reasons)
    else:
        decision_class = "通过"
        decision_reason = "写阻塞口径满足 spec 4.1-2；抓取端到端超预算仅告警，不构成 4.1-2 判据"
    summary = {
        "case_id": CASE_ID,
        "decision_class": decision_class,
        "decision_reason": decision_reason,
        "rules": dict(ROUND_RULES),
        "rounds": rounds,
        "supersedes": [],
        "thread_model_note": (
            "内存实现（MemoryStore，无锁）；CPython GIL 下阻塞表现为调度延迟，"
            "不得外推至 MySQL/持久化后端"
        ),
        "generated_at": now_iso(),
    }
    write_new_json(out_dir / f"round-summary-{ts_stamp()}.json", summary)
    return summary


def record_regression(*, out_dir: Path, round_index: int) -> int:
    if round_index < 1:
        fail("ENV_DECLARATION_INVALID", "round must be >= 1")
    command = [
        sys.executable,
        "-m",
        "unittest",
        "discover",
        "-s",
        "backend/tests",
        "-p",
        "test_*.py",
    ]
    started = time.perf_counter()
    proc = subprocess.run(
        command,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    duration = round(time.perf_counter() - started, 3)
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    ran_match = re.search(r"Ran (\d+) tests", text)
    counts_match = re.search(r"FAILED \((.*?)\)", text)
    errors = 0
    failures = 0
    if counts_match:
        for part in counts_match.group(1).split(","):
            key, _, value = part.strip().partition("=")
            if key == "errors":
                errors = int(value)
            elif key == "failures":
                failures = int(value)
    failed_names = [
        line.split(" ", 1)[1].strip()
        for line in text.splitlines()
        if line.startswith("FAIL: ") or line.startswith("ERROR: ")
    ]
    record = {
        "check_id": "D1-1",
        "round_index": round_index,
        "command": " ".join(command),
        "exit_code": proc.returncode,
        "duration_seconds": duration,
        "ran": int(ran_match.group(1)) if ran_match else 0,
        "errors": errors,
        "failures": failures,
        "failed_test_names": failed_names,
        "contains_skip": "skipped=" in text,
        "stdout_tail": text.strip().splitlines()[-5:],
        "collected_at": now_iso(),
    }
    write_new_json(out_dir / f"regression-{ts_stamp()}-r{round_index}.json", record)
    return proc.returncode


def _selftest() -> int:
    checks: list[tuple[str, bool, str]] = []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        base = Path(tmp)
        jsonl = base / "sample.jsonl"
        jsonl.write_text('{"x": 1}\n', encoding="utf-8")
        before = jsonl.read_bytes()
        append_record(
            jsonl,
            {
                "sample_index": 1,
                "case_id": CASE_ID,
                "measurement_object": "selftest",
                "elapsed_ms": 1.0,
                "over_threshold": False,
                "collected_at": now_iso(),
            },
            kind="PerfSampleRecord",
        )
        after = jsonl.read_bytes()
        checks.append(("PASS" if after.startswith(before) and after.count(b"\n") == 2 else "FAIL", True, "jsonl append keeps prefix"))

        single = base / "single.json"
        single.write_text('{"v": 1}\n', encoding="utf-8")
        size_before = single.stat().st_size
        try:
            append_record(
                single,
                {
                    "requirement_text_ref": "r",
                    "design_text_ref": "d",
                    "assertion_text_ref": "a",
                    "captured_at": now_iso(),
                },
                kind="SemanticsLedger",
            )
            rejected = False
        except ProbeError as exc:
            rejected = exc.code == "OUTPUT_EXISTS"
        checks.append(("PASS" if rejected and single.stat().st_size == size_before else "FAIL", rejected, "json output exists rejected"))

        target = ROOT / "docs" / "devlog" / "selfcheck" / "index.json"
        digest_before = sha256_file(target)
        try:
            append_record(target, {"x": 1}, kind="SemanticsLedger")
            ro_rejected = False
        except ProbeError as exc:
            ro_rejected = exc.code == "READONLY_VIOLATION"
        checks.append(("PASS" if ro_rejected and sha256_file(target) == digest_before else "FAIL", ro_rejected, "readonly violation"))

    schema_hits = 0
    samples = {
        "EnvironmentDeclaration": {
            "mode": "default",
            "os_name": "x",
            "os_release": "x",
            "python_version": "3",
            "python_utf8_env": None,
            "python_io_encoding": None,
            "python_path": None,
            "retained_env_keys": ["PATH"],
            "concurrent_load": False,
            "declared_at": now_iso(),
        },
        "PerfSampleRecord": {
            "sample_index": 1,
            "case_id": CASE_ID,
            "measurement_object": "x",
            "elapsed_ms": 1.0,
            "over_threshold": False,
            "collected_at": now_iso(),
        },
        "MeasurementRecord": {
            "case_id": CASE_ID,
            "measurement_object": "x",
            "measurement_scope": {"container_copy": True},
            "data_scale": {"issues": 1100, "events": 12000},
            "samples": 5,
            "median_ms": 1.0,
            "max_ms": 2.0,
            "over_budget_count": 0,
            "threshold_ms": 200,
"evidence_level": "L2",
        "semantics_consistent": False,
        "semantics_note": (
            "spec 4.1-2 约束对象是'复算对主流程的读取不得阻塞主流程写入超过 200 毫秒'；"
            "协议 A 测得的是 capture 端到端耗时，含容器拷贝、脱敏、序列化、摘要与落盘，"
            "不构成写阻塞判据（design D-01）"
        ),
            "fingerprint_sha256": "a" * 64,
            "environment": {},
            "ledger": {},
        },
        "WriteBlockRecord": {
            "case_id": CASE_ID,
            "baseline_p50_ms": 1.0,
            "baseline_p95_ms": 2.0,
            "baseline_max_ms": 3.0,
            "interference_p50_ms": 1.0,
            "interference_p95_ms": 2.0,
            "interference_max_ms": 3.0,
            "delta_p95_ms": 0.0,
            "thread_model_note": "GIL",
            "evidence_level": "L3",
            "measurement_scope": {},
            "environment": {},
        },
        "ReproducibilityRecord": {
            "check_id": "D1-1",
            "coverage_layer": "config-load",
            "command": "x",
            "exit_code": 0,
            "duration_seconds": 1.0,
            "ran": 0,
            "errors": 0,
            "failures": 0,
            "failed_test_names": [],
            "stopped_at_layer": None,
            "evidence_gap": False,
            "env_mode": "default",
            "retained_env_keys": ["PATH"],
        },
        "CloseoutDecisionRecord": {
            "topic": "x",
            "decision_class": "阈值口径问题",
            "spec_refs": ["5.1.1-2c"],
            "original_text_refs": ["a"],
            "evidence_paths": ["b"],
            "immutable_carriers": ["c"],
            "effective_date": "2026-11-19",
        },
        "RelatedFindingRecord": {
            "finding_id": "RF-01",
            "title": "x",
            "reproduce_command": "x",
            "stability": "stable",
            "ownership": "范围外",
            "blocking_relation": "none",
            "suggestion": "x",
        },
        "SemanticsLedger": {
            "requirement_text_ref": "a",
            "design_text_ref": "b",
            "assertion_text_ref": "c",
            "captured_at": now_iso(),
        },
    }
    for kind, payload in samples.items():
        validate_record(payload, kind)
        broken = dict(payload)
        broken.pop(next(iter(REQUIRED[kind])))
        rejected = False
        try:
            validate_record(broken, kind)
        except ProbeError as exc:
            rejected = exc.code == "SCHEMA_INVALID"
        if rejected:
            schema_hits += 1
    checks.append(("PASS" if schema_hits == 8 else "FAIL", schema_hits == 8, f"schema checks={schema_hits * 2}"))

    bad_finding = dict(samples["RelatedFindingRecord"], finding_id="X-01")
    try:
        validate_record(bad_finding, "RelatedFindingRecord")
        rf_rejected = False
    except ProbeError:
        rf_rejected = True
    checks.append(("PASS" if rf_rejected else "FAIL", rf_rejected, "RF finding_id prefix"))

    store, scale = build_scale(issues=5, repro_failed=1, events_per_run=12)
    checks.append(("PASS" if scale["events"] == 60 else "FAIL", scale["events"] == 60, f"scale issue={scale['issues']} events={scale['events']}"))

    ledger = {
        "requirement_text_ref": "r",
        "design_text_ref": "d",
        "assertion_text_ref": "a",
        "captured_at": now_iso(),
    }
    fixtures = [
        ({"samples": 5, "over_budget_count": 4, "semantics_consistent": True, "scale_monotonic": True}, "性能缺陷"),
        ({"samples": 5, "over_budget_count": 1, "semantics_consistent": True, "only_under_load": True}, "偶发抖动"),
        ({"samples": 5, "over_budget_count": 0, "semantics_consistent": False}, "阈值口径问题"),
        ({"samples": 4, "over_budget_count": 0}, "证据不足"),
        ({"samples": 5, "noncompliant_change_set": True, "over_budget_count": 0}, "不合规"),
        ({"samples": 5, "over_budget_count": 2, "semantics_consistent": True, "observable_marker": False}, "实现缺口"),
    ]
    judge_hits = sum(1 for record, expected in fixtures if judge(record, ledger)["decision_class"] == expected)
    checks.append(("PASS" if judge_hits == 6 else "FAIL", judge_hits == 6, f"judge fixtures={judge_hits}/6"))
    priority = judge({"samples": 5, "over_budget_count": 4, "semantics_consistent": False}, ledger)["decision_class"]
    checks.append(("PASS" if priority == "阈值口径问题" else "FAIL", priority == "阈值口径问题", "priority: semantics > statistics"))

    extra_samples = {
        "SegmentedSampleRecord": {
            "sample_index": 1,
            "round_index": 1,
            "case_id": CASE_ID,
            "write_block_ms": 1,
            "capture_ms": 2,
            "capture_total_ms": 3,
            "segment_ms": {"clone": 1},
            "encode_count": 1,
            "over_capture_budget": False,
            "collected_at": now_iso(),
        },
        "SegmentedMeasurementRecord": {
            "case_id": CASE_ID,
            "round_index": 1,
            "samples": 5,
            "data_scale": {"issues": 1100, "events": 12000},
            "write_ops": 200,
            "write_block_p50_ms": 1.0,
            "write_block_p95_ms": 1.0,
            "write_block_max_ms": 1.0,
            "capture_total_p50_ms": 2.0,
            "capture_total_p95_ms": 2.0,
            "capture_total_max_ms": 2.0,
            "over_capture_budget_count": 0,
            "encode_count": 1,
            "measurement_scope": {"write_block_judged": True, "capture_end_to_end_judged": False},
            "environment": {},
            "fingerprint_sha256": "a" * 64,
            "evidence_level": "L3",
            "generated_at": now_iso(),
        },
        "PerfRoundRecord": {
            "case_id": CASE_ID,
            "round_index": 1,
            "samples_path": "a",
            "measure_path": "b",
            "write_block_path": "c",
            "regression_path": "d",
            "samples_sha256": "e",
            "measure_sha256": "f",
            "write_block_sha256": "g",
            "regression_sha256": "h",
            "passed": True,
            "reasons": [],
            "generated_at": now_iso(),
        },
    }
    extra_schema_hits = 0
    for kind, payload in extra_samples.items():
        validate_record(payload, kind)
        broken = dict(payload)
        broken.pop(next(iter(EXTRA_REQUIRED[kind])))
        try:
            validate_record(broken, kind)
        except ProbeError as exc:
            if exc.code == "SCHEMA_INVALID":
                extra_schema_hits += 1
    checks.append(("PASS" if extra_schema_hits == 3 else "FAIL", extra_schema_hits == 3, f"extra schema checks={extra_schema_hits}"))

    ok_verdict = evaluate_round(
        round_index=1,
        measure={"encode_count": 1},
        write_block={"delta_p95_ms": 0.0},
        regression={"failures": 0, "errors": 0},
        samples=[{"write_block_ms": 1, "encode_count": 1}],
    )
    bad_verdict = evaluate_round(
        round_index=1,
        measure={"encode_count": 1},
        write_block={"delta_p95_ms": 0.0},
        regression={"failures": 0, "errors": 0},
        samples=[{"write_block_ms": 201, "encode_count": 1}],
    )
    round_rules_ok = ok_verdict["passed"] and not bad_verdict["passed"] and "write_block_ms" in bad_verdict["reasons"]
    checks.append(("PASS" if round_rules_ok else "FAIL", round_rules_ok, "round rule fixtures"))


    for state, ok, detail in checks:
        print(f"{state} {detail}")
    return 0 if all(ok for _, ok, _ in checks) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PERF-02 阈值口径取证探针")
    parser.add_argument("--selftest", action="store_true")
    sub = parser.add_subparsers(dest="command")
    for name in ("capture", "write-block"):
        node = sub.add_parser(name)
        node.add_argument("--case", required=True)
        node.add_argument("--env", default=None, choices=("default", "clean"))
        node.add_argument("--samples", type=int, default=5)
        node.add_argument("--write-ops", type=int, default=200)
        node.add_argument("--round", type=int, default=0, dest="round_index")
        node.add_argument("--out", default=str(DEFAULT_OUT))
    segmented_node = sub.add_parser("capture-segmented")
    segmented_node.add_argument("--case", required=True)
    segmented_node.add_argument("--env", default=None, choices=("default", "clean"))
    segmented_node.add_argument("--rounds", type=int, default=3)
    segmented_node.add_argument("--samples", type=int, default=5)
    segmented_node.add_argument("--write-ops", type=int, default=200)
    segmented_node.add_argument("--out", default=str(DEFAULT_OUT))
    summary_node = sub.add_parser("round-summary")
    summary_node.add_argument("--case", required=True)
    summary_node.add_argument("--out", default=str(DEFAULT_OUT))
    regression_node = sub.add_parser("regression")
    regression_node.add_argument("--round", type=int, default=1, dest="round_index")
    regression_node.add_argument("--out", default=str(DEFAULT_OUT))
    env_node = sub.add_parser("env")
    env_node.add_argument("--env", required=True, choices=("default", "clean"))
    env_node.add_argument("--out", default=str(DEFAULT_OUT))
    imm_node = sub.add_parser("immutable")
    imm_node.add_argument("--out", default=str(DEFAULT_OUT))
    judge_node = sub.add_parser("judge")
    judge_node.add_argument("--measure", required=True)
    judge_node.add_argument("--out", default=str(DEFAULT_OUT))

    args = parser.parse_args(argv)
    if args.selftest:
        return _selftest()
    try:
        if args.command == "capture":
            if args.case != CASE_ID:
                fail("INVALID_CASE_ID", f"case must be {CASE_ID}")
            record = measure_capture(env_mode=args.env, out_dir=Path(args.out), samples=args.samples)
            print(json.dumps({k: record[k] for k in ("median_ms", "max_ms", "over_budget_count", "samples")}, ensure_ascii=False))
            return 0
        if args.command == "write-block":
            if args.case != CASE_ID:
                fail("INVALID_CASE_ID", f"case must be {CASE_ID}")
            record = measure_write_block(
                env_mode=args.env,
                out_dir=Path(args.out),
                write_ops=args.write_ops,
                round_index=args.round_index,
            )
            print(
                json.dumps(
                    {k: record[k] for k in ("baseline_p95_ms", "interference_p95_ms", "delta_p95_ms", "evidence_level")},
                    ensure_ascii=False,
                )
            )
            return 0
        if args.command == "capture-segmented":
            outcome = measure_capture_segmented(
                case=args.case,
                env_mode=args.env,
                out_dir=Path(args.out),
                rounds=args.rounds,
                samples=args.samples,
                write_ops=args.write_ops,
            )
            print(json.dumps({"stamp": outcome["stamp"], "rounds": len(outcome["rounds"]), "samples": outcome["samples"]}, ensure_ascii=False))
            return 0
        if args.command == "round-summary":
            summary = round_summary(case=args.case, out_dir=Path(args.out))
            print(json.dumps({k: summary[k] for k in ("decision_class", "decision_reason")}, ensure_ascii=False))
            return 0
        if args.command == "regression":
            return record_regression(out_dir=Path(args.out), round_index=args.round_index)
        if args.command == "env":
            declaration = declare_env(args.env)
            out = Path(args.out)
            out.mkdir(parents=True, exist_ok=True)
            print(json.dumps(declaration, ensure_ascii=False))
            return 0
        if args.command == "immutable":
            paths = immutable_paths()
            out = Path(args.out)
            out.mkdir(parents=True, exist_ok=True)
            payload = {
                "count": len(paths),
                "paths": [{"path": item, "bytes": (ROOT / item).stat().st_size, "sha256": sha256_file(ROOT / item)} for item in paths],
                "captured_at": now_iso(),
            }
            (out / f"immutable-baseline-{ts_stamp()}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"count={len(paths)}")
            return 0
        if args.command == "judge":
            measure = json.loads(Path(args.measure).read_text(encoding="utf-8"))
            ledger = measure.get("ledger") or collect_ledger()
            verdict = judge(measure, ledger)
            print(json.dumps(verdict, ensure_ascii=False))
            return 0
        fail("ENV_DECLARATION_INVALID", "command required: capture | write-block | env | immutable | judge | --selftest")
    except ProbeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())