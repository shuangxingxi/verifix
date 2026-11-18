from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Sequence

from app.api.envelope import ApiError, ErrorCode
from app.realscan.boundary import default_adoptions
from app.realscan.models import (
    BoundaryKind,
    Detection,
    DynamicCheck,
    ScanRecord,
    ScanScope,
    ScanVerdict,
)
from app.realscan.pipeline import RealscanPipeline
from app.realscan.policy import ImageResolver, PolicyFile
from app.realscan.reconcile import ReconcileError, TruthReconciler
from app.realscan.rules import ADVISORIES
from app.realscan.scanner import scan_tree
from app.realscan.target import TargetLaunchError, TargetLauncher, TargetViewBuilder

FULL_CLASSES = ("C01", "C02", "C03", "C05")
FULL_COUNT = 15
DYNAMIC_CLASSES = ("C02", "C03")
STUB_COUNT = 10
STUB_REF = "scripts/m1_detect_acceptance.py:55"
CLOUD_TEXT = "云凭据缺失，未验证"


def build_scope(mode: str) -> ScanScope:
    if mode == "full":
        return ScanScope(defect_classes=list(FULL_CLASSES), item_count=FULL_COUNT, full_count=FULL_COUNT)
    return ScanScope(
        defect_classes=list(DYNAMIC_CLASSES),
        item_count=10,
        full_count=FULL_COUNT,
        uncovered_classes=["C01", "C05"],
    )


def scope_text(scope: ScanScope) -> str:
    if scope.item_count >= scope.full_count:
        return f"{scope.item_count}/{scope.full_count}"
    return f"{scope.item_count}/{scope.full_count}，未覆盖 " + "、".join(scope.uncovered_classes)


def to_detections(raw_detections: Sequence[dict]) -> list[Detection]:
    detections: list[Detection] = []
    for index, item in enumerate(raw_detections, start=1):
        line = int(item.get("line", 0) or 0)
        if line < 1:
            continue
        detections.append(
            Detection(
                detection_id=f"D-{index:02d}-{item.get('rule_id', 'UNKNOWN')}",
                file=str(item.get("file", "")),
                line=line,
                rule_id=str(item.get("rule_id", "")),
                defect_class=str(item.get("defect_class", "")),
                source_kind=BoundaryKind(str(item.get("source_kind", BoundaryKind.REAL_CONTAINER.value))),
                exec_location=str(item.get("exec_location", "CONTAINER")),
                snippet_masked=str(item.get("snippet_masked", "")),
                rule_basis=str(item.get("rule_basis", "")),
            )
        )
    return detections


def to_dynamic_checks(raw_checks: Sequence[dict], detections: Sequence[Detection]) -> list[DynamicCheck]:
    checks: list[DynamicCheck] = []
    for index, item in enumerate(raw_checks, start=1):
        line = int(item.get("line", 0) or 0)
        matched = next(
            (detection for detection in detections if detection.line == line and detection.file == str(item.get("file", ""))),
            None,
        )
        checks.append(
            DynamicCheck(
                check_id=f"DYN-{index:02d}",
                detection_id=matched.detection_id if matched is not None else f"DYN-{index:02d}",
                endpoint=str(item.get("endpoint", "")),
                method=str(item.get("method", "GET")),
                normal_digest=str(item.get("normal_digest", "")),
                injected_digest=str(item.get("injected_digest", "")),
                behavior_diff=bool(item.get("behavior_diff")),
                conclusion=str(item.get("conclusion", "STATIC_ONLY")),
                duration_ms=int(item.get("duration_ms", 0) or 0),
                retries=max(0, int(item.get("retries", 0) or 0)),
            )
        )
    return checks


def check_locations(view_root: Path, detections: Sequence[Detection]) -> list[str]:
    errors: list[str] = []
    cache: dict[str, list[str]] = {}
    for detection in detections:
        if detection.file not in cache:
            path = Path(view_root) / detection.file
            if not path.is_file():
                errors.append(f"{detection.detection_id}:missing_file")
                cache[detection.file] = []
                continue
            cache[detection.file] = path.read_text(encoding="utf-8", errors="replace").splitlines()
        lines = cache[detection.file]
        if not 1 <= detection.line <= len(lines) or not lines[detection.line - 1].strip():
            errors.append(f"{detection.detection_id}:offset")
    return errors


