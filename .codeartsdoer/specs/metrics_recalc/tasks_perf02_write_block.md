# PERF-02 测量口径纠正与抓取预算落地 · 增量编码任务清单

> 文档性质：**增量任务清单**，只覆盖 PERF-02 增量改造，不替代既有基线文档。
> 设计依据：`.codeartsdoer/specs/metrics_recalc/design_perf02_write_block.md`（800 行）。
> 需求基线：`.codeartsdoer/specs/metrics_recalc/spec.md`（只读）、`.codeartsdoer/specs/metrics_recalc/design.md`（只读）。
> 任务基线：`.codeartsdoer/specs/metrics_recalc/tasks.md`（**只读，本文件不覆盖它**）；既有 60 项任务状态保持不变。
> 代码基线：`main@259a1fc`；本文件只做规划，**不修改任何代码**。
> 组织方式：严格对齐设计 2.6 的 S1–S7 实施顺序，垂直按"可验收能力"切分，不按 Controller/Service/DAO 技术层切分。

---

## 0. 全局约束与验收约定

### 0.1 不可放宽的阈值与数据规模（硬门，评审逐条核对）

| 编号 | 量 | 冻结值 | 守护任务 | 说明 |
|---|---|---|---|---|
| F-01 | 写阻塞预算 | `WRITE_BLOCK_BUDGET_MS = 200` | P2-2.1、P2-6.1 | 新增模块常量，**不可配置、无配置键**；唯一判据作用于 `write_block_ms` |
| F-02 | 抓取告警预算 | `metrics.capture_budget_ms` 默认 `200`，下界 `1` | P2-4.3、P2-6.1 | 默认值与校验不变；仅新增消费点，不得新增 `write_block_budget_ms` 配置键 |
| F-03 | PERF-01 | 50 条 Issue 全量复算 `≤ 5s` | P2-6.1 | 数值不变 |
| F-04 | PERF-02 复算 | 1100 Issue / 12000 事件全量复算 `≤ 60s` | P2-5.1、P2-6.1 | 数值不变 |
| F-05 | PERF-04 | 报告生成 `≤ 3s` | P2-6.1 | 数值不变 |
| F-06 | 性能数据规模 | `1000` 完整链路 Issue + `100` 复现失败 Issue = `1100`；`1000` run × `12` event = `12000` | P2-1.1、P2-6.1 | `event_count == 12000` 必须保留；禁止下调 |
| F-07 | 编码次数 | 单次 capture 内同一 payload canonical 编码次数 `== 1` | P2-2.2、P2-5.2 | mock 计数 + 落库字段双证 |
| F-08 | 并发写阻塞佐证 | 每轮 `200` 次写操作；`Δp95 ≤ 200ms`；`event_id_set_equal=True` | P2-7.1、P2-7.4 | 协议 W，结论必须附 `thread_model_note` |
| F-09 | 多轮证据 | `3` 轮 × `5` 样本；`samples < 5` 必须拒绝 | P2-7.1、P2-7.2 | 沿用 `SAMPLE_COUNT_INSUFFICIENT` 风格 |
| F-10 | 快照格式 | `SNAPSHOT_SCHEMA_VERSION == 1`；payload 键集合与键序不变 | P2-2.3、P2-6.1 | 新增任何 payload 字段即失败 |
| F-11 | 分段自洽容差 | 取整误差 `≤ 1ms` | P2-2.1、P2-3.3 | 毫秒一律向下取整 |

### 0.2 测量口径裁定（编码阶段唯一口径，含设计内部表述修正）

| 量 | 起止边界（唯一口径） | 预算/用途 | 参与 4.1-2 判定 |
|---|---|---|---|
| `write_block_ms` | `t0`（capture 入口）→ `t1`（`store.snapshot_copy()` 返回） | `WRITE_BLOCK_BUDGET_MS=200` 硬断言 | **是，唯一判据** |
| `capture_ms` | `t0` → `t4`（`put_locked`/`verify` 返回，归档完成） | 仅历史可比 | 否 |
| `capture_total_ms` | `t0` → `t5`（`_chains_valid` 计算完成） | `capture_budget_ms` 比较，超限告警 | 否 |
| `segment_ms` | `clone=t1-t0`、`build=t2-t1`、`encode=t3-t2`、`archive=t4-t3`、`chain=t5-t4` | 归因 | 否 |

**必须成立的三条等式（测试硬断言，容差 ±1ms）**：
1. `segment_ms` 五项之和 `== capture_total_ms`；
2. `segment_ms["clone"] == write_block_ms`；
3. `segment_ms["build"] + segment_ms["encode"] + segment_ms["archive"] == capture_ms - write_block_ms`。

> **口径修正说明（编码前必须遵守）**：设计 2.1.3(1) 第三条写作 "`build+encode+archive == capture_ms`"，但设计 2.1.3(1) 表格与 2.2.1 时序同时规定 `capture_ms` 为 `t0→归档完成`（含 clone），两者不能同时成立。本清单按**既有语义优先**裁定为 `capture_ms - write_block_ms`，理由：`capture_ms` 是既有落库字段，历史记录必须保持可比（spec 6.4/6.2 不变量）。若实现方坚持原式，必须先修订设计文档，不得在代码中改 `capture_ms` 语义。

**时序边界取点**：全部使用 `time.perf_counter_ns()`；毫秒换算 `int((t_end - t_start) // 1_000_000)`（向下取整），避免 199.6ms 被报成 200ms 而误触发超预算。

### 0.3 禁止的"修绿"手段（评审硬门，出现即判不通过）

1. 修改 `WRITE_BLOCK_BUDGET_MS`、`capture_budget_ms` 默认值、PERF-01/02/04 门槛、F-06 数据规模常量；
2. 新增 `time.sleep`、删除断言、新增 `skipIf` 环境开关、扩大既有 skip 范围、减少 Issue/事件数；
3. 只改测试不改实现（本轮必须是"实现补齐 + 断言对象纠正"成对提交）；
4. 删除 `capture_total_ms` 观测后宣称"不再有性能问题"——必须同时给出 `write_block_ms` 结构断言与协议 W 证据；
5. 在 payload 内新增计量字段、给 `json.dumps` 加 `sort_keys/indent/default`、改 `separators`/`ensure_ascii`；
6. 把告警写入 `Metric`/`MetricReport`/9 行报告要素。

### 0.4 命令与环境约定

1. 全部命令在仓库根 `E:\shuangxingxi\ICT_agent` 执行。
2. 测试框架以 `unittest` 为准（本机无 pytest，沿用既有 tasks.md 0.B 约定）：
   - 单文件：`python -m unittest backend.tests.test_xxx`；
   - 多文件：`python -m unittest backend.tests.test_a backend.tests.test_b`；
   - 全量：`python -m unittest discover -s backend/tests -p "test_*.py"`。
