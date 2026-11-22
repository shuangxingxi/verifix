# 主流程指标报告 RPT-2026-12-PRELIMINARY-0007

- 窗口：2026-12
- 阶段档：PRELIMINARY
- 定义版本：v2
- 生成时间：2027-01-06T12:00:00+00:00
- 发起主体：cli
- 评测运行：EVALRUN-27714aeffb
- 历史留痕摘要：931d20442673b0922a32cfb42de1dcc9996925836607f6ddedbc5e8b1f165502
- 结论：UNDETERMINED

| 指标 | 定义版本 | 值 | 可计算 | 原因码 | 分子 | 分母 | 覆盖 | 剔除 | 通道排除 | 不适用 | 采集源 | 复算标识 | 快照摘要 | 评测运行 | 初赛目标 | 达标 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M4 复现成功率 | v2 | 0.6667 | True | - | 2.0000 | 3.0000 | 3 | 0 | 1 | 0 | ReproductionAttempt + Proof + Verdict / definition=v2 | RC-20270106T120000000000-969d37 | 295bb639ac38008a46797a4961aa1c3a9a736fb15f7863e1fd03e1be09e677f6 |  | 0.6000 | True |
| M5 一次修复通过率 | v2 | 1.0000 | True | - | 2.0000 | 2.0000 | 2 | 0 | 1 | 1 | PatchAttempt(first) + GateAttempt + DispositionHistory / definition=v2 | RC-20270106T120000000000-969d37 | 295bb639ac38008a46797a4961aa1c3a9a736fb15f7863e1fd03e1be09e677f6 |  | 0.4500 | True |
| M6 回归破坏率 | v2 | 0.0000 | True | - | 0.0000 | 2.0000 | 2 | 0 | 1 | 1 | GateResult + GateAttempt / definition=v2 | RC-20270106T120000000000-969d37 | 295bb639ac38008a46797a4961aa1c3a9a736fb15f7863e1fd03e1be09e677f6 |  | 0.0000 | - |
| M7 MTTR | v2 | 30.0000 | True | - | 60.0000 | 2.0000 | 2 | 0 | 1 | 1 | Alert.observed_at + Disposition.ready_at / definition=v2 | RC-20270106T120000000000-969d37 | 295bb639ac38008a46797a4961aa1c3a9a736fb15f7863e1fd03e1be09e677f6 |  | 0.0000 | - |
| M8 自动处置率 | v2 | 0.6667 | True | - | 2.0000 | 3.0000 | 3 | 0 | 1 | 0 | Disposition + GateAttempt / definition=v2 | RC-20270106T120000000000-969d37 | 295bb639ac38008a46797a4961aa1c3a9a736fb15f7863e1fd03e1be09e677f6 |  | 0.0000 | - |
| M9 连续自运行 | v2 | 未验证 | False | EVIDENCE_MISSING | 0.0000 | 0.0000 | 0 | 0 | 1 | 0 | runtime self-run samples / definition=v2 | RC-20270106T120000000000-969d37 | 295bb639ac38008a46797a4961aa1c3a9a736fb15f7863e1fd03e1be09e677f6 |  | 24.0000 | - |

## 与历史 m5 报告的口径差异对照

