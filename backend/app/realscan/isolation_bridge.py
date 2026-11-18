from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from app.api.envelope import ApiError, ErrorCode
from app.eval.isolation import EXEC, AccessAuditLog, AuditArchiveQuery
from app.eval.models import AccessAuditRecord, utc_now
from app.realscan.models import DenialKind, IsolationBridgeRecord, IsolationProbeResult
from app.realscan.policy import PolicyFile, RunSpecBuilder, sanitize_name
from app.realscan.runtime import RuntimeTransport, RuntimeUnavailableError
from app.runtime.exec_domain import ExecDomain, FailureKind

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_POLICY = ROOT / "sandbox" / "spec.json"
DENIED = "拒绝"
SUCCEEDED = "成功"
CONTROL_ACTOR = "control"

ISO_PROBE = r'''
import json
import os

CASES = "/cases"
DENY_TARGET = "/cases/../expected/EVAL-0001.answer.json"


def probe(name, action):
    try:
        action()
        return {"probe": name, "result": "READABLE", "denial_kind": "UNKNOWN"}
    except FileNotFoundError:
        return {"probe": name, "result": "DENIED", "denial_kind": "PATH_NOT_EXIST"}
    except PermissionError:
        return {"probe": name, "result": "DENIED", "denial_kind": "PERMISSION_DENIED"}
    except OSError as exc:
        return {"probe": name, "result": "ERROR", "denial_kind": "UNKNOWN", "detail": type(exc).__name__}


def _read(path):
    with open(path, "rb") as handle:
        handle.read(1)


results = []
results.append(probe("enumerate", lambda: os.listdir("/cases/../expected")))
results.append(probe("open", lambda: _read(DENY_TARGET)))
results.append(probe("relative", lambda: _read(os.path.relpath("../expected/EVAL-0001.answer.json", CASES))))
results.append(probe("traversal", lambda: _read(os.path.join(CASES, "..", "expected", "EVAL-0001.answer.json"))))
results.append(probe("symlink", lambda: _read(os.path.join(CASES, "expected-link"))))
results.append(probe("decoy_expected", lambda: _read("/decoy-expected/secret.txt")))
results.append(probe("decoy_shadow", lambda: _read("/etc/shadow")))

positive = False
try:
    _read(os.path.join(CASES, "EVAL-0001.json"))
    positive = True
except OSError:
    positive = False

print(json.dumps({"probes": results, "positive_control": positive, "uid": os.getuid(), "gid": os.getgid()}))
'''

REQUIRED_PROBES = ("enumerate", "open", "relative", "traversal", "symlink")
DECOY_PROBES = ("decoy_expected", "decoy_shadow")


def _parse_payload(stdout: str) -> dict | None:
    for line in reversed(stdout.splitlines()):
        text = line.strip()
        if text.startswith("{") and text.endswith("}"):
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    return None


