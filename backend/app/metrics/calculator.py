from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.domain.enums import (
    DispositionLevel,
    IssueStatus,
    MetricId,
    ProofResult,
    StageTier,
    VerdictConclusion,
)
from app.domain.models import Metric
from app.metrics.isolation import ChannelResolver

DEFINITION_VERSION = "v1"
WINDOW = "2026-12"
EVAL_PREFIX = "eval-"

SPECS: dict[MetricId, tuple[str, str, str]] = {
    MetricId.M1: ("有效告警率", "人工确认有价值的告警 ÷ 总告警", "评测集 ground truth"),
    MetricId.M2: ("漏洞检出率", "靶场已知洞检出数 ÷ 已知洞总数", "评测结果"),
    MetricId.M3: ("可达性判定准确率", "判定与人工结论一致的比例", "verdict + 评测集"),
    MetricId.M4: ("复现成功率", "能生成必红测试的 issue 占比", "proof.pre_patch_result"),
    MetricId.M5: ("一次修复通过率", "补丁与测试一次被接受的比例", "disposition"),
    MetricId.M6: ("回归破坏率", "补丁引入的新失败占比", "Pipeline 日志"),
    MetricId.M7: ("MTTR", "从告警到 PR 就绪的时长", "event 首末时间戳"),
    MetricId.M8: ("自动处置率", "L0+L1 ÷ 总 issue", "disposition"),
    MetricId.M9: ("连续自运行", "无人干预连续时长（小时）", "看板运行时计数器"),
}


def _metric(metric_id: MetricId, value: float | None, source: str, computable: bool) -> Metric:
    return Metric(
        metric_id=metric_id,
        stage_tier=StageTier.PRELIMINARY,
        window=WINDOW,
        definition_version=DEFINITION_VERSION,
        value=value,
        source_ref=source,
        computed_at=datetime.now(timezone.utc),
        computable=computable,
    )


class MetricCalculator:
    def __init__(self, store, tracker=None):
        self.store = store
        self.tracker = tracker

    def _in_scope_issues(self) -> list:
        resolver = ChannelResolver()
        return [
            issue
            for issue in self.store.issues.values()
            if issue.in_scope and resolver.resolve(issue).channel.value == "MAIN"
        ]

    def calculate(self, eval_results: list[dict] | None = None) -> list[Metric]:
        """Legacy 兼容入口：固定 v1 定义与 2026-12 窗口，保留旧行为。

        Deprecated: 新的主流程指标复算请使用 ``app.metrics.service.RecalcService`` 与
        ``app.metrics.report.MetricReportService``；本方法不再作为对外指标口径来源。
        """
        metrics: list[Metric] = []
        issues = self._in_scope_issues()
        verdicts = {issue.issue_id: self.store.effective(issue.issue_id) for issue in issues}
        proofs = [
            proof
            for proof in self.store.proofs.values()
            if not self.store.get(proof.issue_id).code_version.startswith(EVAL_PREFIX)
        ]
        dispositions = [
            disposition
            for item, disposition in self.store.dispositions.items()
            if not self.store.get(item).code_version.startswith(EVAL_PREFIX)
        ]
        reachable = [
            issue for issue in issues if issue.status.value.startswith("REPRO") or issue.status.value.startswith("PROVEN")
            or issue.status.value.startswith("PATCH") or issue.status.value.startswith("AUDIT")
            or issue.status.value.startswith("GATING") or issue.status.value.startswith("DISPOSED")
        ]

        if eval_results:
            positive = [row for row in eval_results if row["category"] in {"POSITIVE", "BOUNDARY"}]
            detected = [row for row in positive if row.get("detected")]
            m1_value = (len(detected) / len(positive)) if positive else None
            metrics.append(_metric(MetricId.M1, m1_value, "评测集 ground truth", m1_value is not None))

            labelled = [row for row in eval_results if row.get("verdict") is not None]
            agrees = [row for row in labelled if row.get("verdict_agrees")]
            m3_value = (len(agrees) / len(labelled)) if labelled else None
            metrics.append(_metric(MetricId.M3, m3_value, "verdict + 评测集", m3_value is not None))
        else:
            metrics.append(_metric(MetricId.M1, None, "缺人工标注表/评测结果", False))
            metrics.append(_metric(MetricId.M3, None, "缺人工标注表/评测结果", False))

        if eval_results:
            positive = [row for row in eval_results if row["category"] == "POSITIVE"]
            reachable_rows = [row for row in positive if row.get("verdict") == VerdictConclusion.REACHABLE.value]
            m2_value = (len(reachable_rows) / len(positive)) if positive else None
            metrics.append(_metric(MetricId.M2, m2_value, "评测结果", m2_value is not None))
        else:
            metrics.append(_metric(MetricId.M2, None, "缺评测结果", False))

        red = [proof for proof in proofs if proof.pre_patch_result is ProofResult.FAIL]
        m4_value = (len(red) / len(reachable)) if reachable else None
        metrics.append(_metric(MetricId.M4, m4_value, "proof.pre_patch_result", m4_value is not None))

        attempts = len(self.store.patches)
        accepted = [
            disposition
            for disposition in dispositions
            if disposition.level in {DispositionLevel.L0, DispositionLevel.L1}
        ]
        m5_value = (len(accepted) / attempts) if attempts else None
        metrics.append(_metric(MetricId.M5, m5_value, "disposition ÷ patch", m5_value is not None))

        metrics.append(_metric(MetricId.M6, None, "缺 Pipeline 日志采集源", False))

        durations = []
        for run in self.store.runs.values():
            events = self.store.list_for_run(run.run_id)
            if len(events) >= 2:
                durations.append((events[-1].occurred_at - events[0].occurred_at).total_seconds() / 60.0)
        m7_value = (sum(durations) / len(durations)) if durations else None
        metrics.append(_metric(MetricId.M7, m7_value, "event 首末时间戳", m7_value is not None))

        total = len(issues)
        m8_value = (len(accepted) / total) if total else None
        metrics.append(_metric(MetricId.M8, m8_value, "disposition ÷ issue", m8_value is not None))

        hours = self.tracker.continuous_hours() if self.tracker is not None else None
        metrics.append(_metric(MetricId.M9, hours, "看板运行时计数器", hours is not None))

        for metric in metrics:
            self.store.add_metric(metric)
        return metrics

    @staticmethod
    def describe(metric_id: MetricId) -> dict:
        name, definition, source = SPECS[metric_id]
        return {"metric_id": metric_id.value, "name": name, "definition": definition, "source": source}