from __future__ import annotations

from datetime import datetime

from app.domain.enums import MetricId
from app.metrics.collectors.main_flow import CollectedEvidence
from app.metrics.rules.base import RuleExclusion, RuleResult


class _EvalMergeBase:
    metric_id: MetricId

    def evaluate(self, evidence: CollectedEvidence, definition, now: datetime) -> RuleResult:
        conclusion = evidence.eval_conclusion
        result = RuleResult(
            metric_id=self.metric_id,
            channel_excluded_count=evidence.channel_excluded_count,
            source_ref="已完成评测运行结果",
        )
        if conclusion is None:
            result.evidence_present = False
            result.details["missing"] = "缺少已完成且全量跑完的评测运行"
            return result.validate()
        if not conclusion.get("digest_match", True) and not conclusion.get("legacy_conclusion"):
            result.excluded_count += 1
            result.exclusions.append(
                RuleExclusion("evaluation", "EVIDENCE_INCONSISTENT", "评测集摘要与装载记录不一致", self.metric_id)
            )
            return result.validate()
        result.details["eval_run_id"] = conclusion.get("eval_run_id", "")
        result.details["set_digest"] = conclusion.get("set_digest", "")
        result.details["category_stats"] = conclusion.get("category_stats", {})
        if conclusion.get("legacy_conclusion"):
            result.details["legacy_conclusion"] = True
            result.details["legacy_notice"] = "历史运行，需重新裁决后方可作为发布依据"
        return self._fill(result, conclusion)

    def _fill(self, result: RuleResult, conclusion: dict) -> RuleResult:
        raise NotImplementedError


class M1Rule(_EvalMergeBase):
    metric_id = MetricId.M1

    def _fill(self, result: RuleResult, conclusion: dict) -> RuleResult:
        stats = conclusion.get("m1") or {}
        result.covered_count = int(stats.get("total", 0))
        result.numerator = int(stats.get("detected", 0))
        return result.validate()


class M2Rule(_EvalMergeBase):
    metric_id = MetricId.M2

    def _fill(self, result: RuleResult, conclusion: dict) -> RuleResult:
        stats = conclusion.get("m2")
        if stats is None:
            result.evidence_present = False
            result.details["missing"] = "评测运行未提供显式漏洞检出字段"
            return result.validate()
        result.covered_count = int(stats.get("total", 0))
        result.numerator = int(stats.get("detected", 0))
        return result.validate()


class M3Rule(_EvalMergeBase):
    metric_id = MetricId.M3

    def _fill(self, result: RuleResult, conclusion: dict) -> RuleResult:
        stats = conclusion.get("m3") or {}
        result.covered_count = int(stats.get("labelled", 0))
        result.numerator = int(stats.get("agrees", 0))
        return result.validate()