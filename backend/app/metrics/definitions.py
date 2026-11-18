from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from app.domain.enums import MetricChannel, MetricId
from app.metrics.calculator import SPECS

V1 = "v1"
V2 = "v2"
V1_EFFECTIVE_AT = datetime(2025, 1, 1, tzinfo=timezone.utc)
V2_EFFECTIVE_AT = datetime(2026, 12, 1, tzinfo=timezone.utc)


class MetricUnit(str, Enum):
    RATIO = "RATIO"
    MINUTES = "MINUTES"
    HOURS = "HOURS"


class MetricDirection(str, Enum):
    HIGHER_IS_BETTER = "HIGHER_IS_BETTER"
    LOWER_IS_BETTER = "LOWER_IS_BETTER"


@dataclass(frozen=True)
class MetricDefinition:
    metric_id: MetricId
    name: str
    numerator_spec: str
    denominator_spec: str
    unit: MetricUnit
    channel: MetricChannel
    source_bindings: tuple[str, ...]
    definition_version: str
    effective_at: datetime
    preliminary_target: float = 0.0
    finals_target: float | None = None
    direction: MetricDirection = MetricDirection.HIGHER_IS_BETTER
    coverage_delta_tolerance_pp: float = 0.5
    note: str = ""

    def to_record(self) -> dict:
        return {
            "metric_id": self.metric_id,
            "name": self.name,
            "numerator_spec": self.numerator_spec,
            "denominator_spec": self.denominator_spec,
            "unit": self.unit.value,
            "channel": self.channel,
            "source_bindings": list(self.source_bindings),
            "definition_version": self.definition_version,
            "effective_at": self.effective_at,
            "preliminary_target": self.preliminary_target,
            "finals_target": self.finals_target,
            "direction": self.direction.value,
            "coverage_delta_tolerance_pp": self.coverage_delta_tolerance_pp,
            "note": self.note,
        }


V2_BINDINGS: dict[MetricId, tuple[MetricId, str, str, MetricUnit, MetricChannel, tuple[str, ...]]] = {
    MetricId.M1: (
        MetricId.M1,
        "正例+边界样本中被检出的样本数 ÷ 正例+边界样本总数",
        "评测集预期答案 + 已裁决评测运行结果",
        MetricUnit.RATIO,
        MetricChannel.EVAL,
        ("eval/cases", "eval/expected", "eval runs ADJUDICATED"),
    ),
    MetricId.M2: (
        MetricId.M2,
        "靶场已知漏洞检出数 ÷ 已知漏洞总数",
        "评测运行结果中的显式漏洞检出字段",
        MetricUnit.RATIO,
        MetricChannel.EVAL,
        ("eval runs COMPLETED",),
    ),
    MetricId.M3: (
        MetricId.M3,
        "可达性判定与人工结论一致的样本数 ÷ 有标注样本数",
        "verdict + 评测集人工结论",
        MetricUnit.RATIO,
        MetricChannel.EVAL,
        ("eval runs COMPLETED", "Verdict"),
    ),
    MetricId.M4: (
        MetricId.M4,
        "最新一次复现尝试为 PROVEN 且补丁前为 FAIL 的 Issue 数",
        "有效可达且已进入/完成复现的 Issue 数",
        MetricUnit.RATIO,
        MetricChannel.MAIN,
        ("ReproductionAttempt", "Proof", "Verdict", "Alert.observed_at"),
    ),
    MetricId.M5: (
        MetricId.M5,
        "首次补丁尝试门禁 PASSED 且处置为 L0/L1 的 Issue 数",
        "存在首次补丁尝试（attempt_index=1）的 Issue 数",
        MetricUnit.RATIO,
        MetricChannel.MAIN,
        ("PatchAttempt", "GateAttempt", "GateResult", "DispositionHistoryEntry"),
    ),
    MetricId.M6: (
        MetricId.M6,
        "门禁结论中回归失败、复扫新增告警或覆盖率下降超容忍的补丁数",
        "存在门禁结论（PASSED/FAILED 且证据齐全）的补丁数",
        MetricUnit.RATIO,
        MetricChannel.MAIN,
        ("GateResult", "GateAttempt"),
    ),
    MetricId.M7: (
        MetricId.M7,
        "各 Issue PR 就绪时刻与告警首次观测时刻之差的分钟数之和",
        "完成 L0/L1 且两端时间戳齐备的 Issue 数",
        MetricUnit.MINUTES,
        MetricChannel.MAIN,
        ("Alert.observed_at", "Disposition.ready_at"),
    ),
    MetricId.M8: (
        MetricId.M8,
        "处置为 L0/L1 且门禁 PASSED 的 Issue 数",
        "主流程窗口内全部 Issue 数（含未处置与处置中）",
        MetricUnit.RATIO,
        MetricChannel.MAIN,
        ("Disposition", "GateAttempt", "GateResult"),
    ),
    MetricId.M9: (
        MetricId.M9,
        "最近一次健康采样记录的连续运行秒数 ÷ 3600",
        "1（连续小时数指标）",
        MetricUnit.HOURS,
        MetricChannel.MAIN,
        ("runtime self-run samples",),
    ),
}

