from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.envelope import ApiError, ErrorCode
from app.selfcheck.models import (
    CheckSpec,
    Dimension,
    JudgmentMode,
    ThreeQuestion,
)
from app.selfcheck.registry import CheckRegistry, default_registry


def _spec(check_id: str, *, depends_on: tuple[str, ...] = ()) -> CheckSpec:
    return CheckSpec(
        check_id=check_id,
        title="示例",
        dimension=Dimension.REPRODUCIBLE,
        mode=JudgmentMode.AUTO,
        question=ThreeQuestion.REPRODUCE,
        criterion="示例标准",
        depends_on=depends_on,
    )


class RegistryTest(unittest.TestCase):
    def test_default_registry_has_thirty_specs(self) -> None:
        specs = default_registry.all()
        self.assertEqual(len(specs), 30)
        self.assertEqual(len({item.check_id for item in specs}), 30)

    def test_dimension_distribution(self) -> None:
        expected = {
            Dimension.REPRODUCIBLE: 6,
            Dimension.CAPABILITY: 6,
            Dimension.EVIDENCE: 7,
            Dimension.CONSISTENCY: 6,
            Dimension.DELIVERY: 5,
        }
        for dimension, count in expected.items():
            self.assertEqual(len(default_registry.select((dimension,))), count)

    def test_select_does_not_reorder(self) -> None:
        selected = default_registry.select((Dimension.REPRODUCIBLE,))
        self.assertEqual([item.check_id for item in selected], [f"D1-{index}" for index in range(1, 7)])
        everything = default_registry.all()
        self.assertEqual([item.check_id for item in everything][:6], [f"D1-{index}" for index in range(1, 7)])

    def test_duplicate_id_rejected(self) -> None:
        registry = CheckRegistry()
        registry.register(_spec("D1-1"))
        with self.assertRaises(ValueError):
            registry.register(_spec("D1-1"))

    def test_unknown_dependency_rejected(self) -> None:
        registry = CheckRegistry()
        registry.register(_spec("D1-1", depends_on=("D1-9",)))
        with self.assertRaises(ValueError):
            registry.validate_dependencies()

    def test_dependency_cycle_rejected_as_config_invalid(self) -> None:
        registry = CheckRegistry()
        registry.register(_spec("D1-1", depends_on=("D1-2",)))
        registry.register(_spec("D1-2", depends_on=("D1-1",)))
        with self.assertRaises(ApiError) as caught:
            registry.validate_dependencies()
        self.assertIs(caught.exception.code, ErrorCode.CONFIG_INVALID)

    def test_d5_1_has_no_d4_1_dependency(self) -> None:
        spec = default_registry.get("D5-1")
        self.assertEqual(spec.depends_on, ())
        dependencies = {item.check_id: item.depends_on for item in default_registry.all()}
        self.assertEqual(dependencies["D1-2"], ("D1-1",))
        self.assertEqual(dependencies["D1-4"], ("D1-1",))
        self.assertEqual(dependencies["D2-3"], ("D3-1",))
        self.assertEqual(dependencies["D2-6"], ("D2-2",))

    def test_legacy_vf7003_semantics_unchanged(self) -> None:
        self.assertEqual(ErrorCode.RECALC_FAILED.value, "VF-7003")
        self.assertEqual(ErrorCode.CONFIG_INVALID.value, "VF-1006")


if __name__ == "__main__":
    unittest.main()