| 指标 | 历史值/状态 | 新值/状态 | 差异原因 |
|---|---|---|---|
| M1 | 1.0000（可计算） | 1.0000（可计算） | 历史 m5 报告以单文件评测集口径记 1.0；新口径为裁决后的正例+边界检出率，分母固定 30 |
| M2 | 1.0000（可计算） | -（不可计算，原因码 SOURCE_MISSING） | 历史报告记录 1.0；新口径要求显式漏洞检出字段，缺失即 SOURCE_MISSING，不本地推导 |
| M3 | 1.0000（可计算） | 1.0000（可计算） | 历史报告记录 1.0；新口径分母为有可达性标注样本数，须由裁决结论披露分子分母 |
| M4 | 不可计算 | 0.6667（可计算） | 历史 m5 报告只覆盖评测通道；新口径按 v2 主流程复现证据计算 |
| M5 | 不可计算 | 1.0000（可计算） | 历史 m5 报告未采集首次补丁尝试；新口径取门禁结论与门禁尝试 |
| M6 | 不可计算 | 0.0000（可计算） | 历史文本曾以日志口径描述 M6；新口径采集源为门禁结论与门禁尝试 |
| M7 | 不可计算 | 30.0000（可计算） | 历史 m5 报告未覆盖主流程时效；新口径按告警首次观测与 PR 就绪时间差计算 |
| M8 | 不可计算 | 0.6667（可计算） | 历史 m5 报告未覆盖主流程处置率；新口径按 v2 主流程处置与门禁证据计算 |
| M9 | 24.0000（可计算、达标） | 未验证（不可计算，达标 -） | 历史值来自夹具采样；新口径要求真实运行时连续 24 小时证据，否则为未验证 |

## 验证说明

| 项 | 命令 | 结果 |
|---|---|---|
| 全量回归 | `python -m unittest discover -s backend/tests -p "test_*.py"` | 851 用例通过（实测 2026-11-22） |
| 不变量守护 | `python -m unittest backend.tests.test_metrics_invariants` | 24 用例通过 |
| 性能预算 | `python -m unittest backend.tests.test_metrics_perf` | PERF-01 0.017s / PERF-02 `write_block_ms=1–2ms`（判据）、全量复算 0.681s（`capture_total_ms` 仅告警，不作判据）/ PERF-04 0.001s |
| 端到端复算 | `python -m unittest backend.tests.test_metrics_e2e` | 8 用例通过 |
| 离线复算 | `python scripts/recalc_metrics.py --window 2026-12 --tier PRELIMINARY --now 2027-01-06T12:00:00+00:00` | 退出码 0，报告版本递增 |

验证边界：本机无 Docker、无华为云凭据、无 redis。外部 CodeArts Check/Governance/Pipeline 均为录制桩；复算只读本地快照；
`RecalcGuard` 为进程内互斥，多实例部署需外部锁（不在本次范围）。M2 在评测运行未提供显式漏洞检出字段时按 `SOURCE_MISSING` 处理，不本地推导。

## 完成定义（DoD）对照

| DoD | 结论 | 证据 |
|---|---|---|
| 1 M4/M5/M7/M8 可计算且可下钻；M6 有门禁可计算 | 通过 | 本报告 M4=0.6667、M5=1.0、M7=30min、M8=0.6667、M6=0.0；`test_metrics_e2e` |
| 2 M9 真实连续运行证据 | 未验证 | 夹具采样不作为转正证据；本报告 M9 值列为“未验证”、达标列为“-” |
| 3 旧报告作为历史留痕保留，新报告取代误导结论 | 通过 | `docs/devlog/m5-eval-report.md` sha256 未变；本报告 M6 按门禁结论与门禁尝试采集 |
| 4 状态机、证据写入语义、main 硬约束零改动 | 通过 | `test_metrics_invariants`（17+3 迁移、main 硬拒） |
| 5 无 Docker/无云凭据/非 Git 环境可执行 | 通过 | 全部验收基于本地 `MemoryStore` + 临时目录 + 录制适配器 |

## PERF-02 性能口径（增量，2026-11-22）

### 口径分离（唯一判据）

| 量 | 起止边界 | 预算/用途 | 参与 spec 4.1-2 判定 |
|---|---|---|---|
| `write_block_ms` | capture 入口 `t0` → `store.snapshot_copy()` 返回 `t1` | `WRITE_BLOCK_BUDGET_MS=200`（模块常量，不可配置） | **是，唯一判据** |
| `capture_ms` | `t0` → 归档完成（`put_locked`/`verify` 返回） | 仅历史可比 | 否 |
| `capture_total_ms` | `t0` → 事件链校验完成 | `metrics.capture_budget_ms`（默认 200）；超限 → `CAPTURE_SLOW` 非阻断告警 | 否 |
| `segment_ms` | `clone/build/encode/archive/chain` 五段 | 归因 | 否 |

