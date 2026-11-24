import unittest

from app.adapters.pr_evidence import NOT_CLAIMED, PrEvidence


def _evidence(**overrides) -> PrEvidence:
    payload = dict(
        issue_id="ISS-001",
        run_id="RUN-20261124T000000+0800-abcd",
        red_green_paired=True,
        regression_zero_fail=True,
        rescan_new_alerts=0,
        coverage_delta_pp=0.0,
    )
    payload.update(overrides)
    return PrEvidence(**payload)


class PrEvidenceTest(unittest.TestCase):
    def test_render_contains_run_id_and_issue(self) -> None:
        body = _evidence().render()
        self.assertIn("RUN-20261124T000000+0800-abcd", body)
        self.assertIn("| issue | ISS-001 |", body)

    def test_render_uses_readable_boolean(self) -> None:
        body = _evidence(red_green_paired=False, regression_zero_fail=True).render()
        self.assertIn("| 红态—绿态配对 | 否 |", body)
        self.assertIn("| 回归零失败 | 是 |", body)

    def test_render_formats_coverage_with_sign(self) -> None:
        self.assertIn("| 覆盖率变化(pp) | +1.20 |", _evidence(coverage_delta_pp=1.2).render())
        self.assertIn("| 覆盖率变化(pp) | -0.35 |", _evidence(coverage_delta_pp=-0.35).render())

    def test_render_renders_alert_count(self) -> None:
        self.assertIn("| 复扫新增告警 | 3 |", _evidence(rescan_new_alerts=3).render())

    def test_render_keeps_not_claimed_section(self) -> None:
        body = _evidence().render()
        self.assertIn("## 不得声称", body)
        self.assertIn(NOT_CLAIMED, body)

    def test_render_is_deterministic(self) -> None:
        self.assertEqual(_evidence().render(), _evidence().render())

    def test_rows_order_is_stable(self) -> None:
        self.assertEqual(
            [name for name, _ in _evidence().rows()],
            ["issue", "run_id", "红态—绿态配对", "回归零失败", "复扫新增告警", "覆盖率变化(pp)"],
        )


if __name__ == "__main__":
    unittest.main()