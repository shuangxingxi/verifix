from __future__ import annotations

from dataclasses import dataclass

NOT_CLAIMED = (
    "本 PR 由 VeriFix 自动生成，结论范围仅限三闸与回归数据；"
    "不代表云上部署、线上连续运行时长或真实远端合并已验证。"
)


def _yes_no(flag: bool) -> str:
    return "是" if flag else "否"


@dataclass(frozen=True)
class PrEvidence:
    issue_id: str
    run_id: str
    red_green_paired: bool
    regression_zero_fail: bool
    rescan_new_alerts: int
    coverage_delta_pp: float

    def rows(self) -> tuple[tuple[str, str], ...]:
        return (
            ("issue", self.issue_id),
            ("run_id", self.run_id),
            ("红态—绿态配对", _yes_no(self.red_green_paired)),
            ("回归零失败", _yes_no(self.regression_zero_fail)),
            ("复扫新增告警", str(self.rescan_new_alerts)),
            ("覆盖率变化(pp)", f"{self.coverage_delta_pp:+.2f}"),
        )

    def render(self) -> str:
        lines = ["## 证据摘要", "", "| 字段 | 值 |", "| --- | --- |"]
        lines.extend(f"| {name} | {value} |" for name, value in self.rows())
        lines.extend(["", "## 不得声称", "", f"- {NOT_CLAIMED}", ""])
        return "\n".join(lines)