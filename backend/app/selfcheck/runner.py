"""调度器：按注册顺序执行、依赖传导、异常隔离、只读比对与汇总。"""

from __future__ import annotations

from typing import Iterable, Optional

from app.api.envelope import ApiError, ErrorCode

from . import baseline as baseline_module
from .context import DEFINITION_VERSION, ReadOnlySnapshot, mask, monotonic, utc_now_iso
from .models import (
    CheckResult,
    CheckSpec,
    Dimension,
    SelfcheckResult,
    Status,
    STATUS_SEVERITY,
    ThreeQuestion,
    build_result,
    derive_overall,
    summarize_dimensions,
)


class SelfcheckRunner:
    def __init__(self, ctx: object, registry: object | None = None) -> None:
        if registry is None:
            from .registry import default_registry

            registry = default_registry
        self.ctx = ctx
        self.registry = registry

    def run(self, scope: Optional[Iterable[object]] = None) -> SelfcheckResult:
        scope_codes = _scope_codes(scope)
        selected = {spec.check_id for spec in self.registry.select(scope_codes)}
        snapshotter = ReadOnlySnapshot(self.ctx)
        before = snapshotter.capture()
        previous = baseline_module.load(self.ctx.baseline_path)

        results: list[CheckResult] = []
        by_id: dict[str, CheckResult] = {}
        for spec in self.registry.all():
            started = utc_now_iso(self.ctx.clock)
            began = monotonic()
            if spec.check_id not in selected:
                result = build_result(
                    spec,
                    Status.UNVERIFIED,
                    sub_reason="SCOPE_EXCLUDED",
                    output_summary="范围外，未执行。",
                )
            else:
                blocking = [
                    by_id[dependency]
                    for dependency in spec.depends_on
                    if dependency in by_id
                    and by_id[dependency].status in (Status.BLOCKED, Status.MANUAL_PENDING)
                ]
                if blocking:
                    strict = max(blocking, key=lambda item: STATUS_SEVERITY[item.status])
                    result = build_result(
                        spec,
                        strict.status,
                        sub_reason="DEPENDENCY_FAILED",
                        output_summary="依赖项未通过：" + ", ".join(item.check_id for item in blocking),
                    )
                else:
                    result = self._execute(spec)
            result.started_at = started
            result.finished_at = utc_now_iso(self.ctx.clock)
            result.duration_seconds = max(result.duration_seconds, monotonic() - began)
            by_id[result.check_id] = result
            results.append(result)

        after = snapshotter.capture()
        difference = snapshotter.diff(before, after)
        readonly_ok = not snapshotter.has_diff(difference)
        if not readonly_ok:
            self.ctx.warnings.append(
                "只读违规：新增 {} / 删除 {} / 改动 {}".format(
                    len(difference["added"]), len(difference["removed"]), len(difference["changed"])
                )
            )

        changes = baseline_module.compare(
            previous, results, definition_version=DEFINITION_VERSION
        )
        for result in results:
            result.baseline_change = changes.get(result.check_id, "UNCHANGED")

        overall, exit_code = derive_overall(results, readonly_ok=readonly_ok)
        summary = summarize_dimensions(results)
        claims = list(self.ctx.artifacts.get("claims", []))
        evidence = list(self.ctx.artifacts.get("evidence", []))
        consistency = list(self.ctx.artifacts.get("consistency", []))
        delivery = list(self.ctx.artifacts.get("delivery", []))

        escalated = baseline_module.check_level_escalation(claims, previous)
        if escalated:
            overall, exit_code = "不通过", 3
            self.ctx.warnings.append(
                "级别无证据提升：" + ", ".join(escalated)
            )

        scoped = [item.value for item in Dimension] if scope_codes is None else list(scope_codes)
        result = SelfcheckResult(
            run_id="",
            fingerprint=self.ctx.fingerprint(scoped, previous.baseline_id),
            generated_at=utc_now_iso(self.ctx.clock),
            scope=scoped,
            baseline_id=previous.baseline_id,
            overall=overall,
            exit_code=exit_code,
            readonly_ok=readonly_ok,
            checks=results,
            dimensions=summary,
            claims=claims,
            evidence=evidence,
            consistency=consistency,
            delivery=delivery,
        )
        result.weakest_link, result.top_questions, result.fix_priority = _narrative(
            results, summary, self.registry
        )
        result.readonly_files = difference  # type: ignore[attr-defined]
        result.baseline_note = previous.note  # type: ignore[attr-defined]
        result.notes = list(self.ctx.notes)  # type: ignore[attr-defined]
        return result

    def _execute(self, spec: CheckSpec) -> CheckResult:
        try:
            result = spec.execute(self.ctx)
        except ApiError as exc:
            reason = "TIMEOUT" if exc.code is ErrorCode.SELFCHECK_TIMEOUT else "EXCEPTION"
            return build_result(
                spec,
                Status.BLOCKED,
                sub_reason=reason,
                output_summary=self.ctx.sanitize(mask(str(exc)))[:400],
            )
        except Exception as exc:  # noqa: BLE001 - 项间隔离要求捕获所有异常
            return build_result(
                spec,
                Status.BLOCKED,
                sub_reason="EXCEPTION",
                output_summary=self.ctx.sanitize(mask(f"{type(exc).__name__}: {exc}"))[:400],
            )
        if not isinstance(result, CheckResult):
            return build_result(
                spec,
                Status.BLOCKED,
                sub_reason="EXCEPTION",
                output_summary="检查项未返回 CheckResult。",
            )
        if result.check_id != spec.check_id:
            return build_result(
                spec,
                Status.BLOCKED,
                sub_reason="EXCEPTION",
                output_summary=f"结果编号不一致：{result.check_id}",
            )
        result.dimension = spec.dimension
        result.mode = spec.mode
        result.question = spec.question
        result.output_summary = self.ctx.sanitize(mask(result.output_summary))
        result.command = mask(result.command) if result.command else result.command
        result.evidence_refs = sorted(set(result.evidence_refs))
        return result