3. 无 Docker、无云凭据、无 redis：全部用进程内 `MemoryStore` + `tempfile.TemporaryDirectory` + `LocalEvidenceStore`。
4. `scripts/perf_probe.py` 的 `immutable` 清单含 `backend/app/metrics/snapshot.py`、`backend/app/config.py`、`backend/tests/test_metrics_perf.py`、`docs/devlog/metrics-report.md`：**产品/测试/报告改动一律由开发流程完成，禁止借探针就地改绿**；探针只写 `.evidence/perf-repro/`。
5. 本机 `REQUIRED` 现有 8 类记录、`--selftest` 断言 `schema_hits == 8`（实测口径，非设计文档所称"9 类"）：新增记录类型不得加入 `REQUIRED`，不得改动该计数断言。
6. 时间与随机性：测试一律固定 `NOW = datetime(2027,1,6,12,0,tzinfo=timezone.utc)`，禁止 `sleep` 等待。

### 0.5 任务总览与依赖图

| 阶段 | 对应设计步骤 | 子任务数 | 依赖 | 阶段完成标志 | 主要验证命令 |
|---|---|---|---|---|---|
| S1 冻结改造前黄金基线 | S1 | 4 | 当前 HEAD | 黄金四项 + 小规模实体归档冻结，二次采集一致 | `python scripts/capture_snapshot_golden.py ...`；`python -m unittest backend.tests.test_metrics_snapshot` |
| S2 单次编码 + 计量值与告警纯函数 | S2 | 3 | S1 | 黄金四项相等；`encode_count==1`；纯函数用例全绿 | `python -m unittest backend.tests.test_metrics_capture_budget` |
| S3 模型字段、回填与装配注入 | S3 | 6 | S2 | 旧 ref/run 可读；ref 计量与告警落库；API 字段透出 | `python -m unittest backend.tests.test_metrics_capture_budget backend.tests.test_metrics_api backend.tests.test_metrics_recalc` |
| S4 用例对象纠正与告警非阻断 | S4 | 3 | S3 | `write_block_ms ≤ 200` 硬断言生效；无端到端硬门槛；告警不污染口径 | `python -m unittest backend.tests.test_metrics_perf` |
| S5 不变量与阈值/规模守护 | S5 | 3 | S4 | 常量漂移即失败；默认环境无 skip | `python -m unittest backend.tests.test_metrics_invariants` |
| S6 取证脚本分段与 3 轮汇总 | S6 | 3 | S5 | `--selftest` 全 PASS；3 轮证据落盘 | `python scripts/perf_probe.py --selftest`；`python scripts/perf_probe.py capture-segmented ...` |
| S7 多轮证据判定、文档口径与回滚 | S6/S7 | 4 | S6 | 3×5 样本 + 写阻塞 + 全量回归按预置规则判定；回滚演练记录 | `python -m unittest discover -s backend/tests -p "test_*.py"` |

**依赖图（串行主线，禁止跳步）**

```text
S1 ──▶ S2 ──▶ S3 ──▶ S4 ──▶ S5 ──▶ S6 ──▶ S7
                   │                       ▲
                   └── 模型/API 兼容回归 ───┘（S3.6 完成后即可并行启动 S6.1/S6.2 的脚本开发）
```

> S1 必须在任何产品代码改动**之前**执行。S1 一旦冻结，黄金 fixture 视为只读，后续任何任务不得修改其数值（只能新增字段并同步评审记录）。

---

## 1. 阶段 S1：冻结改造前黄金基线（对应设计 S1）

**本阶段不得改动产品代码**：`backend/app/**` 一律不修改；只允许新增/修改 `backend/tests/support/**` 与新增一次性采集脚本。

### P2-1.1 抽出 PERF-02 规模夹具并固化规模常量
- [x] 新增 `backend/tests/support/perf_fixture.py`，导出常量 `PERF02_FULL_ISSUES=1000`、`PERF02_REPRO_FAILED=100`、`PERF02_ISSUES=1100`、`PERF02_RUNS=1000`、`EVENTS_PER_RUN=12`、`PERF02_EVENTS=12000`，并提供 `build_perf02_store(now=NOW) -> tuple[MemoryStore, dict]`：以 `seed_synthetic(store, "2026-12", full=1000, repro_failed=100)` 建 Issue/链路记录，再对 1000 个 `ISF-*` 各建 1 个 `Run`（`run_id=f"RUN-{issue_id}"`、`started_at=now-2h`、`deadline_at=now`）与 12 条 `Event`（`seq` 1..12、`event_type=INGEST`、`actor="perf"`）；**每条 `Event` 必须显式传 `occurred_at=now - timedelta(minutes=5)`**，不得依赖 `Event.occurred_at` 的 `utc_now` 默认值
  - 交付物：`backend/tests/support/perf_fixture.py`
  - 完成标准：`build_perf02_store()` 返回 `issue_count=1100`、`event_count=12000`、`run_count=1000`；**跨进程可重建**——两次独立调用生成的 store 经 `SnapshotBuilder.capture()` 得到的 `digest` 完全相同（这是黄金基线成立的必要前提）
  - 验证命令：`python -m unittest backend.tests.test_metrics_snapshot`（既有确定性用例不回归）＋首次自检：`python -c "import sys;sys.path.insert(0,'backend');from tests.support.perf_fixture import build_perf02_store;s,_=build_perf02_store();print(len(s.issues),len(s.runs),sum(len(v) for v in s.events.values()))"` 输出 `1100 1000 12000`
  - 不可放宽：`1100/1000/12/12000` 为冻结值；**不得**因"加速"下调
  - 说明：现有 `test_metrics_perf.py:78-97` 的 `Event` 未传 `occurred_at`，跨进程不可复现；本任务显式固定时间属于黄金可重建的最小必要修正，事件条数不变
  - 需求：RQ-5（不得削减数据量）；依赖：无

