# PERF-02 回滚演练记录（2026-11-22）

## 演练方式

- 触发来源：`docs/devlog/metrics-report.md`「回滚方案（PERF-02 增量）」。
- 隔离方式：独立 `git worktree`（`HEAD=259a1fc`，即改造前基线），主工作区未执行任何 `git reset`/`checkout`。
- 环境补齐说明：`backend/app/eval/` 与 `eval/` 被仓库 `.gitignore` 第 44 行 `eval/` 规则排除，worktree 默认不含这两个运行依赖；演练时把主工作区的同名只读副本补齐到 worktree（不改变改造前产品代码），随后执行复核命令。
- 演练后已 `git worktree remove --force` 并 `git worktree prune`；`git worktree list` 仅剩主工作区。

## 复核命令与结果

| 命令 | 退出码 | 结果 |
|---|---|---|
| `python -m unittest backend.tests.test_metrics_snapshot backend.tests.test_metrics_recalc backend.tests.test_metrics_report backend.tests.test_metrics_perf` | 0 | `Ran 44 tests in 1.626s`，`OK`（errors=0，failures=0） |
| `python scripts/perf_probe.py --selftest` | 0 | 8 项 check 全 PASS（`jsonl append`、`json output exists`、`readonly violation`、`schema checks=16`、`RF finding_id prefix`、`scale`、`judge fixtures=6/6`、`priority`） |

改造前 PERF-02 用例实测：`capture` 端到端 176.5ms（旧断言 `capture_elapsed < 0.2` 本次通过）。该量为端到端耗时，历史 5 次采样中曾出现 209.9ms（`.evidence/perf-repro/decision-perf02-20261119T235056.json`），证明旧断言对象不稳定；PERF-02 增量改造后改为对 `write_block_ms`（结构插桩，实测 1–2ms）做硬断言。

## 回滚后仍需注意

- 归档文件（`metrics/snapshots/*.json`）无需处理：payload 与文件名未变，回滚前后均可 `verify`。
- 进程重启后 `MetricSnapshotRef`/`RecalcRun` 内存态重建，带新字段的记录不残留。
- 证据文件只追加、不删除；跨轮汇总中的 `supersedes` 保持为空，如未来重跑需在新汇总中登记被取代的旧汇总。