def _scope_codes(scope: Optional[Iterable[object]]) -> Optional[tuple[str, ...]]:
    if scope is None:
        return None
    codes: set[str] = set()
    for item in scope:
        value = item.value if isinstance(item, Dimension) else str(item)
        if value not in {dimension.value for dimension in Dimension}:
            raise ValueError(f"invalid scope: {value}")
        codes.add(value)
    return tuple(sorted(codes))


def _narrative(
    results: list[CheckResult],
    summaries: list,
    registry: object,
) -> tuple[str, list[str], list[str]]:
    blocked = [item for item in results if item.status is Status.BLOCKED]
    weakest = "当前运行未发现阻塞"
    if blocked:
        ranked = sorted(
            summaries,
            key=lambda item: (-item.blocked, -item.unverified, item.dimension.value),
        )
        head = ranked[0]
        weakest = f"{head.dimension.value} {head.dimension.label}（阻塞 {head.blocked} 项，未验证 {head.unverified} 项）"
    counts = {question: 0 for question in ThreeQuestion}
    for item in blocked:
        counts[item.question] += 1
    questions: list[str] = []
    for question, value in sorted(counts.items(), key=lambda pair: -pair[1]):
        if value <= 0:
            continue
        members = [item.check_id for item in blocked if item.question is question]
        questions.append(f"{question.value}：{value} 项（{', '.join(members)}）")
        if len(questions) == 3:
            break
    if not questions:
        questions.append("本次运行未发现阻塞，三问暂无高危项")
    elif len(questions) < 3:
        questions.append("本次不足三项，按实际数量列示")
    priority: list[str] = []
    for item in blocked:
        spec = registry.get(item.check_id)
        reason = item.sub_reason or "未达通过标准"
        priority.append(f"[{item.check_id}] {spec.title}：{reason}；依据：{spec.criterion}")
    if not blocked:
        priority.append("本次运行未发现阻塞")
    priority.append("工期判断：人工待填（由负责人填写，不由自检推断）")
    return weakest, questions, priority