### P2-1.2 新增一次性黄金采集脚本（只读产品代码、只写测试夹具）
- [x] 新增 `scripts/capture_snapshot_golden.py`，参数 `--window`（默认 `2026-12`）、`--tier`（默认 `PRELIMINARY`）、`--out`（默认 `backend/tests/support/snapshot_golden.json`）、`--archive-dir`（默认 `backend/tests/support/snapshot_golden/`）、`--small`（小规模实体归档模式）；流程：`build_perf02_store()` → `SnapshotBuilder(store, LocalEvidenceStore(tmp))` → `capture()` → 采集 `payload` canonical bytes 的 `sha256` 与长度、`digest`、`snapshot_id`、`archive_sha256`、`archive_bytes`、`record_counts`、`event_count`、`fixture` 构造参数、`code_revision`（`git rev-parse HEAD` 只读查询）、`captured_at`；脚本对产品源码、`docs/devlog/**`、`.evidence/git-baseline/**` 一律拒绝写入
  - 交付物：`scripts/capture_snapshot_golden.py`；`backend/tests/support/snapshot_golden.json`
  - 完成标准：生成 `snapshot_golden.json` 且四项目标值齐全（`payload_sha256`、`digest`、`snapshot_id`、`archive_sha256`）；JSON 内含 `fixture.issues=1100`、`fixture.events=12000`、`fixture.events_per_run=12`；`code_revision == 259a1fc` 前缀可追溯
  - 验证命令：`python scripts/capture_snapshot_golden.py --window 2026-12 --tier PRELIMINARY` 退出码 0；重复执行到**不同输出目录**后四项目标值与前次完全相等（`captured_at` 允许不同）
  - 不可放宽：payload 键集合/键序、`SNAPSHOT_SCHEMA_VERSION=1`；脚本不得读取或改写被测实现之外的业务数据
  - 需求：RQ-4、RQ-6（字节级等价基线）；依赖：P2-1.1

### P2-1.3 冻结小规模实体归档文件（跨版本复用的实物载体）
- [x] 用 P2-1.2 的 `--small` 模式生成最小可复现 fixture（`5` Issue、`1` run、`12` event）的改造前归档文件，落到 `backend/tests/support/snapshot_golden/`，并生成 `backend/tests/support/snapshot_golden_small.json` 记录其 `digest`、`snapshot_id`、`archive_sha256`、`archive_bytes`、文件相对路径与 `fixture` 构造参数
  - 交付物：`backend/tests/support/snapshot_golden/SNAP-2026-12-PRELIMINARY-<digest12>.json`、`backend/tests/support/snapshot_golden_small.json`
  - 完成标准：实体归档文件 `< 1 MB`；其 `sha256` 与 JSON 记录一致；文件内容为改造前实现产出的原始字节（文件头 `{"schema_version":1,...`）
  - 验证命令：`python scripts/capture_snapshot_golden.py --small` 退出码 0；`git hash-object`/`sha256sum` 方式复核记录值一致（只读）
  - 不可放宽：小规模实体归档只用于"格式复用"证据，**不替代** F-06 的 1100/12000 规模断言
  - 需求：RQ-4、RQ-6；依赖：P2-1.2

### P2-1.4 黄金基线自校验（改造前最后一道闸）
- [x] 在 `backend/tests/test_metrics_capture_budget.py` 建立前，先用一次性自检证明黄金 fixture 可稳定重建；并把 `snapshot_golden.json` / `snapshot_golden_small.json` 设为测试只读输入（测试只 `read_text`，任何用例不得写入该目录）
  - 交付物：黄金 fixture 只读性说明（写入 `snapshot_golden.json` 的 `readonly=true` 字段与文件头注释性字段）
  - 完成标准：连续两次采集的四项目标值全等；`snapshot_golden/` 目录下文件在测试运行后 `sha256` 不变（可用测试断言，S2.3 落地）
  - 验证命令：连续两次执行 P2-1.2 命令并比对；`python -m unittest backend.tests.test_metrics_snapshot`
  - 需求：RQ-6；依赖：P2-1.2、P2-1.3

---

## 2. 阶段 S2：单次编码 + 计量值对象与告警纯函数（对应设计 S2）

**本阶段不得改动**：payload 结构、`SNAPSHOT_SCHEMA_VERSION`、`_exists`/`reused` 语义、链校验算法、任何模型字段（ref 字段在 S3 才加）。

### P2-2.1 新增 `metrics/capture_health.py`：计量值对象与告警纯函数
- [x] 新增 `backend/app/metrics/capture_health.py`：定义模块常量 `WRITE_BLOCK_BUDGET_MS=200`、`CAPTURE_WARNINGS=("WRITE_BLOCK_EXCEEDED","CAPTURE_SLOW")`；定义 `@dataclass(frozen=True) CaptureMetrics`（字段 `write_block_ms/capture_ms/capture_total_ms/encode_count/segment_ms`）与 `CaptureMetrics.from_ns(t0,t1,t2,t3,t4,t5,encode_count)`（毫秒向下取整、边界单调校验、`encode_count>=1`、`segment_ms` 固定 5 键）；定义纯函数 `evaluate_capture_health(metrics, capture_budget_ms) -> list[str]`（`write_block_ms > 200` → `WRITE_BLOCK_EXCEEDED`；`capture_total_ms > capture_budget_ms` → `CAPTURE_SLOW`；固定顺序、不重复、不抛业务异常；非法预算 `<1` 抛 `ValueError`）
  - 交付物：`backend/app/metrics/capture_health.py`
  - 完成标准：纯函数无 IO、无时钟、无全局可变量；`CaptureMetrics.from_ns` 非单调边界抛 `ValueError`
  - 验证命令：`python -m unittest backend.tests.test_metrics_capture_budget`（P2-2.3 建文件后生效）
  - 不可放宽：F-01（200 常量，不读配置）、F-11（向下取整，容差 ≤1ms）
  - 需求：RQ-1、RQ-2、RQ-3；依赖：P2-1.1

### P2-2.2 `snapshot.py` 合并为单次 canonical 编码
- [x] 在 `backend/app/metrics/snapshot.py` 新增模块级 `encode_payload(payload: dict) -> bytes`（唯一实现 `json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")`）；`capture()` 内只调用一次，`digest = sha256(bytes).hexdigest()`，归档 `put_locked(key, bytes)` 写同一字节串；删除 `_digest(payload)` 的第二次 `dumps`（`_digest` 若保留则改为接收 `bytes`，全仓无其他调用点）；`capture()` 内维护本地 `encode_count`（恒为 1）**不写入 payload、不写入 ref**
  - 交付物：改造后的 `backend/app/metrics/snapshot.py`
  - 完成标准：单次 capture 内 `json.dumps` 对同一 payload 仅调用 1 次；`digest`、`snapshot_id`、归档字节与 P2-1.2 冻结值逐字节相等；payload 键集合与黄金 fixture 相等
  - 验证命令：`python -m unittest backend.tests.test_metrics_snapshot backend.tests.test_metrics_capture_budget`
  - 不可放宽：F-07、F-10；禁止新增 `sort_keys/indent/default/ensure_ascii=True`、禁止改 `separators`、禁止流式 `json.dump`
  - 需求：RQ-4、RQ-6；依赖：P2-2.1

