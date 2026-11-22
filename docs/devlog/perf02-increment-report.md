# PERF-02 增量任务执行报告（2026-11-22）

> 依据：`.codeartsdoer/specs/metrics_recalc/tasks_perf02_write_block.md`（S1–S7 串行）。
> 代码基线：`main@259a1fc`；本报告只记录执行事实与设计偏差，不替代既有 spec/design/tasks。
> 未提交 Git（按要求）。

## 1. 完成情况

S1–S7 全部完成；任务清单 27 个条目、28 个复选框全部勾选为完成。未完成项：无。

| 阶段 | 完成任务 | 阶段验证结果 |
|---|---|---|
| S1 冻结黄金基线 | P2-1.1 / P2-1.2 / P2-1.3 / P2-1.4 | 夹具 `1100 1000 12000`；黄金四项两次采集完全相等；`test_metrics_snapshot` 11 用例 OK |
| S2 单次编码与纯函数 | P2-2.1 / P2-2.2 / P2-2.3 | `test_metrics_capture_budget` 首版 16 用例 OK；`encode_count==1` |
| S3 模型/装配/API | P2-3.1…P2-3.6 | 71 用例 OK（capture_budget + snapshot + recalc + api + report） |
| S4 对象纠正与非阻断 | P2-4.1 / P2-4.2 / P2-4.3 | `test_metrics_perf` 8 用例 OK（PERF-02 `write_block_ms=1–2ms`）；capture_budget 27 用例 OK |
| S5 不变量守护 | P2-5.1 / P2-5.2 / P2-5.3 | `test_metrics_invariants` 24 用例 OK；常量漂移探针可捕获 |
| S6 取证脚本扩展 | P2-6.1 / P2-6.2 / P2-6.3 | `--selftest` 10 项全 PASS；`capture-segmented` 3 轮 × 5 样本落盘；fake 输入判定正确 |
| S7 多轮证据/文档/回滚 | P2-7.1…P2-7.5 | 全量回归 851 OK；`round-summary` = 通过；回滚演练 44 OK + selftest PASS |

## 2. 改动清单

**生产代码**

- 新增 `backend/app/metrics/capture_health.py`：`WRITE_BLOCK_BUDGET_MS=200`、`CAPTURE_WARNINGS`、`CaptureMetrics.from_ns`、`evaluate_capture_health`。
- 改造 `backend/app/metrics/snapshot.py`：`encode_payload` 单次 canonical 编码；6 个纳秒边界分段计时；`capture_budget_ms`/`clock_ns` 注入；`ref` 回填 8 个计量字段；`SnapshotEnvelope.metrics`。
- 改造 `backend/app/domain/models.py`：`MetricSnapshotRef` 8 个计量字段 + 不自洽校验；`RecalcRun.warnings`。
- 改造 `backend/app/metrics/service.py`：默认 builder 注入 `capture_budget_ms`；`ref` 告警映射到 `RecalcRun.warnings` 与 `RecalcResult.warnings`（不重算）。
- 改造 `backend/app/metrics/types.py`：`RecalcResult.warnings`。
- 改造 `backend/app/main.py`：`POST /recalc` 与 `GET /recalc/{id}` 增 `warnings`；`GET /snapshots/{id}/verify` 增 9 个计量字段（`cached is None` 时为 null）；`_metric_payload` 未改。
- `backend/app/config.py`：未改（默认值 200 与下界 1 保持；未新增键）。

**测试与夹具**

- 新增 `backend/tests/support/perf_fixture.py`（`build_perf02_store` / `build_small_store` + 冻结常量）。
- 新增 `backend/tests/support/snapshot_golden.json`、`snapshot_golden_small.json`、`snapshot_golden/SNAP-*.json`（改造前实物归档）。
- 新增 `backend/tests/test_metrics_capture_budget.py`（27 用例：黄金四项、键序、单次编码、分段等式、告警边界、非阻断、临界段代理、旧数据兼容、跨版本复用）。
- 改造 `backend/tests/test_metrics_perf.py`：断言改 `write_block_ms ≤ 200`、`encode_count == 1`、数据规模常量；新增 `PERF01/02/04_LIMIT_S`、`PERF02_RUNS/EVENTS`、`PERF_WRITE_BLOCK_MS`；改用统一夹具。
- 扩展 `backend/tests/test_metrics_invariants.py`（24 用例：阈值/规模/无 sleep/无新增 skip/报告隔离/API 键集合/m5 sha256）。

**脚本**

- 新增 `scripts/capture_snapshot_golden.py`（一次性黄金采集；只写 `backend/tests/support/`）。
- 改造 `scripts/perf_probe.py`：新增 `capture-segmented`、`round-summary`、`regression` 子命令；`write-block` 增加可选 `--round`；新增 `EXTRA_REQUIRED` 3 类记录与 `ROUND_RULES`；既有 `REQUIRED` 与 `--selftest` 的 `schema_hits==8` 未改。
- 改造 `scripts/recalc_metrics.py`：仅更新验证说明文案为新口径（`write_block_ms` 判据 / 端到端告警）。