**200ms 仅作用于 `write_block_ms`（capture 临界段）**；`capture_total_ms` 超过 `capture_budget_ms` 只产生 `CAPTURE_SLOW` 非阻断告警：告警落 `MetricSnapshotRef` 与 `RecalcRun.warnings`，经 `GET /api/v1/metrics/recalc/{id}` 与 `GET /api/v1/metrics/snapshots/{id}/verify` 可检索，不改变复算成功状态、不改变 9 条指标任何字段、不进入指标报告与 9 行报告要素。

必须成立的三条等式（容差 ±1ms）：`segment_ms` 五项之和 == `capture_total_ms`；`segment_ms["clone"] == write_block_ms`；`segment_ms["build"]+["encode"]+["archive"] == capture_ms - write_block_ms`。

### 关键不变量

- `capture_ms` 仍为 `t0 → 归档完成`，语义未变，历史记录可比。
- 同一 payload 的 canonical JSON 编码次数恒为 1（`encode_count == 1`），`json.dumps` 参数未改（`ensure_ascii=False, separators=(",",":")`）。
- payload 键集合、键序与 `SNAPSHOT_SCHEMA_VERSION=1` 未变；计量字段只进元数据模型。
- 黄金四项（改造前冻结，`backend/tests/support/snapshot_golden.json`）：
  - `payload_sha256 = 3de2d3ce7489721fb69fd884dbacf27c8c14fc0e51f72c40f143e6dbcf504120`
  - `digest = 3de2d3ce7489721fb69fd884dbacf27c8c14fc0e51f72c40f143e6dbcf504120`
  - `snapshot_id = SNAP-2026-12-PRELIMINARY-3de2d3ce7489`
  - `archive_sha256 = 3de2d3ce7489721fb69fd884dbacf27c8c14fc0e51f72c40f143e6dbcf504120`（`archive_bytes = 7,265,041`）
- 改造后复测上述四项完全相等；小规模跨版本归档（`265557bc2adad7fedebe99c915dab74e0f8129c363edc0385a2385b8c2e05b3b`，19,158 bytes）在新代码下 `reused=True`、`verify().digest_match=True`。

### 3 轮 × 5 样本证据（2026-11-22）

| 轮次 | `write_block_ms` p50 / p95 / max | `capture_total_ms` p50 / p95 / max | 超预算次数 | `encode_count` | 协议 W `Δp95` | 全量回归 | 判定 |
|---|---|---|---|---|---|---|---|
| r1 | 2 / 2 / 2 ms | 143 / 148 / 148 ms | 0 | 1 | 0.0021 ms | 851 用例，failures=0，contains_skip=false | 通过 |
| r2 | 1 / 2 / 2 ms | 129 / 154 / 154 ms | 0 | 1 | 0.0016 ms | 851 用例，failures=0，contains_skip=false | 通过 |
| r3 | 1 / 2 / 2 ms | 144 / 158 / 158 ms | 0 | 1 | 0.0010 ms | 851 用例，failures=0，contains_skip=false | 通过 |

证据指针（只追加、不覆盖）：

- `.evidence/perf-repro/samples-metrics-capture-segmented-20261122T201931-r{1,2,3}.jsonl`
- `.evidence/perf-repro/measure-metrics-capture-segmented-20261122T201931-r{1,2,3}.json`
- `.evidence/perf-repro/write-block-metrics-capture-20261122T202010-r1.json`、`...20261122T202011-r2.json`、`...20261122T202012-r3.json`
- `.evidence/perf-repro/regression-20261122T202226-r1.json`、`...20261122T202327-r2.json`、`...20261122T202431-r3.json`
- `.evidence/perf-repro/round-summary-20261122T202438.json`（`decision_class="通过"`）

结论表述（仅允许此表述）：**写阻塞口径满足 spec 4.1-2；抓取端到端超预算仅告警，不构成 4.1-2 判据。**

`thread_model_note`：本结论基于单进程 `MemoryStore`（无锁）与 CPython GIL 下的调度延迟测量，不得外推至 MySQL/持久化后端。