### P2-2.3 建立 `test_metrics_capture_budget.py` 基础用例（纯函数 + 黄金等价 + 单次编码）
- [x] 新增 `backend/tests/test_metrics_capture_budget.py`（沿用现有 `sys.path.insert`、`unittest`、`tempfile` 风格），首版覆盖：① 黄金四项（`payload_sha256/digest/snapshot_id/archive_sha256`）与冻结值相等；② `payload` 键集合与黄金 json 记录相等（NB-06 反例：人为加键则失败）；③ `encode_payload` 等价性（`sha256(encode_payload(payload)) == digest`）；④ 单次编码 double-check：`unittest.mock.patch("app.metrics.snapshot.json.dumps", wraps=json.dumps)` 记录调用次数 `== 1`；⑤ `CaptureMetrics.from_ns` 自洽三条等式（容差 ≤1ms）；⑥ 告警纯函数边界（201/200/预算内/预算超/双超顺序/非法预算）；⑦ 非单调边界与 `encode_count=0` 抛 `ValueError`
  - 交付物：`backend/tests/test_metrics_capture_budget.py`
  - 完成标准：文件用例数 `≥ 8`；不含 `pytest` import、不含 `time.sleep`、不含新增 `skipIf`；全部通过
  - 验证命令：`python -m unittest backend.tests.test_metrics_capture_budget`
  - 不可放宽：F-07、F-11；黄金值不得在测试中被"修正"（只允许读取）
  - 需求：RQ-3、RQ-4、RQ-6；依赖：P2-1.2、P2-1.3、P2-2.1、P2-2.2

---

## 3. 阶段 S3：模型字段、回填与装配注入（对应设计 S3）

**本阶段不得改动**：既有字段语义、`extra="forbid"`、`Metric` 互斥校验、两段式事务与 9 条记录写入顺序。

### P2-3.1 `MetricSnapshotRef` 新增计量字段与 `RecalcRun.warnings`
- [x] 在 `backend/app/domain/models.py` 的 `MetricSnapshotRef` 新增 `write_block_ms: int = 0`、`write_block_budget_ms: int = 200`、`write_block_exceeded: bool = False`、`capture_total_ms: int = 0`、`capture_budget_ms: int = 200`、`capture_slow: bool = False`、`segment_ms: dict[str,int] = {}`、`encode_count: int = 1`（全部带默认值、`ge=0` 约束）；新增 `model_validator(mode="after")` 不变式：`write_block_exceeded == (write_block_ms > write_block_budget_ms)`、`capture_slow == (capture_total_ms > capture_budget_ms)`、`capture_total_ms >= capture_ms`、`segment_ms` 非空时键集合恒为 `{clone,build,encode,archive,chain}` 且值 `≥0`（为空字典时允许，保证旧 ref 可读）；`RecalcRun` 新增 `warnings: list[str] = []`
  - 交付物：改造后的 `backend/app/domain/models.py`
  - 完成标准：旧 ref JSON（无新字段）`model_validate` 成功且默认值正确；未知字段仍被拒（`extra="forbid"`）；布尔与数值不一致时构造失败；`RecalcRun` 旧记录可读
  - 验证命令：`python -m unittest backend.tests.test_domain_models backend.tests.test_metrics_capture_budget`
  - 不可放宽：全部字段必须有默认值（RP-10）；不得把 `warnings` 取值域校验做成 `domain → metrics` 依赖（取值域由纯函数与不变量测试守护）
  - 需求：RQ-2、RQ-6；依赖：P2-2.1

### P2-3.2 `SnapshotBuilder` 注入预算并回填计量与告警
- [x] 在 `backend/app/metrics/snapshot.py` 的 `SnapshotBuilder.__init__` 新增 `capture_budget_ms: int = 200`（构造期校验 `<1` 抛 `ValueError`）与可选 `clock_ns=time.perf_counter_ns`；`capture()` 按 0.2 的六个边界取时、构造 `CaptureMetrics`、调用 `evaluate_capture_health(metrics, self.capture_budget_ms)`；把计量字段与布尔结论回填 `MetricSnapshotRef`；`SnapshotEnvelope` 新增 `metrics: CaptureMetrics | None = None`（进程内可验证出口，**不进 payload、不单独持久化**）；`capture()` 签名不变
  - 交付物：改造后的 `backend/app/metrics/snapshot.py`
  - 完成标准：`ref` 8 个计量字段与 `envelope.metrics` 一一对应；`ref.write_block_budget_ms == 200`；`ref.capture_budget_ms == 构造参数`；`ref.write_block_exceeded/capture_slow` 与 `envelope.metrics` 判定一致；黄金四项仍相等
  - 验证命令：`python -m unittest backend.tests.test_metrics_capture_budget backend.tests.test_metrics_snapshot`
  - 不可放宽：`snapshot_copy()` 是唯一触碰 store 容器的调用；计时只在 6 个边界取一次（RP-07）
  - 需求：RQ-1、RQ-2、RQ-3；依赖：P2-2.1、P2-2.2、P2-3.1

### P2-3.3 补充分段/告警单测（口径自洽与边界）
- [x] 在 `backend/tests/test_metrics_capture_budget.py` 增补：① `segment_ms["clone"] == write_block_ms`；② 五项和与 `capture_total_ms` 差值 `≤1ms`；③ `build+encode+archive == capture_ms - write_block_ms`；④ 注入 `capture_budget_ms=1` 时 `capture_slow=True`、告警列表为 `["CAPTURE_SLOW"]`（或含 `WRITE_BLOCK_EXCEEDED` 时顺序在前）；⑤ `capture_budget_ms=0/ -1` 构造抛 `ValueError`；⑥ 同一 store 连续两次 capture → `reused=True`、两次 `digest` 相同、归档文件字节与 `mtime` 不变
  - 交付物：测试用例增补
  - 完成标准：用例全部通过；失败信息包含具体等式名
  - 验证命令：`python -m unittest backend.tests.test_metrics_capture_budget`
  - 不可放宽：F-11 容差
  - 需求：RQ-3；依赖：P2-3.2

### P2-3.4 `RecalcService` 注入预算、汇总告警到 run/result
- [x] 在 `backend/app/metrics/service.py`：默认 builder 构造改为 `SnapshotBuilder(store, evidence, capture_budget_ms=self.config.metrics.capture_budget_ms)`（显式传入 builder 时以其配置为准）；事务内 `put_snapshot(envelope.ref)` 与 `update_recalc(finished)` 时把 `envelope.ref` 对应告警码写入 `RecalcRun.warnings`（顺序固定、去重，不重算）；`RecalcResult` 返回同一列表；失败路径 `_mark_failed` 不写 `warnings`
- [x] 在 `backend/app/metrics/types.py` 的 `RecalcResult` 末尾新增 `warnings: list[str] = field(default_factory=list)`（保持既有位置参数兼容）
  - 交付物：改造后的 `backend/app/metrics/service.py`、`backend/app/metrics/types.py`
  - 完成标准：`config.metrics.capture_budget_ms=1` 注入后复算 `status=SUCCESS`、`run.warnings==["CAPTURE_SLOW"]`、`result.warnings` 相同；9 条指标记录与默认预算场景逐字段相等（`computed_at/recalc_id/last_success_at` 除外）；失败复算 `warnings==[]`
  - 验证命令：`python -m unittest backend.tests.test_metrics_recalc backend.tests.test_metrics_api backend.tests.test_metrics_capture_budget`
  - 不可放宽：告警不改变 `RecalcStatus`、不改变 9 条指标任一字段、不改变报告结论（RQ-6）
  - 需求：RQ-2、RQ-6；依赖：P2-3.2

