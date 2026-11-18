from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.api.envelope import ApiError
from app.config import load_config
from app.realscan.evidence import EvidenceInput, EvidencePackWriter, EvidenceScrubber
from app.realscan.models import BoundaryKind, VerificationSource
from app.realscan.pipeline import RealscanPipeline
from app.realscan.runtime import wsl_path
from app.realscan.scan import RealScanOrchestrator, scope_text
from app.realscan.worker import build_worker_bundle, worker_payload
from app.tools.redactor import SecretRedactor


def _mapper(transport):
    return wsl_path if getattr(transport, "name", "") == "wsl" else None


def main() -> int:
    parser = argparse.ArgumentParser(description="run the real target scan and write SCAN evidence")
    parser.add_argument("--scope", choices=("full", "sql-cmd"), default="full")
    parser.add_argument("--port", default="0")
    parser.add_argument("--exec", dest="exec_mode", choices=("container", "host", "auto"), default="container")
    parser.add_argument("--allow-host-fallback", choices=("on", "off"), default="on")
    parser.add_argument("--evidence-root", default=".evidence/sandbox-realscan")
    args = parser.parse_args()

    try:
        port = int(args.port)
    except ValueError:
        print(json.dumps({"error": "port must be an integer"}, ensure_ascii=False))
        return 3

    config = load_config().realscan
    config = config.model_copy(
        update={
            "evidence_root": args.evidence_root,
            "scan_scope": args.scope,
            "listen_port": port,
            "allow_host_fallback": args.allow_host_fallback == "on",
        }
    )
    evidence_root = Path(args.evidence_root)
    writer = EvidencePackWriter(evidence_root, scrubber=EvidenceScrubber())
    scan_id = writer.new_evidence_id("SCAN")

    pipeline = RealscanPipeline(config)
    orchestrator = RealScanOrchestrator(config, pipeline=pipeline, work_root=evidence_root / ".work" / scan_id)
    exec_mode = "CONTAINER" if args.exec_mode in {"container", "auto"} else "HOST"
    try:
        record = orchestrator.run(scan_id, scope_mode=args.scope, exec_mode=exec_mode)
    except ApiError as exc:
        print(json.dumps({"stage": "scan", "code": exc.code.value, "detail": exc.detail}, ensure_ascii=False))
        return 2 if exc.http_status == 503 else 3

    reconciliation = None
    try:
        reconciliation = orchestrator.reconcile(record)
    except ApiError as exc:
        print(json.dumps({"stage": "reconcile", "code": exc.code.value, "detail": exc.detail}, ensure_ascii=False))

    prefix = "wsl.exe -d Debian -u root -- " if getattr(pipeline.transport, "name", "") == "wsl" else ""
    bundle_preview = build_worker_bundle(worker_payload())
    commands = [
        prefix + "docker image inspect --format '{{.Id}}' realscan-probe:local",
        prefix + "docker run -i --rm --network=none --read-only --cap-drop=ALL --security-opt=no-new-privileges "
        "--user=10001:10001 --memory=1024m --cpus=1 --pids-limit=128 "
        "--volume=<view>:/src:ro --workdir=/src --entrypoint python realscan-probe:local - < scan_bundle/worker_bundle.py",
    ]
    # the placeholder above is replaced with the real view path before rendering
    view_path = str(evidence_root / ".work" / scan_id / "view")
    commands[1] = commands[1].replace("<view>", view_path)

    import hashlib

    bundle_sha256 = hashlib.sha256(bundle_preview.encode("utf-8")).hexdigest()
    redacted_bundle = SecretRedactor().redact(bundle_preview).text
    files = {
        "records/scan.json": json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2),
        "records/detections.json": json.dumps([item.model_dump(mode="json") for item in record.detections], ensure_ascii=False, indent=2),
        "records/dynamic_checks.json": json.dumps([item.model_dump(mode="json") for item in record.dynamic_checks], ensure_ascii=False, indent=2),
        "scan_bundle/worker_bundle.py": redacted_bundle,
        "scan_bundle/worker_bundle.sha256": bundle_sha256 + "  worker_bundle.py\n",
    }
    if reconciliation is not None:
        files["records/reconciliation.json"] = json.dumps(reconciliation.model_dump(mode="json"), ensure_ascii=False, indent=2)
    payload = EvidenceInput(
        commands=commands,
        runtime_facts={"network_mode": record.network_mode, "sandbox_scope": record.sandbox_scope},
        reuse_conditions={
            "image_id": "recorded-in-scan-json",
            "exec_domain": "CONTAINER" if record.sandbox_scope else "HOST_USER",
            "network_mode": record.network_mode,
            "dependency_versions": {"flask": "3.1.3", "python": "3.12"},
        },
        boundary_tags=[BoundaryKind.REAL_CONTAINER if record.sandbox_scope else BoundaryKind.REAL_LOCAL],
        verification_source=VerificationSource.REAL_EXECUTION if record.sandbox_scope else VerificationSource.UNVERIFIED,
        files=files,
        raw_output="",
    )
    try:
        pack = writer.write("SCAN", payload, evidence_id=scan_id)
    except ApiError as exc:
        print(json.dumps({"stage": "evidence", "code": exc.code.value, "detail": exc.detail}, ensure_ascii=False))
        return 4

    summary = {
        "scan_id": record.scan_id,
        "scan_verdict": record.scan_verdict.value,
        "scope": scope_text(record.scope),
        "listen_port": record.listen_port,
        "network_mode": record.network_mode,
        "sandbox_scope": record.sandbox_scope,
        "boundary_summary": record.boundary_summary,
        "detections": len(record.detections),
        "dynamic_checks": len(record.dynamic_checks),
        "verdict_missing": record.verdict_missing,
        "reconciliation": reconciliation.coverage if reconciliation is not None else "unavailable",
        "evidence": str(evidence_root / pack.path),
        "sha256": pack.sha256,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if record.scan_verdict.value == "ESTABLISHED":
        return 0
    if record.scan_verdict.value == "UNVERIFIED":
        return 2
    return 3


if __name__ == "__main__":
    raise SystemExit(main())