class ContainerIsolationVerifier:
    def __init__(
        self,
        transport: RuntimeTransport,
        cases_dir: Path,
        work_root: Path,
        audit: AccessAuditLog | None = None,
        policy: PolicyFile | None = None,
        image=None,
        path_mapper=None,
        probe_timeout_seconds: float = 60.0,
    ) -> None:
        self.transport = transport
        self.cases_dir = Path(cases_dir)
        self.work_root = Path(work_root)
        self.archive_path = self.work_root / "audit" / "access.jsonl"
        self.audit = audit or AccessAuditLog(self.archive_path)
        self.policy = policy or PolicyFile.load(DEFAULT_POLICY)
        self.image = image
        self.path_mapper = path_mapper
        self.probe_timeout_seconds = probe_timeout_seconds

    def verify(self, iso_id: str) -> IsolationBridgeRecord:
        result = self._run_probe(iso_id)
        payload = _parse_payload(result.stdout)
        if payload is None:
            self._audit(iso_id, "probe", "runtime", DENIED, "PROBE_INVALID")
            raise ApiError(ErrorCode.EVAL_ISOLATION_UNMET, "探针失效：隔离探针无原始输出")
        raw_probes = payload.get("probes") or []
        probes: list[IsolationProbeResult] = []
        violations = 0
        for item in raw_probes:
            name = str(item.get("probe", ""))
            outcome = str(item.get("result", "ERROR"))
            denial = DenialKind(str(item.get("denial_kind", "UNKNOWN")))
            probes.append(IsolationProbeResult(probe=name, result=outcome, denial_kind=denial))
            succeeded = outcome == "READABLE"
            self._audit(
                iso_id,
                "exec",
                name,
                SUCCEEDED if succeeded else DENIED,
                denial.value if not succeeded else "readable",
            )
            if name in REQUIRED_PROBES and succeeded:
                violations += 1
        positive = bool(payload.get("positive_control"))
        self._audit(iso_id, CONTROL_ACTOR, "positive_control", SUCCEEDED if positive else DENIED, "control")
        uid = int(payload.get("uid", -1))
        gid = int(payload.get("gid", -1))
        exec_domain = ExecDomain.CONTAINER_EXEC if uid not in (0, -1) else ExecDomain.RUNTIME_ROOT
        denial_kinds = [probe.denial_kind for probe in probes if probe.probe in REQUIRED_PROBES]
        denial_kind = self._dominant(denial_kinds)
        has_permission = any(
            probe.denial_kind is DenialKind.PERMISSION_DENIED for probe in probes if probe.probe in DECOY_PROBES
        )
        decoy_ok = has_permission
        exec_success = AuditArchiveQuery(self.archive_path).exec_success_count()
        ok = violations == 0 and positive and decoy_ok and exec_success == 0
        failure_kind = None if ok else FailureKind.ISOLATION_DEFECT
        if not positive:
            failure_kind = FailureKind.PROBE_INVALID
        record = IsolationBridgeRecord(
            iso_id=iso_id,
            exec_identity=f"uid={uid},gid={gid}",
            exec_domain=exec_domain,
            visible_roots=["/cases"],
            probes=probes,
            denial_kind=denial_kind,
            exec_success_count=exec_success,
            enforcement_mode="MANDATORY_SELF_CHECK",
            publishable=bool(ok and exec_domain is ExecDomain.CONTAINER_EXEC),
            failure_kind=failure_kind,
            audit_ref=str(self.archive_path) + "#run_ref=" + iso_id,
        )
        if not ok:
            reasons = []
            if violations:
                reasons.append("答案目录可读：" + str(violations))
            if not positive:
                reasons.append("正例不可读")
            if not decoy_ok:
                reasons.append("权限拒绝分支不可观测")
            raise ApiError(ErrorCode.EVAL_ISOLATION_UNMET, "隔离缺陷（CONTAINER_EXEC）：" + ",".join(reasons))
        return record

    def _run_probe(self, iso_id: str):
        effective = replace(self.policy, image=self.image.resolved_image or self.policy.image) if self.image is not None else self.policy
        spec = RunSpecBuilder(effective, sanitize_name(f"vf-iso-{iso_id}"), self.path_mapper).build_run(
            self.cases_dir,
            ISO_PROBE,
            workdir="/cases",
            mount_target="/cases",
        )
        try:
            return self.transport.run(spec.argv, self.probe_timeout_seconds)
        except RuntimeUnavailableError as exc:
            self._audit(iso_id, "runtime", "container", DENIED, "RUNTIME_UNAVAILABLE")
            raise ApiError(
                ErrorCode.EVAL_ISOLATION_UNMET,
                "运行时不可用，评测未启动：" + str(exc.reason),
            ) from exc

    def _audit(self, iso_id: str, actor: str, target: str, result: str, reason: str) -> None:
        self.audit.record(
            AccessAuditRecord(
                occurred_at=utc_now(),
                actor=actor,
                target_path=str(target),
                operation="隔离桥接探针",
                result=result,
                reason=reason,
                run_ref=iso_id,
            )
        )

    @staticmethod
    def _dominant(kinds: list[DenialKind]) -> DenialKind:
        if not kinds:
            return DenialKind.UNKNOWN
        denied = sum(1 for kind in kinds if kind is DenialKind.PERMISSION_DENIED)
        missing = sum(1 for kind in kinds if kind is DenialKind.PATH_NOT_EXIST)
        if denied == 0 and missing == 0:
            return DenialKind.UNKNOWN
        return DenialKind.PERMISSION_DENIED if denied >= missing else DenialKind.PATH_NOT_EXIST