### P2-3.5 HTTP 透出：3 个响应只增字段
- [x] 在 `backend/app/main.py`：`POST /api/v1/metrics/recalc` 响应增 `warnings`；`GET /api/v1/metrics/recalc/{recalc_id}` 响应增 `warnings`；`GET /api/v1/metrics/snapshots/{snapshot_id}/verify` 响应增 `capture_ms/capture_total_ms/write_block_ms/write_block_budget_ms/write_block_exceeded/capture_budget_ms/capture_slow/encode_count/segment_ms`（来自 `box.store.get_snapshot(snapshot_id)`；`cached is None` 时全部为 `null`）；**`_metric_payload` 一个字段都不加**
  - 交付物：改造后的 `backend/app/main.py`
  - 完成标准：三个端点响应为旧字段超集；`warnings` 缺省为 `[]`；`verify` 在无 cached 且 `expected_digest` 合法时仍 `200` 且计量字段为 `null`；既有错误码（`EVIDENCE_MISSING`/`SNAPSHOT_INTEGRITY`/`RECALC_CONFLICT`）不变
  - 验证命令：`python -m unittest backend.tests.test_metrics_api backend.tests.test_m4_dashboard backend.tests.test_metrics_capture_budget`
  - 不可放宽：接口不变量 1–4（不得用告警改写指标状态；不得新增错误码）；`warnings` 取值域仅两个稳定码
  - 需求：RQ-2；依赖：P2-3.1、P2-3.4

### P2-3.6 模型/API 兼容回归（旧数据可读、旧客户端不受影响）
- [x] 在 `backend/tests/test_metrics_capture_budget.py` 增补兼容用例：① 旧 `MetricSnapshotRef`（无计量字段）反序列化 → 默认值、`capture_slow=False`、`write_block_exceeded=False`；② 旧 `RecalcRun`（无 `warnings`）→ `warnings==[]`；③ 通过 `TestClient` 读取旧 run 的 `GET /api/v1/metrics/recalc/{id}` → `warnings==[]`；④ 读取既有 `test_metrics_snapshot`/`test_metrics_recalc` 生成的记录 → 无异常、无告警误报
  - 交付物：测试用例增补
  - 完成标准：用例全部通过；`python -m unittest backend.tests.test_metrics_snapshot backend.tests.test_metrics_recalc backend.tests.test_metrics_api backend.tests.test_metrics_report` 全绿
  - 验证命令：同上命令
  - 不可放宽：历史数据不可改写（既有 tasks.md 0.A 不变式）
  - 需求：RQ-6；依赖：P2-3.5

---

## 4. 阶段 S4：用例对象纠正与告警非阻断（对应设计 S4）

**本阶段不得改动**：F-06 数据规模、`event_count==12000`、60s 门槛、`VERIFIX_SKIP_PERF` 既有跳过机制。

### P2-4.1 PERF-02 断言对象纠正（数值与规模不变）
- [x] 在 `backend/tests/test_metrics_perf.py`：把 `assertLess(capture_elapsed, 0.2)` 替换为 `assertLessEqual(envelope.ref.write_block_ms, 200)`；新增 `assertEqual(envelope.ref.encode_count, 1)`、`assertEqual(envelope.ref.capture_budget_ms, 200)`；把性能门槛抽为模块常量 `PERF01_LIMIT_S=5.0`、`PERF02_LIMIT_S=60.0`、`PERF02_RUNS=1000`、`PERF02_EVENTS=12000`、`PERF_WRITE_BLOCK_MS=200`（供 S5 不变量测试引用）；改用 `tests.support.perf_fixture.build_perf02_store()` 构造 store（规模与结构不变）；打印 `write_block_ms` 与 `segment_ms` 五项
  - 交付物：改造后的 `backend/tests/test_metrics_perf.py`
  - 完成标准：PERF-02 用例断言 1100 Issue / 12000 事件、`write_block_ms ≤ 200`、`encode_count == 1`、全量复算 `< 60s`；**不再存在**对 `capture_elapsed` 的 `< 0.2` 断言，也不得换成任何其他端到端硬门槛；PERF-01/04/READ-01 断言数值不变
  - 验证命令：`python -m unittest backend.tests.test_metrics_perf`
  - 不可放宽：F-03/F-04/F-05/F-06/F-07；`test_metrics_perf.py` 在 `perf_probe.immutable` 内 → 只能由开发流程改，探针不得写
  - 需求：RQ-1、RQ-3、RQ-5；依赖：P2-3.2、P2-3.4

### P2-4.2 告警"非阻断但可见"用例
- [x] 在 `backend/tests/test_metrics_capture_budget.py` 增补 NB-01 全链路用例：同一 store 分别以 `capture_budget_ms=200` 与 `=1` 复算 → 后者 `run.warnings==["CAPTURE_SLOW"]`、`ref.capture_slow=True`、`status=SUCCESS`；两次的 9 条 `Metric` 记录在 `value/computable/reason_code/numerator/denominator/covered_count/excluded_count/channel_excluded_count/not_applicable_count/snapshot_digest/definition_version/trial/unverified` 上逐字段相等；`snapshot_id` 相同（payload 未变）
  - 交付物：测试用例增补
  - 完成标准：用例通过；断言信息明确区分"告警"与"指标口径"
  - 验证命令：`python -m unittest backend.tests.test_metrics_capture_budget`
  - 不可放宽：RP-04（告警不得污染口径）
  - 需求：RQ-2、RQ-6；依赖：P2-3.4

### P2-4.3 结构不变量：临界段唯一且写阻塞上界成立
- [x] 在 `backend/tests/test_metrics_capture_budget.py` 增补：用代理 store 包装 `MemoryStore`，记录 `snapshot_copy()` 调用次数与 `snapshot_copy()` 之后对 `issues/alerts/verdicts/proofs/patches/gate_results/dispositions/runs/events/*` 的属性访问次数，断言调用次数 `== 1` 且之后访问次数 `== 0`；同时断言 `segment_ms["clone"] == write_block_ms`、`write_block_budget_ms == 200`
  - 交付物：测试用例增补
  - 完成标准：用例通过；人为在 capture 后追加 `self.store.issues` 访问时用例必须失败（RP-03 回归探针）
  - 验证命令：`python -m unittest backend.tests.test_metrics_capture_budget`
  - 不可放宽：F-01、接口不变量（`snapshot_copy` 唯一临界段）
  - 需求：RQ-1、RQ-3；依赖：P2-3.2