TARGETS: dict[MetricId, tuple[float, float | None, MetricDirection]] = {
    MetricId.M1: (0.50, None, MetricDirection.HIGHER_IS_BETTER),
    MetricId.M2: (0.0, None, MetricDirection.HIGHER_IS_BETTER),
    MetricId.M3: (0.0, None, MetricDirection.HIGHER_IS_BETTER),
    MetricId.M4: (0.60, None, MetricDirection.HIGHER_IS_BETTER),
    MetricId.M5: (0.45, None, MetricDirection.HIGHER_IS_BETTER),
    MetricId.M6: (0.0, None, MetricDirection.LOWER_IS_BETTER),
    MetricId.M7: (0.0, None, MetricDirection.LOWER_IS_BETTER),
    MetricId.M8: (0.0, None, MetricDirection.HIGHER_IS_BETTER),
    MetricId.M9: (24.0, None, MetricDirection.HIGHER_IS_BETTER),
}


def _v1_definitions() -> list[MetricDefinition]:
    items: list[MetricDefinition] = []
    for metric_id, (name, definition, source) in SPECS.items():
        items.append(
            MetricDefinition(
                metric_id=metric_id,
                name=name,
                numerator_spec=definition.split(" ÷ ")[0],
                denominator_spec=definition.split(" ÷ ")[-1],
                unit=MetricUnit.HOURS if metric_id is MetricId.M9 else (
                    MetricUnit.MINUTES if metric_id is MetricId.M7 else MetricUnit.RATIO
                ),
                channel=MetricChannel.EVAL if metric_id in {MetricId.M1, MetricId.M2, MetricId.M3} else MetricChannel.MAIN,
                source_bindings=(source,),
                definition_version=V1,
                effective_at=V1_EFFECTIVE_AT,
                direction=TARGETS[metric_id][2],
                note="v1 归档：保留历史定义与采集源描述，不再作为新复算口径",
            )
        )
    return items


def _v2_definitions() -> list[MetricDefinition]:
    items: list[MetricDefinition] = []
    for metric_id in MetricId:
        _, numerator_spec, denominator_spec, unit, channel, bindings = V2_BINDINGS[metric_id]
        preliminary, finals, direction = TARGETS[metric_id]
        note = ""
        if metric_id is MetricId.M2:
            note = "口径待评测通道对齐：评测运行未提供显式漏洞检出字段时不本地推导"
        if metric_id is MetricId.M6:
            note = "采集源由 v1 的 Pipeline 日志更正为 GateResult/GateAttempt；覆盖率容忍默认 0.5pp"
        items.append(
            MetricDefinition(
                metric_id=metric_id,
                name=SPECS[metric_id][0],
                numerator_spec=numerator_spec,
                denominator_spec=denominator_spec,
                unit=unit,
                channel=channel,
                source_bindings=bindings,
                definition_version=V2,
                effective_at=V2_EFFECTIVE_AT,
                preliminary_target=preliminary,
                finals_target=finals,
                direction=direction,
                note=note,
            )
        )
    return items


def default_definitions() -> list[MetricDefinition]:
    return _v1_definitions() + _v2_definitions()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class DefinitionRegistry:
    def __init__(self, definitions: list[MetricDefinition] | None = None) -> None:
        self._definitions: list[MetricDefinition] = list(definitions if definitions is not None else default_definitions())

    def register(self, definition: MetricDefinition) -> MetricDefinition:
        self._definitions.append(definition)
        return definition

    def definitions(self) -> list[MetricDefinition]:
        return list(self._definitions)

    def effective(self, metric_id: MetricId, at: datetime) -> MetricDefinition | None:
        point = _as_utc(at)
        candidates = [
            item
            for item in self._definitions
            if item.metric_id is metric_id and _as_utc(item.effective_at) <= point
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: (_as_utc(item.effective_at), item.definition_version))

    def all_effective(self, at: datetime) -> dict[MetricId, MetricDefinition]:
        result: dict[MetricId, MetricDefinition] = {}
        for metric_id in MetricId:
            found = self.effective(metric_id, at)
            if found is not None:
                result[metric_id] = found
        return result

    def missing(self, at: datetime) -> set[MetricId]:
        return {metric_id for metric_id in MetricId if self.effective(metric_id, at) is None}

    def by_version(self, metric_id: MetricId, version: str) -> MetricDefinition | None:
        for item in self._definitions:
            if item.metric_id is metric_id and item.definition_version == version:
                return item
        return None