"""抓取计量值对象与告警纯函数（PERF-02）。

本模块无 IO、无时钟、无全局可变量：
- ``CaptureMetrics.from_ns`` 只做纳秒→毫秒的向下取整与自洽校验；
- ``evaluate_capture_health`` 只把计量事实映射为两个稳定告警码。
"""

from __future__ import annotations

from dataclasses import dataclass

WRITE_BLOCK_BUDGET_MS = 200
CAPTURE_WARNINGS = ("WRITE_BLOCK_EXCEEDED", "CAPTURE_SLOW")
SEGMENT_KEYS = ("clone", "build", "encode", "archive", "chain")

_NS_PER_MS = 1_000_000


def _to_ms(delta_ns: int) -> int:
    return int(delta_ns // _NS_PER_MS)


@dataclass(frozen=True)
class CaptureMetrics:
    write_block_ms: int
    capture_ms: int
    capture_total_ms: int
    encode_count: int
    segment_ms: dict[str, int]

    def __post_init__(self) -> None:
        if self.encode_count < 1:
            raise ValueError("encode_count must be >= 1")
        if min(self.write_block_ms, self.capture_ms, self.capture_total_ms) < 0:
            raise ValueError("capture metrics must be non-negative")
        if self.capture_ms > self.capture_total_ms:
            raise ValueError("capture_ms must not exceed capture_total_ms")
        if self.write_block_ms > self.capture_ms:
            raise ValueError("write_block_ms must not exceed capture_ms")
        if set(self.segment_ms) != set(SEGMENT_KEYS):
            raise ValueError("segment_ms must contain exactly: " + ",".join(SEGMENT_KEYS))
        if any(value < 0 for value in self.segment_ms.values()):
            raise ValueError("segment_ms values must be non-negative")

    @classmethod
    def from_ns(
        cls,
        t0: int,
        t1: int,
        t2: int,
        t3: int,
        t4: int,
        t5: int,
        encode_count: int,
    ) -> "CaptureMetrics":
        boundaries = (t0, t1, t2, t3, t4, t5)
        if any(later < earlier for earlier, later in zip(boundaries, boundaries[1:])):
            raise ValueError("capture boundaries must be monotonic non-decreasing")
        if encode_count < 1:
            raise ValueError("encode_count must be >= 1")
        elapsed_ms = [_to_ms(boundary - t0) for boundary in boundaries]
        segment_ms = {
            "clone": elapsed_ms[1] - elapsed_ms[0],
            "build": elapsed_ms[2] - elapsed_ms[1],
            "encode": elapsed_ms[3] - elapsed_ms[2],
            "archive": elapsed_ms[4] - elapsed_ms[3],
            "chain": elapsed_ms[5] - elapsed_ms[4],
        }
        return cls(
            write_block_ms=segment_ms["clone"],
            capture_ms=_to_ms(t4 - t0),
            capture_total_ms=_to_ms(t5 - t0),
            encode_count=encode_count,
            segment_ms=segment_ms,
        )


def evaluate_capture_health(metrics: CaptureMetrics, capture_budget_ms: int) -> list[str]:
    """把计量事实映射为稳定告警码；顺序固定、不重复、不抛业务异常。"""
    if capture_budget_ms < 1:
        raise ValueError("capture_budget_ms must be >= 1")
    warnings: list[str] = []
    if metrics.write_block_ms > WRITE_BLOCK_BUDGET_MS:
        warnings.append("WRITE_BLOCK_EXCEEDED")
    if metrics.capture_total_ms > capture_budget_ms:
        warnings.append("CAPTURE_SLOW")
    return warnings