---

## 5. 阶段 S5：不变量与阈值/规模守护（对应设计 S5）

### P2-5.1 阈值、默认预算与数据规模常量守护
- [x] 扩展 `backend/tests/test_metrics_invariants.py`，新增 `CaptureBudgetInvariantTest`：断言 `capture_health.WRITE_BLOCK_BUDGET_MS == 200`、`MetricsConfig().capture_budget_ms == 200`、`MetricsConfig` 字段中**不存在** `write_block_budget_ms`、`capture_budget_ms=0` 触发既有校验错误、`SNAPSHOT_SCHEMA_VERSION == 1`；import 并断言 `tests.test_metrics_perf.PERF01_LIMIT_S == 5.0`、`PERF02_LIMIT_S == 60.0`、`PERF04_LIMIT_S == 3.0`、`PERF02_EVENTS == 12000`、`PERF_WRITE_BLOCK_MS == 200`；断言 `perf_fixture` 的 `PERF02_ISSUES == 1100`、`PERF02_RUNS == 1000`、`EVENTS_PER_RUN == 12`
  - 交付物：改造后的 `backend/tests/test_metrics_invariants.py`
  - 完成标准：故意把任一常量改成别的值（本地临时改动验证后还原）时用例失败，失败信息含常量名与期望值
  - 验证命令：`python -m unittest backend.tests.test_metrics_invariants`
  - 不可放宽：F-01…F-06、F-10
  - 需求：RQ-5；依赖：P2-4.1

### P2-5.2 合规守护（无 sleep / 无新增 skip / 无规模下调）
- [x] 在 `test_metrics_invariants.py` 增补：① 默认环境（未设 `VERIFIX_SKIP_PERF`）下 `tests.test_metrics_perf.SKIP is False`，且 `PerfTest.test_perf02_thousand_issues_and_twelve_thousand_events` 不存在 `__unittest_skip__` 标记（NB-08）；② 对 `backend/tests/test_metrics_capture_budget.py`、`backend/tests/test_metrics_invariants.py` 做源码扫描断言不含 `time.sleep(`，且 `skipIf` 出现次数不超过既有基线（`test_metrics_perf.py` 现有 2 处）；③ 断言 `build_perf02_store()` 的 `issue_count==1100`、`event_count==12000`（NB-09）
  - 交付物：测试用例增补
  - 完成标准：用例通过；新增任何 `sleep`/`skip`/规模下调都会失败
  - 验证命令：`python -m unittest backend.tests.test_metrics_invariants`
  - 不可放宽：0.3 全部禁止项
  - 需求：RQ-5；依赖：P2-5.1

### P2-5.3 报告与对外口径隔离守护
- [x] 在 `test_metrics_invariants.py` 增补：① `MetricReport`/报告行结构无 `warnings`/`write_block_ms` 等性能字段；② 同一 store 在 `capture_budget_ms=1` 与 `=200` 下生成的报告 `content_digest` 相同、`version` 递增行为不变；③ `GET /api/v1/metrics` 返回行不包含任何性能告警字段（`_metric_payload` 键集合冻结）；④ 既有 `docs/devlog/m5-eval-report.md` 前后 `sha256` 不变
  - 交付物：测试用例增补
  - 完成标准：用例通过；`python -m unittest backend.tests.test_metrics_report backend.tests.test_metrics_api backend.tests.test_metrics_e2e` 全绿
  - 验证命令：同上命令
  - 不可放宽：RP-04、接口不变量 1
  - 需求：RQ-6；依赖：P2-5.1

---

## 6. 阶段 S6：取证脚本分段采集与 3 轮汇总（对应设计 S6）

**本阶段不得改动**：`REQUIRED` 现有 8 类 schema、`--selftest` 的 `schema_hits == 8` 断言、`immutable` 清单、`judge()` 既有判定语义、既有命令输出格式。

### P2-6.1 新增 `capture-segmented` 子命令（分段计量 3 轮 × 5 样本）
- [x] 在 `scripts/perf_probe.py` 新增子命令 `capture-segmented`，参数 `--case`（必须 `PERF-02/metrics-capture`）、`--env`（`default|clean`）、`--rounds`（默认 3，`<3` 报 `ROUNDS_INSUFFICIENT`）、`--samples`（默认 5，`<5` 报 `SAMPLE_COUNT_INSUFFICIENT`）、`--write-ops`（默认 200）、`--out`；每样本写 `samples-metrics-capture-segmented-{stamp}-r{n}.jsonl`（字段 `sample_index/write_block_ms/capture_ms/capture_total_ms/segment_ms/encode_count/over_capture_budget`）；每轮写 `measure-metrics-capture-segmented-{stamp}-r{n}.json`（`write_block_ms` 与 `capture_total_ms` 各自 p50/p95/max、超预算次数、`data_scale`、`environment`、`fingerprint_sha256`、`measurement_scope` 含 `write_block_judged=true`、`capture_end_to_end_judged=false`、`note` 说明 200ms 仅判写阻塞）
  - 交付物：改造后的 `scripts/perf_probe.py`；每轮 JSON/JSONL 证据
  - 完成标准：`--rounds 3 --samples 5 --write-ops 200` 落盘 3 个 jsonl + 3 个 measure json；`--rounds 2` 退出码 `2` 且报 `ROUNDS_INSUFFICIENT`；每轮 `encode_count` 恒为 1；证据只写 `--out`（默认 `.evidence/perf-repro/`）
  - 验证命令：`python scripts/perf_probe.py capture-segmented --case PERF-02/metrics-capture --env default --rounds 3 --samples 5 --write-ops 200`
  - 不可放宽：F-07、F-09、F-06（`data_scale` 必须为 1100/12000）；禁止改写既有 `capture`/`write-block` 输出格式
  - 需求：RQ-3、RQ-5；依赖：P2-3.2、P2-5.1

