from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.api.envelope import ApiError, ErrorCode
from app.config import load_config
from app.realscan.constraints import ConstraintVerifier
from app.realscan.evidence import EvidenceInput, EvidencePackWriter, EvidenceScrubber
from app.realscan.models import BoundaryKind, DefaultAdoption, Judgement, VerificationSource
from app.realscan.pipeline import RealscanPipeline
from app.realscan.policy import JUDGEMENT_CLASSES, ImageResolver, PolicyFile
from app.realscan.runtime import wsl_path
from app.realscan.target import TargetViewBuilder
from app.tools.redactor import SecretRedactor


def _transport_prefix(transport) -> str:
    if getattr(transport, "name", "") == "wsl":
        return "wsl.exe -d Debian -u root -- "
    return ""


def _mapper(transport):
    return wsl_path if getattr(transport, "name", "") == "wsl" else None


def _reuse_conditions(transport, capability, image) -> dict:
    return {
        "image_id": image.image_id,
        "exec_domain": transport.exec_domain.value,
        "network_mode": "NONE_LOOPBACK",
        "dependency_versions": {
            "python": sys.version.split()[0],
            "docker": capability.runtime.docker_version,
            "cgroup": capability.runtime.cgroup_version,
            "driver": capability.runtime.runtime_driver,
        },
    }


def _overrides(record, values: dict[str, str]):
    if not values:
        return record
    replacements = [
        DefaultAdoption(q_id=key, value=value, source="CLI_OVERRIDE", pending=False)
        for key, value in values.items()
    ]
    merged = {item.q_id: item for item in record.adopted_defaults}
    for item in replacements:
        merged[item.q_id] = item
    return record.model_copy(update={"adopted_defaults": [merged[key] for key in sorted(merged)]})


def main() -> int:
    parser = argparse.ArgumentParser(description="verify sandbox constraints and write VER evidence")
    parser.add_argument("--policy", default="sandbox/spec.json")
    parser.add_argument("--p4-05", choices=("on", "off"), default="on")
    parser.add_argument("--evidence-root", default=".evidence/sandbox-realscan")
    parser.add_argument("--o01", default=None)
    parser.add_argument("--o02", default=None)
    parser.add_argument("--o03", default=None)
    parser.add_argument("--o04", default=None)
    parser.add_argument("--o05", default=None)
    parser.add_argument("--o06", default=None)
    parser.add_argument("--q01", default=None)
    parser.add_argument("--q02", default=None)
    parser.add_argument("--q03", default=None)
    parser.add_argument("--q04", default=None)
    parser.add_argument("--q05", default=None)
    parser.add_argument("--q06", default=None)
    parser.add_argument("--q07", default=None)
    parser.add_argument("--q08", default=None)
    parser.add_argument("--q09", default=None)
    parser.add_argument("--q10", default=None)
    args = parser.parse_args()

    config = load_config().realscan
    config = config.model_copy(
        update={
            "policy_path": args.policy,
            "evidence_root": args.evidence_root,
            "p4_05_enabled": args.p4_05 == "on",
        }
    )
    pipeline = RealscanPipeline(config)
    try:
        capability = pipeline.ensure_ready()
    except ApiError as exc:
        print(json.dumps({"stage": "capability", "code": exc.code.value, "detail": exc.detail}, ensure_ascii=False))
        return 2

    policy = PolicyFile.load(Path(args.policy))
    image = ImageResolver(pipeline.transport, list(config.sandbox_images)).resolve(policy.image)
    evidence_root = Path(args.evidence_root)
    writer = EvidencePackWriter(evidence_root, scrubber=EvidenceScrubber())
    verification_id = writer.new_evidence_id("VER")

    work = evidence_root / ".work" / verification_id
    view = TargetViewBuilder().build_p4_fixture(work)
    verifier = ConstraintVerifier(
        policy=policy,
        capability=capability,
        transport=pipeline.transport,
        image=image,
        view_dir=Path(view.view_root),
        evidence_dir=evidence_root,
        path_mapper=_mapper(pipeline.transport),
        probe_timeout_seconds=float(config.probe_budget_seconds),
        p4_05_seconds=60.0,
    )
    before = pipeline.immutable_snapshot()
    try:
        record = verifier.verify(verification_id, run_p4_05=args.p4_05 == "on")
        pipeline.assert_immutable(before)
    except ApiError as exc:
        print(json.dumps({"stage": "verify", "code": exc.code.value, "detail": exc.detail}, ensure_ascii=False))
        return 3

    overrides = {f"O-{index:02d}": value for index in range(1, 7) if (value := getattr(args, f"o{index:02d}"))}
    overrides.update({f"Q-{index:02d}": value for index in range(1, 11) if (value := getattr(args, f"q{index:02d}"))})
    record = _overrides(record, overrides)

    prefix = _transport_prefix(pipeline.transport)
    commands = [
        prefix + "docker version --format '{{.Server.Version}}'",
        prefix + "docker info --format '{{.Driver}}|{{.CgroupVersion}}'",
        prefix + f"docker image inspect --format '{{{{.Id}}}}' {image.resolved_image or policy.image}",
    ]
    files = {
        "records/verification.json": json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2),
        "records/capability.json": json.dumps(capability.model_dump(mode="json"), ensure_ascii=False, indent=2),
        "runtime_facts.json": json.dumps(capability.runtime.model_dump(mode="json"), ensure_ascii=False, indent=2),
        "reuse_conditions.json": json.dumps(_reuse_conditions(pipeline.transport, capability, image), ensure_ascii=False, indent=2),
        "boundary.json": json.dumps({"tags": [BoundaryKind.REAL_CONTAINER.value]}, ensure_ascii=False, indent=2),
    }
    payload = EvidenceInput(
        commands=commands,
        runtime_facts=capability.runtime.model_dump(mode="json"),
        reuse_conditions=_reuse_conditions(pipeline.transport, capability, image),
        boundary_tags=[BoundaryKind.REAL_CONTAINER],
        verification_source=VerificationSource.REAL_EXECUTION,
        files=files,
        raw_output=json.dumps([check.model_dump(mode="json") for check in record.checks], ensure_ascii=False, indent=2),
    )
    try:
        pack = writer.write("VER", payload, evidence_id=verification_id)
    except ApiError as exc:
        print(json.dumps({"stage": "evidence", "code": exc.code.value, "detail": exc.detail}, ensure_ascii=False))
        return 4

    summary = {
        "verification_id": record.verification_id,
        "verdict": record.verdict.value,
        "exec_domain": record.exec_domain.value,
        "policy_keys": len(policy.isolation),
        "judgement_classes": len([name for name in JUDGEMENT_CLASSES if any(check.policy_key == name for check in record.checks)]),
        "checks": [{"id": check.check_id, "judgement": check.judgement.value} for check in record.checks],
        "evidence": str(evidence_root / pack.path),
        "sha256": pack.sha256,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if record.verdict is Judgement.PASS:
        return 0
    return 2 if record.verdict is Judgement.UNVERIFIED else 3


if __name__ == "__main__":
    raise SystemExit(main())