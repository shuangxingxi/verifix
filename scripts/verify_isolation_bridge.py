from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.api.envelope import ApiError
from app.config import load_config
from app.eval.isolation import AccessAuditLog
from app.realscan.evidence import EvidenceInput, EvidencePackWriter, EvidenceScrubber
from app.realscan.isolation_bridge import ContainerIsolationVerifier
from app.realscan.models import BoundaryKind, VerificationSource
from app.realscan.pipeline import RealscanPipeline
from app.realscan.policy import ImageResolver, PolicyFile
from app.realscan.runtime import wsl_path
from app.tools.redactor import SecretRedactor


def _mapper(transport):
    return wsl_path if getattr(transport, "name", "") == "wsl" else None


def main() -> int:
    parser = argparse.ArgumentParser(description="verify container answer isolation and write ISO evidence")
    parser.add_argument("--cases", default="eval/cases")
    parser.add_argument("--evidence-root", default=".evidence/sandbox-realscan")
    args = parser.parse_args()

    config = load_config().realscan.model_copy(update={"evidence_root": args.evidence_root, "cases_dir": args.cases})
    pipeline = RealscanPipeline(config)
    try:
        pipeline.ensure_ready()
    except ApiError as exc:
        print(json.dumps({"stage": "capability", "code": exc.code.value, "detail": exc.detail}, ensure_ascii=False))
        return 3

    evidence_root = Path(args.evidence_root)
    writer = EvidencePackWriter(evidence_root, scrubber=EvidenceScrubber())
    iso_id = writer.new_evidence_id("ISO")
    policy = PolicyFile.load(Path(config.policy_path))
    image = ImageResolver(pipeline.transport, list(config.target_images)).inspect(config.target_images[-1])
    audit_dir = evidence_root / ".audit" / iso_id
    audit = AccessAuditLog(audit_dir / "access.jsonl")
    verifier = ContainerIsolationVerifier(
        pipeline.transport,
        Path(args.cases),
        evidence_root / ".work" / iso_id,
        audit=audit,
        policy=policy,
        image=image,
        path_mapper=_mapper(pipeline.transport),
    )
    try:
        record = verifier.verify(iso_id)
    except ApiError as exc:
        shutil.rmtree(audit_dir, ignore_errors=True)
        print(json.dumps({"stage": "isolation", "code": exc.code.value, "detail": exc.detail}, ensure_ascii=False))
        return 3

    prefix = "wsl.exe -d Debian -u root -- " if getattr(pipeline.transport, "name", "") == "wsl" else ""
    commands = [
        prefix + f"docker run --rm --network=none --read-only --cap-drop=ALL --security-opt=no-new-privileges "
        f"--user=10001:10001 --volume={Path(args.cases).resolve()}:/cases:ro --workdir=/cases "
        f"--entrypoint python {image.resolved_image or config.target_images[-1]} -c 'import os;print(os.getuid())'",
    ]
    audit_text = (audit_dir / "access.jsonl").read_text(encoding="utf-8") if (audit_dir / "access.jsonl").is_file() else ""
    files = {
        "records/isolation.json": json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2),
        "audit/access.jsonl": audit_text,
    }
    payload = EvidenceInput(
        commands=commands,
        runtime_facts={"exec_domain": record.exec_domain.value, "exec_identity": record.exec_identity},
        reuse_conditions={
            "image_id": image.image_id,
            "exec_domain": record.exec_domain.value,
            "network_mode": "NONE_LOOPBACK",
            "dependency_versions": {"python": sys.version.split()[0]},
        },
        boundary_tags=[BoundaryKind.REAL_CONTAINER],
        verification_source=VerificationSource.REAL_EXECUTION,
        files=files,
        raw_output=json.dumps([probe.model_dump(mode="json") for probe in record.probes], ensure_ascii=False, indent=2),
    )
    try:
        pack = writer.write("ISO", payload, evidence_id=iso_id)
    except ApiError as exc:
        shutil.rmtree(audit_dir, ignore_errors=True)
        print(json.dumps({"stage": "evidence", "code": exc.code.value, "detail": exc.detail}, ensure_ascii=False))
        return 4
    shutil.rmtree(audit_dir, ignore_errors=True)

    summary = {
        "iso_id": record.iso_id,
        "publishable": record.publishable,
        "exec_domain": record.exec_domain.value,
        "exec_identity": record.exec_identity,
        "visible_roots": record.visible_roots,
        "denial_kind": record.denial_kind.value,
        "probes": [{"probe": probe.probe, "result": probe.result, "denial_kind": probe.denial_kind.value} for probe in record.probes],
        "exec_success_count": record.exec_success_count,
        "evidence": str(evidence_root / pack.path),
        "sha256": pack.sha256,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if record.publishable else 2


if __name__ == "__main__":
    raise SystemExit(main())