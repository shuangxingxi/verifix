from __future__ import annotations

from app.metrics.judgment import MetricComputation


def build_source_ref(computation: MetricComputation) -> str:
    parts = [computation.source_ref or "未登记采集源"]
    eval_run = computation.details.get("eval_run_id")
    if eval_run:
        parts.append(f"eval_run_id={eval_run}")
    if computation.details.get("legacy_conclusion"):
        parts.append("legacy_conclusion=True")
    parts.append(f"definition={computation.definition_version}")
    return " / ".join(part for part in parts if part)