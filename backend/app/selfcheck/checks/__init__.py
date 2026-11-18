"""检查项聚合：显式导入五个维度模块，保持注册顺序为 D1-1 … D5-5。"""

from __future__ import annotations

from ..models import CheckSpec


def all_specs() -> tuple[CheckSpec, ...]:
    from . import d1_reproducible, d2_capability, d3_evidence, d4_consistency, d5_delivery

    return (
        d1_reproducible.SPECS
        + d2_capability.SPECS
        + d3_evidence.SPECS
        + d4_consistency.SPECS
        + d5_delivery.SPECS
    )