def compare_runs(first: ScanRecord, second: ScanRecord) -> list[str]:
    def key(detection: Detection):
        return (detection.file, detection.line, detection.rule_id, detection.defect_class)

    left = {key(item) for item in first.detections}
    right = {key(item) for item in second.detections}
    differences: list[str] = []
    for item in sorted(left - right):
        differences.append("removed:" + ":".join(str(part) for part in item))
    for item in sorted(right - left):
        differences.append("added:" + ":".join(str(part) for part in item))
    left_dynamic = {(item.endpoint, item.conclusion) for item in first.dynamic_checks}
    right_dynamic = {(item.endpoint, item.conclusion) for item in second.dynamic_checks}
    for item in sorted(left_dynamic - right_dynamic):
        differences.append("dynamic_removed:" + ":".join(item))
    for item in sorted(right_dynamic - left_dynamic):
        differences.append("dynamic_added:" + ":".join(item))
    return differences


class RealScanOrchestrator:
    def __init__(
        self,
        config: object,
        pipeline: RealscanPipeline | None = None,
        policy: PolicyFile | None = None,
        work_root: Path | None = None,
        view_builder: TargetViewBuilder | None = None,
        launcher_factory: Callable[..., object] | None = None,
        truth_path: Path | None = None,
    ) -> None:
        self.config = config
        self.pipeline = pipeline or RealscanPipeline(config)
        self.policy = policy or PolicyFile.load(Path(str(getattr(config, "policy_path", "sandbox/spec.json"))))
        evidence_root = Path(str(getattr(config, "evidence_root", ".evidence/sandbox-realscan")))
        self.work_root = Path(work_root) if work_root is not None else evidence_root / ".work"
        self.view_builder = view_builder or TargetViewBuilder()
        self.launcher_factory = launcher_factory
        self.truth_path = Path(truth_path) if truth_path is not None else Path(str(getattr(config, "target_root", "verifix-target"))) / "ground_truth.json"

    def run(
        self,
        scan_id: str,
        scope_mode: str | None = None,
        exec_mode: str = "CONTAINER",
        interrupted_after: int | None = None,
    ) -> ScanRecord:
        mode = str(scope_mode or getattr(self.config, "scan_scope", "full"))
        scope = build_scope(mode)
        if str(exec_mode).upper() == "HOST":
            return self._run_host(scan_id, scope, interrupted_after)
        self.pipeline.ensure_ready()
        image = self._target_image()
        view = self.view_builder.build(Path(str(self.config.target_root)), self.work_root)
        payload = self._payload(scope)
        launcher = self._make_launcher(view, image)
        try:
            runtime = launcher.launch(
                scan_id,
                payload,
                timeout_seconds=float(getattr(self.config, "scan_budget_seconds", 180)),
            )
        except TargetLaunchError as exc:
            return self._blank_record(scan_id, scope, reason=exc.reason, sandbox_scope=True)

        detections = to_detections(runtime.detections)
        dynamic = to_dynamic_checks(runtime.dynamic_checks, detections)
        locate_errors = check_locations(Path(view.view_root), detections)
        if interrupted_after is not None:
            completed = max(0, min(int(interrupted_after), len(detections)))
            detections = detections[:completed]
            dynamic = dynamic[: min(len(dynamic), completed)]
            return self._record(
                scan_id,
                scope,
                detections,
                dynamic,
                view,
                runtime,
                sandbox_scope=True,
                verdict=ScanVerdict.UNVERIFIED,
                missing=["interrupted"],
                completed=completed,
                unverified=max(0, FULL_COUNT - completed),
                interrupted_at=completed,
            )

        missing: list[str] = []
        if not runtime.health_ok:
            missing.append("target_responded")
        expected_dynamic = 10 if mode == "full" else 10
        if len(dynamic) < expected_dynamic or not all(item.behavior_diff for item in dynamic):
            missing.append("behavior_diff_reproducible")
        if not (runtime.truth_reads == 0):
            missing.append("isolation_effective")
        if not (runtime.stdout.strip() and (detections or dynamic)):
            missing.append("evidence_replayable")
        if locate_errors:
            missing.append("location_alignment")
        if scope.item_count < scope.full_count and any(
            item.defect_class in scope.defect_classes for item in detections
        ) is False:
            missing.append("scope_coverage")
        verdict = ScanVerdict.ESTABLISHED if not missing else ScanVerdict.NOT_ESTABLISHED
        return self._record(
            scan_id,
            scope,
            detections,
            dynamic,
            view,
            runtime,
            sandbox_scope=True,
            verdict=verdict,
            missing=missing,
            completed=len(detections),
            unverified=max(0, FULL_COUNT - len(detections)),
        )

    def _payload(self, scope: ScanScope) -> dict[str, object]:
        from app.realscan.worker import worker_payload

        advisories = [asdict(item) for item in ADVISORIES]
        return worker_payload(
            listen_port=int(getattr(self.config, "listen_port", 0)),
            port_retries=int(getattr(self.config, "port_retries", 3)),
            request_timeout=float(getattr(self.config, "request_timeout_seconds", 5)),
            request_retries=int(getattr(self.config, "request_retries", 3)),
            advisories=advisories,
            scope_classes=scope.defect_classes,
        )

    def _target_image(self):
        resolver = ImageResolver(self.pipeline.transport, list(self.config.target_images))
        for candidate in self.config.target_images:
            resolution = resolver.inspect(candidate)
            if resolution.image_id:
                return resolution
        raise ApiError(ErrorCode.REALSCAN_NOT_ESTABLISHED, "target image unavailable")

    def _make_launcher(self, view, image):
        if self.launcher_factory is not None:
            return self.launcher_factory(view, image)
        from app.realscan.runtime import wsl_path

        mapper = wsl_path if getattr(self.pipeline.transport, "name", "") == "wsl" else None
        return TargetLauncher(self.pipeline.transport, view, image, self.policy, path_mapper=mapper)

    def _record(
        self,
        scan_id: str,
        scope: ScanScope,
        detections: list[Detection],
        dynamic: list[DynamicCheck],
        view,
        runtime,
        *,
        sandbox_scope: bool,
        verdict: ScanVerdict,
        missing: list[str],
        completed: int = 0,
        unverified: int = 0,
        interrupted_at: int | None = None,
    ) -> ScanRecord:
        summary = {
            "REAL_CONTAINER": (len(detections) + len(dynamic)) if sandbox_scope else 0,
            "REAL_LOCAL": 0 if sandbox_scope else (len(detections) + len(dynamic)),
            "RECORDED_STUB": STUB_COUNT,
            "CLOUD_CREDENTIAL_MISSING": 1,
        }
        return ScanRecord(
            scan_id=scan_id,
            target=str(Path(str(self.config.target_root)).name),
            target_version="1.0.0",
            target_view_digest=view.view_digest,
            listen_port=int(getattr(runtime, "listen_port", 0) or 0),
            port_source=str(getattr(runtime, "port_source", "DYNAMIC")),
            network_mode="NONE_LOOPBACK" if sandbox_scope else "HOST",
            sandbox_scope=sandbox_scope,
            scope=scope,
            detections=detections,
            dynamic_checks=dynamic,
            scan_verdict=verdict,
            verdict_missing=list(missing),
            boundary_summary=summary,
            scan_phase_truth_reads=0,
            stub_count=STUB_COUNT,
            cloud_section=CLOUD_TEXT,
            completed_count=completed,
            unverified_count=unverified,
            interrupted_at=interrupted_at,
            evidence_ref=f"{scan_id}/manifest.json",
            adopted_defaults=default_adoptions(),
        )

    def _blank_record(self, scan_id: str, scope: ScanScope, reason: str, sandbox_scope: bool) -> ScanRecord:
        view = self.view_builder.build(Path(str(self.config.target_root)), self.work_root)

        class _Runtime:
            listen_port = 0
            port_source = "DYNAMIC"

        return self._record(
            scan_id,
            scope,
            [],
            [],
            view,
            _Runtime(),
            sandbox_scope=sandbox_scope,
            verdict=ScanVerdict.UNVERIFIED,
            missing=[reason],
        )

    def _run_host(self, scan_id: str, scope: ScanScope, interrupted_after: int | None) -> ScanRecord:
        view = self.view_builder.build(Path(str(self.config.target_root)), self.work_root)
        raw = scan_tree(Path(view.view_root), ADVISORIES, exec_location="HOST")
        detections = to_detections(raw)
        if interrupted_after is not None:
            completed = max(0, min(int(interrupted_after), len(detections)))
            detections = detections[:completed]

        class _Runtime:
            listen_port = 0
            port_source = "HOST"

        return self._record(
            scan_id,
            scope,
            detections,
            [],
            view,
            _Runtime(),
            sandbox_scope=False,
            verdict=ScanVerdict.NOT_ESTABLISHED,
            missing=["sandbox_scope"],
        )

    def reconcile(self, record: ScanRecord) -> object:
        try:
            return TruthReconciler(self.truth_path).reconcile(record.scan_id, record.detections, record.target_version)
        except ReconcileError:
            raise ApiError(ErrorCode.REALSCAN_NOT_ESTABLISHED, "reconcile failed")