**文档**

- 更新 `docs/devlog/metrics-report.md`：性能行改为"写阻塞/全链路分离"，新增 PERF-02 口径、黄金值、3 轮证据指针、回滚方案、DoD 对照。
- 新增 `docs/devlog/perf02-rollback-drill.md`：回滚演练记录。
- 新增本报告 `docs/devlog/perf02-increment-report.md`。
- 只读未改：`.codeartsdoer/specs/metrics_recalc/{spec,design,tasks}.md`、`docs/devlog/m5-eval-report.md`（sha256 `931d2044…5502` 未变）。

## 3. 设计偏差与裁定（已落地）

| 编号 | 设计与任务原文 | 实际执行 | 理由 |
|---|---|---|---|
| D-1 | 只需固定 `Event.occurred_at` 即可跨进程重建 | 额外固定 `Issue.updated_at` | `Issue.updated_at` 默认 `utc_now`，不固定则 digest 每次漂移（实测两次 `9d9d…` vs `9f98…`）；固定后跨进程 digest 恒为 `3de2…` |
| D-2 | `_digest` 若保留则改为接收 `bytes`，全仓无其他调用点 | 保留 `_digest(payload)` 作为测试辅助（内部调用 `encode_payload`），`capture` 不再调用 | 实际调用点在 `test_metrics_snapshot.py:98/166`；改签名会迫改既有测试断言，违背"既有用例零回归" |
| D-3 | `capture_total_ms >= capture_ms` 绝对不变式 | 旧 ref（`capture_total_ms == 0`）豁免该比较 | 旧 ref 无此字段，默认 0 会与 `capture_ms>0` 冲突，违反 RP-10 旧数据可读；新写入路径始终填真实值 |
| D-4 | P2-5.3 ②"不同预算生成的报告 `content_digest` 相同" | 改为断言两次报告 `rows` 口径逐字段相同、报告不含性能字段、`content_digest == sha256(markdown)` 口径不变 | `content_digest` 覆盖 markdown，必然含 `recalc_id`/`generated_at`/`report_id`；两次独立复算不可能同 digest。告警不污染报告已由 rows 相等证明 |
| D-5 | P2-7.1 写阻塞命令无轮次参数 | `write-block` 新增可选 `--round`（默认 0 保持原文件名），证据落 `-r{n}.json` | 满足"每轮独立文件、禁止覆盖"且不改既有默认输出格式 |
| D-6 | P2-7.1 未指定回归记录工具 | 新增 `regression` 子命令执行真实全量 `unittest` 并落盘记录 | 避免手工抄写/伪造；退出码透传子进程结果 |
| D-7 | P2-7.5 复算命令默认覆盖 `metrics-report.md` | 先执行默认命令（报告版本 0007），随后重新追加 PERF-02 章节 | 报告为机器产物；人工章节需在生成后追加，否则被覆盖 |
| D-8 | 回滚演练使用独立 worktree | worktree 需补齐被 `.gitignore` 的 `backend/app/eval/` 与 `eval/` 数据后执行 | 仓库 `.gitignore:44` 忽略 `eval/`，HEAD worktree 缺该运行依赖；补齐不改变改造前产品代码 |
| D-9 | 分段耗时按各区间独立向下取整 | 改为按累计边界差计算：`clone=floor(t1-t0)`、`build=floor(t2-t0)-floor(t1-t0)`，其余同理 | 独立取整在纳秒余数组合下可使三条毫秒等式相差 2–3ms；累计差保证三项等式恒等，且 `capture_ms`/`capture_total_ms` 语义不变 |

## 4. 各阶段验证命令与真实结果