### P2-6.2 新增记录类型与 `--selftest` 扩展（既有 8 项 schema 不动）
- [x] 在 `scripts/perf_probe.py` 新增独立常量 `EXTRA_REQUIRED = {"SegmentedSampleRecord": (...), "SegmentedMeasurementRecord": (...), "PerfRoundRecord": (...)}`，`validate_record` 同时识别 `REQUIRED` 与 `EXTRA_REQUIRED`；**不改** `REQUIRED` 键集合与 `schema_hits == 8` 断言；在 `_selftest()` 末尾追加新 check（`extra_schema_hits == 3` 与 `round_rule_fixtures` 通过），既有 check 顺序与文案不变
  - 交付物：改造后的 `scripts/perf_probe.py`
  - 完成标准：`--selftest` 全部 PASS，其中既有 8 项 schema 检查仍 PASS、新增 3 类必填字段缺失均被 `SCHEMA_INVALID` 拒绝；`immutable` 清单输出 count 与改动前一致
  - 验证命令：`python scripts/perf_probe.py --selftest`
  - 不可放宽：RP-12（历史证据 schema 可复读）
  - 需求：RQ-5；依赖：P2-6.1

### P2-6.3 新增 `round-summary` 子命令（预置判定规则，禁止事后调参）
- [x] 在 `scripts/perf_probe.py` 新增子命令 `round-summary`，参数 `--case`、`--out`；读取该 case 的 3 轮 measure/write-block/regression 文件，按脚本内**常量表** `ROUND_RULES`（与设计 2.4.5 逐条一致：3 轮 `write_block_ms` 全 `≤200`、协议 W 全 `Δp95 ≤200`、3 轮回归 `failures=0`、每轮 `encode_count=1`）输出 `round-summary-{stamp}.json`（3 轮文件指针与各自 `sha256`、每轮判定、总计结论、`supersedes` 为空）；**不接受** `--threshold` 等覆盖参数
  - 交付物：改造后的 `scripts/perf_probe.py`；`round-summary-*.json`
  - 完成标准：全部达标 → `decision_class="通过"`；用 fake 输入（一轮 `write_block_ms=201`）→ `"不通过"` 且理由含 `write_block_ms`；输出文件已存在时拒绝覆盖（沿用 `OUTPUT_EXISTS`）
  - 验证命令：`python scripts/perf_probe.py round-summary --case PERF-02/metrics-capture`；`python scripts/perf_probe.py --selftest`
  - 不可放宽：判定规则先定后用（设计 2.4.5），任何阈值/规则字段不得由命令行或事后手工修改
  - 需求：RQ-5；依赖：P2-6.1、P2-6.2

---

## 7. 阶段 S7：多轮证据判定、文档口径与回滚（对应设计 S6/S7）

### P2-7.1 执行 3 轮 × 5 样本 + 3 轮写阻塞 + 3 轮全量回归
- [x] 按固定协议执行并落盘（每轮独立文件，禁止覆盖）：
  1. `python scripts/perf_probe.py capture-segmented --case PERF-02/metrics-capture --env default --rounds 3 --samples 5 --write-ops 200`
  2. 每轮一次：`python -m unittest discover -s backend/tests -p "test_*.py"` → 记录 `Ran/errors/failures/failed_test_names/duration/command/contains_skip` 到 `regression-{stamp}-r{n}.json`
  3. 每轮一次：`python scripts/perf_probe.py write-block --case PERF-02/metrics-capture --env default --write-ops 200` → `write-block-metrics-capture-{stamp}-r{n}.json`
  - 交付物：`.evidence/perf-repro/samples-metrics-capture-segmented-*-r{1,2,3}.jsonl`、`measure-...-r{1,2,3}.json`、`write-block-...-r{1,2,3}.json`、`regression-*-r{1,2,3}.json`
  - 完成标准：3 轮各 5 样本齐备；3 轮回归 `failures=0` 且 `contains_skip=false`；3 轮写阻塞 `event_id_set_equal=true`、`Δp95 ≤ 200`；任何缺失/覆盖即失败
  - 验证命令：上述 1–3；`python scripts/perf_probe.py round-summary --case PERF-02/metrics-capture`
  - 不可放宽：F-08、F-09；禁止重试修绿、禁止设 `VERIFIX_SKIP_PERF=1`
  - 需求：RQ-1、RQ-3、RQ-5；依赖：P2-6.3

### P2-7.2 按预置规则输出跨轮结论（含允许表述）
- [x] 依据 `round-summary` 结果与设计 2.4.5 判定表，逐条登记结论；通过时只允许表述"写阻塞口径满足 spec 4.1-2；抓取端到端超预算仅告警，不构成 4.1-2 判据"；任一 `write_block_ms>200`、协议 W `Δp95>200`、`encode_count≠1`、PERF-02 相关回归失败 → 判"不通过"并复现；无关既有失败 → 单独登记为"阻断验收（非本次结论）"，不得计入通过也不得据此宣称本次失败
  - 交付物：`.evidence/perf-repro/round-summary-{stamp}.json` 与结论说明（写入 `docs/devlog/metrics-report.md` 对应小节）
  - 完成标准：结论与证据指针一一对应；写入 `thread_model_note` 边界（单进程内存实现，不外推至 MySQL/持久化后端）
  - 验证命令：`python scripts/perf_probe.py round-summary --case PERF-02/metrics-capture`；`python -m unittest backend.tests.test_metrics_perf backend.tests.test_metrics_capture_budget backend.tests.test_metrics_invariants`
  - 不可放宽：RP-09（结论边界）、0.3 禁止项
  - 需求：RQ-1、RQ-3；依赖：P2-7.1

### P2-7.3 文档口径更新（性能行改为"写阻塞/全链路分离"）
- [x] 更新 `docs/devlog/metrics-report.md` 性能说明：明确 200ms 仅作用于 `write_block_ms`；`capture_total_ms` 超 `capture_budget_ms` 只产生 `CAPTURE_SLOW` 非阻断告警；列出证据指针（3 轮 measure/write-block/regression/round-summary）、验收命令与实测值；补充 `encoding_count=1`、黄金 fixture 与跨版本复用结论；保留 `docs/devlog/m5-eval-report.md` 原样（sha256 不变）
  - 交付物：更新后的 `docs/devlog/metrics-report.md`
  - 完成标准：文档同时含"写阻塞判据"与"端到端告警"两句口径、无"capture ≤200ms"旧表述；`test_check_devlog` 通过；`m5-eval-report.md` sha256 未变
  - 验证命令：`python -m unittest backend.tests.test_check_devlog backend.tests.test_metrics_invariants`
  - 不可放宽：`perf_probe.immutable` 含该文件 → 由开发/文档流程改，探针不得写；报告 `content_digest` 不受影响
  - 需求：RQ-3、RQ-5；依赖：P2-7.2

