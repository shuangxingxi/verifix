from __future__ import annotations

from dataclasses import dataclass, field

COMPARED_FIELDS = (
    "value",
    "computable",
    "unverified",
    "reason_code",
    "numerator",
    "denominator",
    "covered_count",
    "excluded_count",
    "channel_excluded_count",
    "not_applicable_count",
    "source_ref",
    "recalc_id",
    "snapshot_digest",
    "eval_run_id",
    "definition_version",
    "met",
)
FLOAT_TOLERANCE = 1e-9


@dataclass(frozen=True)
class FieldDiff:
    metric_id: str
    field: str
    left: object
    right: object

    def to_dict(self) -> dict:
        return {"metric_id": self.metric_id, "field": self.field, "left": self.left, "right": self.right}


@dataclass
class ConsistencyReport:
    differences: list[FieldDiff] = field(default_factory=list)

    @property
    def consistent(self) -> bool:
        return not self.differences

    def to_dict(self) -> dict:
        return {
            "consistent": self.consistent,
            "differences": [item.to_dict() for item in self.differences],
        }


class CrossReportConsistencyChecker:
    def compare(self, main_rows: list[dict], special_rows: list[dict]) -> ConsistencyReport:
        main = {row["metric_id"]: row for row in main_rows}
        special = {row["metric_id"]: row for row in special_rows}
        differences: list[FieldDiff] = []
        for metric_id in sorted(set(main) & set(special)):
            left = main[metric_id]
            right = special[metric_id]
            for name in COMPARED_FIELDS:
                if name not in left and name not in right:
                    continue
                if not self._equal(name, left.get(name), right.get(name)):
                    differences.append(FieldDiff(metric_id, name, left.get(name), right.get(name)))
        return ConsistencyReport(differences=differences)

    @staticmethod
    def _equal(name: str, left, right) -> bool:
        if name == "source_ref":
            return str(left or "").strip() == str(right or "").strip()
        if isinstance(left, float) or isinstance(right, float):
            try:
                return abs(float(left) - float(right)) <= FLOAT_TOLERANCE
            except (TypeError, ValueError):
                return left == right
        return left == right