| 阶段 | 命令 | 真实结果 |
|---|---|---|
| S1 | `python scripts/capture_snapshot_golden.py --window 2026-12 --tier PRELIMINARY` | 退出码 0；`payload_sha256=digest=archive_sha256=3de2d3ce…4120`，`archive_bytes=7,265,041` |
| S1 | `python scripts/capture_snapshot_golden.py --small` | 退出码 0；`265557bc…5b3b`，19,158 bytes |
| S1 | `python -m unittest backend.tests.test_metrics_snapshot` | Ran 11，OK |
| S2 | `python -m unittest backend.tests.test_metrics_capture_budget` | Ran 16，OK（首版） |
| S3 | `python -m unittest backend.tests.test_metrics_recalc backend.tests.test_metrics_api backend.tests.test_metrics_capture_budget` | Ran 46，OK |
| S3 | `python -m unittest backend.tests.test_metrics_capture_budget backend.tests.test_metrics_snapshot backend.tests.test_metrics_recalc backend.tests.test_metrics_api backend.tests.test_metrics_report` | Ran 71，OK |
| S4 | `python -m unittest backend.tests.test_metrics_perf` | Ran 8，OK；`write_block_ms=1–2ms`，`segment_ms` 五项打印 |
| S4 | `python -m unittest backend.tests.test_metrics_capture_budget` | Ran 27，OK |
| S5 | `python -m unittest backend.tests.test_metrics_invariants` | Ran 24，OK |
| S5 | 常量漂移探针（monkeypatch） | `WRITE_BLOCK_BUDGET_MS=500` → 失败；`PERF02_LIMIT_S=61.0` → 失败；还原后 OK |
| S6 | `python scripts/perf_probe.py --selftest` | 10 项全 PASS（既有 `schema checks=16` 未变，新增 `extra schema checks=3`、`round rule fixtures`） |
| S6 | `python scripts/perf_probe.py capture-segmented --case PERF-02/metrics-capture --env default --rounds 3 --samples 5 --write-ops 200` | 退出码 0，`stamp=20261122T201931`，3 个 jsonl + 3 个 measure |
| S6 | `... --rounds 2` | 退出码 2，`ROUNDS_INSUFFICIENT` |
| S6 | fake 输入 round-summary | 全达标 → `通过`；r2 `write_block_ms=201` → `不通过` 且理由 `write_block_ms`；重复输出 → `OUTPUT_EXISTS` |
| S7 | `python scripts/perf_probe.py write-block ... --round {1,2,3}` | 退出码 0；`Δp95 = 0.0021 / 0.0016 / 0.0010 ms` |
| S7 | `python scripts/perf_probe.py regression --round {1,2,3}` | 3 轮均 `Ran 851`、`errors=0`、`failures=0`、`contains_skip=false`、退出码 0 |
| S7 | `python scripts/perf_probe.py round-summary --case PERF-02/metrics-capture` | `decision_class="通过"`；`round-summary-20261122T202438.json` |
| S7 | `python -m unittest backend.tests.test_check_devlog backend.tests.test_metrics_invariants` | Ran 30，OK |
| S7 | 回滚演练（独立 worktree，HEAD=259a1fc） | `Ran 44 tests in 1.626s`，OK（errors=0/failures=0）；`perf_probe --selftest` 8 项 PASS；PERF-02 旧端到端实测 176.5ms |
| S7 | `python scripts/recalc_metrics.py --window 2026-12 --tier PRELIMINARY --now 2027-01-06T12:00:00+00:00` | 退出码 0；`report_id=RPT-2026-12-PRELIMINARY-0007`，9 行摘要输出 |
| S7 | `python -m unittest discover -s backend/tests -p "test_*.py"` | `Ran 851 tests in 58.952s`，OK（0 failure / 0 error / 0 skip） |

## 5. 性能多轮数据（3 轮 × 5 样本）

| 轮次 | `write_block_ms` p50 / p95 / max | `capture_total_ms` p50 / p95 / max | 超预算次数 | `encode_count` | 协议 W `Δp95` |
|---|---|---|---|---|---|
| r1 | 2 / 2 / 2 ms | 143 / 148 / 148 ms | 0 | 1 | 0.0021 ms |
| r2 | 1 / 2 / 2 ms | 129 / 154 / 154 ms | 0 | 1 | 0.0016 ms |
| r3 | 1 / 2 / 2 ms | 144 / 158 / 158 ms | 0 | 1 | 0.0010 ms |

- 判据量 `write_block_ms` 最大 2ms，距 200ms 预算余量两个数量级。
- `capture_total_ms` 仅作告警口径；本轮 15 样本均未超 200ms（超预算次数 0）。
- 全量复算（1100 Issue / 12000 Event）实测 0.68–0.78s（门槛 60s）；PERF-01 0.017s（门槛 5s）；PERF-04 0.001–0.003s（门槛 3s）。

## 6. 测试计数与失败项

- 全量：`Ran 851 tests`，`OK`，失败 0、错误 0、跳过 0。
- 本次直接相关：`test_metrics_capture_budget` 27、`test_metrics_invariants` 24、`test_metrics_perf` 8、`test_metrics_snapshot` 11、`test_metrics_recalc`/`test_metrics_api`/`test_metrics_report` 等共同构成验证组合 71 用例（S3 阶段）。
- 失败项：无。过程中出现过 2 次测试辅助函数自造错误（`metrics_with` 未保证 `capture_ms ≥ write_block_ms`），已修正测试辅助而非放宽断言。

## 7. 未完成项与阻塞

无未完成项。环境边界：回滚演练 worktree 需补齐 `.gitignore` 排除的 `backend/app/eval/` 与 `eval/`；这是仓库既有结构事实，不影响主工作区与回滚结论。写阻塞结论仅适用于单进程内存实现（`MemoryStore` + GIL），不外推至持久化后端。