### P2-7.4 回滚方案落地与演练
- [x] 把回滚方案写入 `docs/devlog/metrics-report.md`（"回滚"小节）与本文件附录：① 触发条件 5 条（黄金四项任一不等、跨版本复用失败、任一轮 `write_block_ms>200` 且非插桩错误、全量回归出现本次引入失败、指标字段/条数/幂等语义任何差异）；② 回滚粒度 12 个文件清单（`snapshot.py`、`capture_health.py`、`service.py`、`types.py`、`models.py`、`main.py`、`config.py`、`test_metrics_perf.py`、`test_metrics_capture_budget.py`、`test_metrics_invariants.py`、`support/snapshot_golden*.json`、`scripts/perf_probe.py`）；③ 顺序：回退提交 → 重启进程（内存 ref/run 重建）→ 归档文件不处理（payload 与文件名未变，回滚前后均可 verify）→ 证据保留并标注 `supersedes`；④ 回滚后复核命令
  - [x] 演练：在**独立 worktree 或临时副本目录**（禁止在主工作区 `git reset`）回退上述文件后执行复核，记录结果
  - 交付物：回滚方案文档 + 演练记录（命令、退出码、`Ran/errors/failures`、证据路径）
  - 完成标准：演练后 `python -m unittest backend.tests.test_metrics_snapshot backend.tests.test_metrics_recalc backend.tests.test_metrics_report backend.tests.test_metrics_perf`（原断言形态）全绿；`python scripts/perf_probe.py --selftest` 通过；主工作区未被破坏（`git status` 与演练前一致，除本次新增任务文档/证据）
  - 验证命令：上述 4 个用例 + `--selftest`
  - 不可放宽：RP-11（回滚后归档仍可复用）；演练须经用户确认后执行
  - 需求：RQ-5、RQ-6；依赖：P2-7.3

### P2-7.5 最终 DoD 对照清单
- [x] 逐条核对设计 2.6 完成定义 1–5 与本文件 S1–S7 的门槛，输出"通过/未通过/不适用"三态清单；未通过项给出阻塞子任务编号与复现命令；确认既有 `tasks.md` 60 项状态未被改动
  - 交付物：DoD 对照表（追加至 `docs/devlog/metrics-report.md` 末尾或本文件附录）
  - 完成标准：DoD 1–5 每项有对应命令与结论；`python -m unittest discover -s backend/tests -p "test_*.py"` 与 `python scripts/recalc_metrics.py --window 2026-12 --tier PRELIMINARY --now 2027-01-06T12:00:00+00:00` 均通过
  - 验证命令：上述两条命令
  - 需求：design 完成定义 1–5；依赖：P2-7.1…P2-7.4

---

## 8. 需求—任务映射（覆盖性核对）

| 需求事实 | 来源 | 覆盖任务 |
|---|---|---|
| RQ-1 读不阻塞写 >200ms，且判定对象可测量 | spec 4.1-2 | P2-2.1、P2-3.2、P2-4.1、P2-4.3、P2-7.1 |
| RQ-2 `capture_budget_ms` 有真实消费点，超预算可观测不阻断 | design 360/465-466/766、perf_repro_closeup 5.1.1-5 | P2-2.1、P2-3.1、P2-3.2、P2-3.4、P2-3.5、P2-4.2 |
| RQ-3 "读对写阻塞"与"抓取端到端"口径互不替代 | perf_repro_closeout 5.1.1-1/2c | P2-2.3、P2-3.3、P2-4.1、P2-6.1、P2-7.2 |
| RQ-4 端到端两次序列化合并为一次且字节等价 | perf_repro_closeout 5.1.1-1、design 2.5.2 | P2-1.2、P2-1.3、P2-2.2、P2-2.3、P2-3.3 |
| RQ-5 不得调阈值/sleep/跳过/削减数据量 | perf_repro_closeout 5.1.1-6 | 0.1、0.3、P2-5.1、P2-5.2、P2-7.1 |
| RQ-6 指标值/可计算/原因码/摘要/幂等不变，模型与 API 兼容 | spec 4.2-2、6.2、6.4 | P2-3.1、P2-3.4、P2-3.5、P2-3.6、P2-4.2、P2-5.3 |
| 黄金快照与跨版本复用 | design 2.4.2 PB-04/PB-05 | P2-1.2、P2-1.3、P2-1.4、P2-2.3 |
| 3 轮 × 5 样本与全量回归 | design 2.4.5 | P2-6.1、P2-6.3、P2-7.1、P2-7.2 |
| 回滚 | design 2.5.2 | P2-7.4 |

---

## 9. 交付物清单

| 类别 | 路径 | 任务 |
|---|---|---|
| 新增产品代码 | `backend/app/metrics/capture_health.py` | P2-2.1 |
| 改造产品代码 | `backend/app/metrics/snapshot.py` | P2-2.2、P2-3.2 |
| 改造产品代码 | `backend/app/domain/models.py`、`backend/app/metrics/service.py`、`backend/app/metrics/types.py`、`backend/app/main.py` | P2-3.1、P2-3.4、P2-3.5 |
| 配置（不改默认值） | `backend/app/config.py`（仅核对，不新增键） | P2-5.1 |
| 新增测试 | `backend/tests/test_metrics_capture_budget.py` | P2-2.3、P2-3.3、P2-3.6、P2-4.2、P2-4.3 |
| 改造测试 | `backend/tests/test_metrics_perf.py` | P2-4.1 |
| 扩展测试 | `backend/tests/test_metrics_invariants.py` | P2-5.1、P2-5.2、P2-5.3 |
| 新增测试夹具 | `backend/tests/support/perf_fixture.py`、`backend/tests/support/snapshot_golden.json`、`backend/tests/support/snapshot_golden_small.json`、`backend/tests/support/snapshot_golden/*.json` | P2-1.1…P2-1.4 |
| 新增脚本 | `scripts/capture_snapshot_golden.py` | P2-1.2 |
| 改造脚本 | `scripts/perf_probe.py` | P2-6.1、P2-6.2、P2-6.3 |
| 证据 | `.evidence/perf-repro/{samples,measure,write-block,regression}-*`、`round-summary-*` | P2-7.1、P2-7.2 |
| 文档 | `docs/devlog/metrics-report.md`（性能口径、证据指针、回滚、DoD） | P2-7.3、P2-7.4、P2-7.5 |
| 只读不改 | `.codeartsdoer/specs/metrics_recalc/{spec,design,tasks}.md`、`docs/devlog/m5-eval-report.md` | 全阶段 |

---

## 附：任务勾选状态说明

- 本文件全部子任务初始状态为 `- [ ]`（未开始）；执行完成后为 `- [x]`。S1 完成后才开始 S2，串行推进。
- 勾选只表示"完成标准 + 验证命令均通过"，不表示"已验证可上线"；上线判定见 P2-7.5。
- 本文件与既有 `tasks.md` 相互独立：既有 60 项保持 `[x]` 未被改写；本文件新增 27 个任务条目、28 个复选框（S1 4 + S2 3 + S3 6 + S4 3 + S5 3 + S6 3 + S7 5 个条目 / 6 个复选框，P2-7.4 拆为"方案撰写 + 演练"两项）。