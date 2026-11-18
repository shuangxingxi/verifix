from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.adapters.types import UpstreamUnavailable
from app.domain.enums import GateOutcome
from app.domain.models import GateResult, Proof

COVERAGE_TOLERANCE_PP = 0.5


@dataclass(frozen=True)
class GateParams:
    branch: str
    issue_id: str
    run_key: str


@dataclass(frozen=True)
class PipelineRunRef:
    run_id: str


@dataclass(frozen=True)
class GateStageResult:
    name: str
    success: bool
    coverage_delta_pp: float = 0.0
    new_alerts: int = 0
    evidence_ref: str = ""


@dataclass(frozen=True)
class GateRunSnapshot:
    run_id: str
    terminal: bool
    stages: dict[str, GateStageResult]
    elapsed_seconds: float = 0.0


class CodeArtsPipelinePort(Protocol):
    def trigger_gate(self, pipeline_id: str, params: GateParams) -> PipelineRunRef: ...

    def poll_gate_result(self, run: PipelineRunRef) -> GateRunSnapshot: ...


@dataclass
class RecordedPipelineClient:
    stages: dict[str, GateStageResult] = field(default_factory=dict)
    terminal: bool = True
    fail_trigger: bool = False
    timeout: bool = False
    calls: int = 0

    @staticmethod
    def all_passed(coverage_delta_pp: float = 0.0, new_alerts: int = 0) -> "RecordedPipelineClient":
        return RecordedPipelineClient(
            stages={
                "proof": GateStageResult("proof", True, evidence_ref="pipeline/proof"),
                "regression": GateStageResult("regression", True, coverage_delta_pp=coverage_delta_pp,
                                              evidence_ref="pipeline/regression"),
                "rescan": GateStageResult("rescan", True, new_alerts=new_alerts, evidence_ref="pipeline/rescan"),
            }
        )

    def trigger_gate(self, pipeline_id: str, params: GateParams) -> PipelineRunRef:
        self.calls += 1
        if self.fail_trigger:
            raise UpstreamUnavailable("pipeline", f"trigger failed for {pipeline_id}")
        return PipelineRunRef(run_id=f"{pipeline_id}:{params.run_key}")

    def poll_gate_result(self, run: PipelineRunRef) -> GateRunSnapshot:
        if self.timeout:
            raise UpstreamUnavailable("pipeline", "readback timeout")
        return GateRunSnapshot(run_id=run.run_id, terminal=self.terminal, stages=dict(self.stages),
                               elapsed_seconds=1.0)


class GateJudger:
    def judge(
        self,
        patch_id: str,
        proof: Proof,
        snapshot: GateRunSnapshot,
        local_regression_ok: bool,
    ) -> GateResult:
        proof_stage = snapshot.stages.get("proof")
        regression_stage = snapshot.stages.get("regression")
        rescan_stage = snapshot.stages.get("rescan")

        red_green = (
            proof.pre_patch_result.value == "FAIL"
            and proof_stage is not None
            and proof_stage.success
        )
        coverage = regression_stage.coverage_delta_pp if regression_stage else 0.0
        regression_ok = (
            local_regression_ok
            and regression_stage is not None
            and regression_stage.success
            and coverage >= -COVERAGE_TOLERANCE_PP
        )
        new_alerts = rescan_stage.new_alerts if rescan_stage else 0
        rescan_ok = rescan_stage is not None and rescan_stage.success and new_alerts == 0

        all_ok = red_green and regression_ok and rescan_ok
        return GateResult(
            gate_result_id=f"G-{patch_id}",
            patch_id=patch_id,
            gate_run_ref=snapshot.run_id,
            red_green_paired=red_green,
            regression_zero_fail=regression_ok,
            coverage_delta_pp=coverage,
            rescan_new_alerts=new_alerts,
            outcome=GateOutcome.PASSED if all_ok else GateOutcome.FAILED,
        )