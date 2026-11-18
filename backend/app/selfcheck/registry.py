"""检查项注册表：编号唯一、范围过滤不重排、依赖环在注册期失败。"""

from __future__ import annotations

from typing import Iterable, Optional

from app.api.envelope import ApiError, ErrorCode

from .models import CheckSpec, Dimension


class CheckRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, CheckSpec] = {}

    def register(self, spec: CheckSpec) -> None:
        if spec.check_id in self._specs:
            raise ValueError(f"duplicate check id: {spec.check_id}")
        self._specs[spec.check_id] = spec

    def get(self, check_id: str) -> CheckSpec:
        try:
            return self._specs[check_id]
        except KeyError:
            raise KeyError(f"unknown check id: {check_id}") from None

    def all(self) -> tuple[CheckSpec, ...]:
        return tuple(self._specs.values())

    def select(self, scope: Optional[Iterable[object]] = None) -> tuple[CheckSpec, ...]:
        specs = tuple(self._specs.values())
        if scope is None:
            return specs
        allowed = {
            item.value if isinstance(item, Dimension) else str(item) for item in scope
        }
        return tuple(spec for spec in specs if spec.dimension.value in allowed)

    def validate_dependencies(self) -> None:
        for spec in self._specs.values():
            for dependency in spec.depends_on:
                if dependency not in self._specs:
                    raise ValueError(
                        f"{spec.check_id} depends on unknown check {dependency}"
                    )
        state: dict[str, int] = {}
        stack: list[str] = []

        def visit(check_id: str) -> None:
            marker = state.get(check_id, 0)
            if marker == 1:
                cycle = " -> ".join(stack[stack.index(check_id):] + [check_id])
                # 设计偏差：VF-7003 已被 RECALC_FAILED 占用，依赖环使用 VF-1006。
                raise ApiError(ErrorCode.CONFIG_INVALID, f"dependency cycle: {cycle}")
            if marker == 2:
                return
            state[check_id] = 1
            stack.append(check_id)
            for dependency in self._specs[check_id].depends_on:
                visit(dependency)
            stack.pop()
            state[check_id] = 2

        for check_id in self._specs:
            visit(check_id)


def build_default_registry() -> CheckRegistry:
    from .checks import all_specs

    registry = CheckRegistry()
    for spec in all_specs():
        registry.register(spec)
    registry.validate_dependencies()
    return registry


default_registry = build_default_registry()