### 验收命令

```text
python -m unittest backend.tests.test_metrics_capture_budget
python -m unittest backend.tests.test_metrics_perf
python -m unittest backend.tests.test_metrics_invariants
python -m unittest backend.tests.test_metrics_snapshot backend.tests.test_metrics_recalc backend.tests.test_metrics_report backend.tests.test_metrics_e2e
python -m unittest discover -s backend/tests -p "test_*.py"
python scripts/perf_probe.py --selftest
python scripts/perf_probe.py capture-segmented --case PERF-02/metrics-capture --env default --rounds 3 --samples 5 --write-ops 200
python scripts/perf_probe.py write-block --case PERF-02/metrics-capture --env default --write-ops 200 --round N
python scripts/perf_probe.py regression --round N
python scripts/perf_probe.py round-summary --case PERF-02/metrics-capture
```

## 回滚方案（PERF-02 增量）

**触发条件（任一满足即回滚，不做局部妥协）**

1. 黄金四项（`payload_sha256`/`digest`/`snapshot_id`/`archive_sha256`）任一不等。
2. 跨版本复用失败（改造前归档在新代码下 `reused=False` 或 `verify` 不通过）。
3. 3 轮任一轮 `write_block_ms > 200` 且无法定位为插桩错误。
4. 全量回归出现本次引入的失败。
5. 指标记录字段、条数（9 条）或幂等语义出现任何差异。

**回滚粒度（12 个文件）**

`backend/app/metrics/snapshot.py`、`backend/app/metrics/capture_health.py`、`backend/app/metrics/service.py`、`backend/app/metrics/types.py`、`backend/app/domain/models.py`、`backend/app/main.py`、`backend/app/config.py`（仅核对，未改默认值）、`backend/tests/test_metrics_perf.py`、`backend/tests/test_metrics_capture_budget.py`、`backend/tests/test_metrics_invariants.py`、`backend/tests/support/snapshot_golden*.json`（含 `snapshot_golden/`）、`scripts/perf_probe.py`。

**顺序**

1. 回退上述文件的提交（单次提交回退）。
2. 重启进程（`MemoryStore` 内存态重建，带新字段的 ref/run 不残留）。
3. 归档文件不处理：payload 与文件名未变，回滚前后均可 `verify`。
4. 证据保留，并在新汇总中标注 `supersedes`；不删除历史证据。

**回滚后复核命令**

```text
python -m unittest backend.tests.test_metrics_snapshot backend.tests.test_metrics_recalc backend.tests.test_metrics_report backend.tests.test_metrics_perf
python scripts/perf_probe.py --selftest
```

**演练记录**：在独立 `git worktree`（HEAD=改造前 `259a1fc`）执行上述复核命令，主工作区未执行任何 `git reset`；结果见 `docs/devlog/perf02-rollback-drill.md`。

## PERF-02 DoD 对照（P2-7.5）

| DoD（design 完成定义 1–5） | 结论 | 证据/命令 |
|---|---|---|
| 1 200ms 只作 `write_block_ms` 判据；端到端超预算仅告警 | 通过 | `test_metrics_perf`（`write_block_ms ≤ 200`）、`test_metrics_capture_budget`、3 轮 measure |
| 2 `capture_budget_ms` 有真实消费点（builder → ref → run.warnings → API） | 通过 | `capture_health.evaluate_capture_health`、`RecalcService`、`RecalcRun.warnings`、3 个 HTTP 响应 |
| 3 单次编码；digest/snapshot_id/归档字节/reused/9 条指标不变 | 通过 | 黄金四项相等、跨版本复用、`encode_count==1`、`test_metrics_recalc` |
| 4 3 轮 × 5 样本 + 协议 W + 全量回归齐备，按预置规则判定 | 通过 | `round-summary-20261122T202438.json`、3 轮 regression（851/0/0） |
| 5 既有用例零回归；`MetricReport` 与对外报告内容不受影响 | 通过 | 全量回归 851 用例 OK；`test_metrics_report`、`test_metrics_e2e`、`test_metrics_invariants` |
