from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from app.domain.enums import VerdictConclusion
from app.tracing.callgraph import CallGraph
from app.tracing.entrypoints import EntryPoint

FULL_CONFIDENCE = 0.9
INCOMPLETE_CONFIDENCE = 0.4
UNREACHABLE_CONFIDENCE = 0.8
DYNAMIC_PENALTY_CONFIDENCE = 0.35


@dataclass(frozen=True)
class TaintResult:
    conclusion: VerdictConclusion
    confidence: float
    path: list[str]
    basis: str
    incomplete: bool


def _label(graph: CallGraph, node_id: str) -> str:
    node = graph.nodes.get(node_id)
    if node is None:
        return node_id
    return f"{node.file}:{node.name}"


def trace_taint(
    graph: CallGraph,
    entry: EntryPoint,
    sink_node_id: str | None,
    threshold: float = 0.60,
    max_visits: int = 200_000,
) -> TaintResult:
    if sink_node_id is None:
        return TaintResult(
            conclusion=VerdictConclusion.SUSPECTED,
            confidence=0.0,
            path=[],
            basis="漏洞点无法定位到具体函数，无法构建传播路径",
            incomplete=True,
        )

    start = graph.node_for_function(entry.file, entry.function)
    if start is None:
        return TaintResult(
            conclusion=VerdictConclusion.SUSPECTED,
            confidence=0.0,
            path=[],
            basis="入口点函数未在调用图中找到",
            incomplete=True,
        )

    if start == sink_node_id:
        return TaintResult(
            conclusion=VerdictConclusion.REACHABLE,
            confidence=FULL_CONFIDENCE,
            path=[_label(graph, start)],
            basis=f"入口点 {entry.kind.value} 直接位于漏洞函数",
            incomplete=False,
        )

    visited: set[str] = {start}
    queue: deque[tuple[str, list[str]]] = deque([(start, [start])])
    incomplete = False
    visits = 0
    while queue:
        current, path = queue.popleft()
        visits += 1
        if visits > max_visits:
            return TaintResult(
                conclusion=VerdictConclusion.SUSPECTED,
                confidence=INCOMPLETE_CONFIDENCE,
                path=[],
                basis="调用图遍历超出上限，判定结果不完整",
                incomplete=True,
            )
        node = graph.nodes.get(current)
        if node is not None and node.dynamic:
            incomplete = True
        for callee in graph.callees(current):
            if callee in visited:
                continue
            visited.add(callee)
            callee_node = graph.nodes.get(callee)
            if callee_node is not None and callee_node.dynamic:
                incomplete = True
            next_path = path + [callee]
            if callee == sink_node_id:
                confidence = FULL_CONFIDENCE - (DYNAMIC_PENALTY_CONFIDENCE if incomplete else 0.0)
                reachable = confidence >= threshold
                return TaintResult(
                    conclusion=VerdictConclusion.REACHABLE if reachable else VerdictConclusion.SUSPECTED,
                    confidence=round(confidence, 3),
                    path=[_label(graph, node_id) for node_id in next_path],
                    basis=(
                        "路径可能不完整（存在动态调用/反射）"
                        if incomplete
                        else "静态污点路径完整，可从入口点到达漏洞点"
                    ),
                    incomplete=incomplete,
                )
            queue.append((callee, next_path))

    if incomplete:
        return TaintResult(
            conclusion=VerdictConclusion.SUSPECTED,
            confidence=INCOMPLETE_CONFIDENCE,
            path=[],
            basis="调用关系包含动态调用，无法断言不可达，路径可能不完整",
            incomplete=True,
        )
    return TaintResult(
        conclusion=VerdictConclusion.UNREACHABLE,
        confidence=UNREACHABLE_CONFIDENCE,
        path=[],
        basis="未找到从受支持入口点到漏洞点的传播路径",
        incomplete=False,
    )

def trace_best(
    graph: CallGraph,
    entries: list[EntryPoint],
    sink_node_id: str | None,
    threshold: float = 0.60,
) -> TaintResult:
    if not entries:
        return TaintResult(
            conclusion=VerdictConclusion.SUSPECTED,
            confidence=0.0,
            path=[],
            basis="入口点识别为空，请核对入口点配置",
            incomplete=True,
        )
    results = [trace_taint(graph, entry, sink_node_id, threshold) for entry in entries]
    reachable = [item for item in results if item.conclusion is VerdictConclusion.REACHABLE]
    if reachable:
        return max(reachable, key=lambda item: (item.confidence, len(item.path)))
    suspected = [item for item in results if item.conclusion is VerdictConclusion.SUSPECTED]
    if suspected:
        return min(suspected, key=lambda item: len(item.path))
    return results[0]