# 主流程指标复算 · 编码任务规划（tasks）

> 依据：`.codeartsdoer/specs/metrics_recalc/spec.md`（577 行）＋ `.codeartsdoer/specs/metrics_recalc/design.md`（1438 行）
> 目标：在现有 VeriFix 代码库（`backend/app/`、`backend/tests/`、`scripts/`）实现主流程指标复算，替换 `docs/devlog/m5-eval-report.md` 中 M4–M9"不可计算（缺采集源）"状态。
> 组织方式：按"证据生产侧只增不改 → 定义登记与通道隔离 → 快照构建/校验 → 采集器与规则 → 五道判定 → 复算服务与三条触发路径 → 落库与报告改造 → 主流程实跑复算与报告产出 → 回归加固"九阶段推进；每个任务可独立验证，不按 Controller/Service/DAO 技术层切分。
> 写作范围：只描述"做什么、改哪些文件、做到什么程度"，不含实现代码。
> 已裁决口径（用户无异议，按 design 执行）：① 剔除比例超 10% 统一报 `COVERAGE_INSUFFICIENT`（仅 `covered=0` 时报 `EVIDENCE_INCONSISTENT`）；② 前置校验失败整次复算失败、零指标写入；③ M7 缺少 `Disposition.ready_at` 记为剔除、禁止用 `decided_at` 估算；④ M6 定义升 v2、采集源改为 `GateResult`/`GateAttempt`、v1 定义归档保留可查。

---

## 0. 全局约束与验收约定

**A. 不可破坏的既有不变式（每个阶段收尾时必须复核）**

| 不变式 | 具体约束 | 守护任务 | 验证方式 |
|---|---|---|---|
| 状态迁移与守卫 | 既有 `backend/app/orchestration/state_machine.py` 的迁移全集与守卫（用户口径 17 条业务迁移，含辅助迁移 T0/T5/T8B）零改动：不新增迁移、不放宽守卫、不改 `TransitionContext` 语义 | 1.1–1.6、9.2 | `python -m unittest backend.tests.test_state_machine backend.tests.test_gate`；9.2 迁移数量与守卫断言 |
| `main` 永不自动合并 | 补丁分支命名空间 `verifix/` 不变，`main/master` 在适配层与门禁层双重硬拒，L0 只合并到 `release/auto` | 1.5、9.2 | `python -m unittest backend.tests.test_gate`；`test_gate.test_main_is_hard_rejected` 必须持续通过 |
| 不可计算禁止填 0/估算 | `computable=False` 时 `value` 必须为空、`reason_code` 非空；禁止写入 0、上次值或估算值；M7 禁止用 `decided_at` 代替 `ready_at` | 5.3、7.2、9.2 | `python -m unittest backend.tests.test_metrics_judgment backend.tests.test_metrics_report`；9.2 空值互斥断言 |
| 通道隔离 | 评测通道与主流程通道隔离：`EvalRunner` 每次新建独立 `MemoryStore` 不变；带 `EVAL` 通道标记的记录不进入 M4–M9 分子分母，也不得跨通道补值 | 2.5、2.6、4.1、9.2 | `python -m unittest backend.tests.test_metrics_isolation backend.tests.test_metrics_rules` |
| API 契约向后兼容 | 既有 `GET /api/v1/metrics` 只新增字段、不改既有字段语义；既有错误码不变；旧调用（不传 `window/tier`）仍返回全部记录 | 6.5、7.4、9.2 | `python -m unittest backend.tests.test_metrics_api backend.tests.test_m4_admin backend.tests.test_m4_dashboard` |
| 历史数据不可改写 | 旧 v1 `Metric` 记录可读可展示；旧 `docs/devlog/m5-eval-report.md` 保留为历史留痕、不被覆写；复算 2026-12 不改变 2026-11 及更早窗口记录 | 7.2、8.4、9.4 | `python -m unittest backend.tests.test_metrics_invariants`（含报告文件前后 sha256 比对、跨窗口记录比对） |

**B. 本机环境与替代验证方式**

1. **测试框架**：本机未安装 pytest（`ModuleNotFoundError: No module named 'pytest'`）。全部验收统一使用 `unittest`：
   - 单文件：`python -m unittest backend.tests.test_xxx`
   - 多文件：`python -m unittest backend.tests.test_a backend.tests.test_b`
   - 全量：`python -m unittest discover -s backend/tests -p "test_*.py"`（现有 253 个用例、约 13 秒，基线全绿）
   - 若后续安装 pytest，同一测试文件可等价用 `python -m pytest backend/tests/test_xxx.py -q` 运行；任务完成标准以 unittest 命令为准。
2. **无 Docker**：全部测试使用进程内 `MemoryStore` + `tempfile.TemporaryDirectory` + `LocalEvidenceStore`；主流程链路用现有本地适配器（`backend/app/adapters/repo.py::LocalRepoAdapter`、`backend/app/adapters/pipeline.py::RecordedPipelineClient`），不启动容器、不跑真实 Pipeline。
3. **无华为云凭据**：不设置任何以真实 CodeArts/Repo/OBS 连通为完成标准的任务。M6 用主流程 `GateResult`/`GateAttempt`；M9 用本地采样文件；M1–M3 用已落盘的 `eval/runs/*.json`（现有 `EVALRUN-27714aeffb.json` 可作真实样本）。
4. **非 Git 仓库**：不安排任何 git 命令；"分支不得为 main"由 `LocalRepoAdapter` 与 `Patch` 模型校验断言，不依赖 git 状态。**前提变更（2026-11-18）：本条"不安排任何 git 命令"的适用范围截至基线提交；此后只读 git 查询可用于追溯，分支守卫断言仍由模型层校验。**
5. **redis 不存在**：当前代码库无 redis 依赖，本方案不引入 redis；`RecalcGuard` 为进程内非阻塞锁，验收不依赖外部锁服务；多实例边界写入文档即可。
6. **性能验证**：用 `time.perf_counter` + `unittest` 断言，不做 pytest marker 依赖；性能用例可通过环境变量 `VERIFIX_SKIP_PERF=1` 跳过（默认开启）。
7. **时间与随机性**：测试统一使用固定 UTC 基准时间与显式 `now` 注入，禁止 `sleep` 等待；复算服务对外暴露可注入的 `clock`。

**C. 任务总览表**

| 阶段 | 任务数 | 对应 design 2.6 阶段 | 依赖关系 | 可验证点（主要命令/探针） |
|---|---|---|---|---|
| 1 证据生产侧只增不改 | 6 | 阶段 1（模型前置项提前） | 无 | `python -m unittest backend.tests.test_metrics_evidence`；P-01/P-05/P-06、N-07/N-08/N-10/N-11 |
| 2 定义登记与通道隔离 | 7 | 阶段 0 + 阶段 2（通道部分） | 依赖阶段 1（`Issue.channel`、尝试历史模型） | `python -m unittest backend.tests.test_metrics_definitions backend.tests.test_metrics_isolation`；N-22、P-09、N-03 |
| 3 快照构建/校验 | 6 | 阶段 2 | 依赖阶段 1、2（通道解析、指标侧集合） | `python -m unittest backend.tests.test_metrics_snapshot`；N-15/N-16/N-17/P-12/READ-01/N-21 |
| 4 采集器与规则 | 11 | 阶段 3（规则部分）+ 阶段 6（M9 采样） | 依赖阶段 1–3（视图需尝试历史/通道/窗口标注） | `python -m unittest backend.tests.test_metrics_rules backend.tests.test_metrics_sampler`；P-01..P-08、N-01..N-14、N-21、N-30 |
| 5 五道判定 | 4 | 阶段 3（判定部分） | 依赖阶段 2（定义/原因码）、阶段 4（规则结果） | `python -m unittest backend.tests.test_metrics_judgment`；N-13/N-14、原因码优先级、空值约束 |
| 6 复算服务与三条触发路径 | 7 | 阶段 4 | 依赖阶段 3、4、5 | `python -m unittest backend.tests.test_metrics_recalc backend.tests.test_metrics_api`；P-10/P-11、N-18/N-19/N-22、PERF-01/02 |
| 7 落库与报告改造 | 7 | 阶段 5 | 依赖阶段 6（只读落库记录） | `python -m unittest backend.tests.test_metrics_report backend.tests.test_metrics_api`；P-13、N-23/N-24/N-25/N-27 |
| 8 主流程实跑复算与报告产出 | 6 | 阶段 6（脚本/实跑） | 依赖阶段 7 | `python scripts/recalc_metrics.py --window 2026-12 --tier PRELIMINARY`；`python -m unittest backend.tests.test_metrics_e2e`；DoD 1–3 |
| 9 回归加固 | 6 | 阶段 0–6 收口 | 依赖阶段 1–8 | 全量 `python -m unittest discover -s backend/tests -p "test_*.py"`；不变量/性能/兼容性用例 |

> 探针编号沿用 `design.md` 2.5.2（P-01…P-15）、2.5.3（N-01…N-30）、2.5.4（PERF-01…PERF-04、READ-01），本文件不再重复其定义。

**D. 任务书写约定**

- 每条任务给出：改动文件路径、前置依赖、完成标准（可执行命令）、需求条款编号（`spec` 章节号）。
- 完成标准中的命令均在仓库根 `E:\shuangxingxi\ICT_agent` 执行。
- 新增测试文件统一位于 `backend/tests/`，文件名与 design 2.5.1 对齐；测试内部沿用现有 `sys.path.insert(0, .../backend)` 风格。
- 禁止在任务中安排"只有真实外部系统才能验证"的完成标准。

---

## 1. 阶段 1：证据生产侧只增不改（尝试历史、`ready_at`、通道标记）

**本阶段不得破坏**：`state_machine.py` 全量迁移与守卫零改动；`Proof.pre_patch_result=FAIL`、`Disposition` L0/L1 必须 `gate_outcome=PASSED`、`Patch.branch` 命名空间与 `main` 硬拒等模型校验不变；`add_proof/add_patch/add_gate_result/add_disposition` 的"当前值覆盖"语义不变（历史另行追加）。

### 1.1 扩展领域模型：通道标记、PR 就绪时刻与四类尝试历史
- [x] 在 `backend/app/domain/enums.py` 新增 `MetricChannel`（`MAIN`/`EVAL`/`UNKNOWN`）与 `ReproductionAttemptStatus`（`PROVEN`/`REPRO_FAILED`/`INVALID_TEST`/`INFRA_ERROR`）；在 `backend/app/domain/models.py` 新增 `ReproductionAttempt`、`PatchAttempt`、`GateAttempt`、`DispositionHistoryEntry`，并为 `Issue` 增加 `channel: MetricChannel = MetricChannel.MAIN`、`Disposition` 增加 `ready_at: datetime | None = None`；所有新增字段带默认值，保持 `extra="forbid"`
  完成标准：新建 `backend/tests/test_metrics_evidence.py`，用例覆盖四个模型的必填字段与默认值、`Issue.channel` 默认 `MAIN`、`Disposition.ready_at` 默认 `None`；`python -m unittest backend.tests.test_metrics_evidence backend.tests.test_domain_models` 通过
  需求：spec 5.2.1-2、5.2.1-5、5.1.1-2(4)(5)(6)(7)、5.1.1-5、6.1
  依赖：无

### 1.2 存储层新增四类追加集合与事务清单
- [x] 在 `backend/app/repo/memory.py` 增加 `reproduction_attempts`、`patch_attempts`、`gate_attempts`、`disposition_history` 四个集合，提供只追加的 `record_reproduction/record_patch/record_gate/record_disposition` 与只读的 `reproduction_attempts_for/patch_attempts_for/gate_attempts_for/disposition_history_for`；将集合清单抽为常量并纳入 `_take_snapshot/_restore_snapshot`，不改变 `snapshot_digest()` 的计算口径与返回值
  完成标准：`backend/tests/test_metrics_evidence.py` 新增用例断言"事务内追加后抛异常 → 四个集合回滚为空、既有 15 类集合不变"；`python -m unittest backend.tests.test_metrics_evidence backend.tests.test_repo_and_service` 通过
  需求：spec 4.2.1、4.2.5、5.2.1-4、6.2.11
  依赖：1.1

### 1.3 复现服务追加复现尝试历史
- [x] 在 `backend/app/agents/reproducer/service.py` 的成功路径（`add_proof` 前后）、复现失败路径、无效测试与基础设施错误路径各追加一条 `ReproductionAttempt`（`attempt_index` 按 Issue 递增、`proof_id` 可空、状态取 `ReproductionAttemptStatus`），不改变 T7/T8 迁移与红态判定逻辑
  完成标准：`test_metrics_evidence` 用例 P-05 的组件级版本——同一 Issue 复现两次（第二次成功）后 `reproduction_attempts` 有 2 条且 `attempt_index=[1,2]`，`store.proofs` 仍只保留最新一份；`python -m unittest backend.tests.test_metrics_evidence backend.tests.test_reproducer` 通过
  需求：spec 5.1.1-2(4)、5.2.1-3
  依赖：1.1、1.2

### 1.4 补丁服务追加补丁尝试历史
- [x] 在 `backend/app/agents/patcher/service.py` 的每次补丁产出路径（含配额/强度校验通过后的 `add_patch` 两次调用点）追加 `PatchAttempt`，`attempt_id` 采用 `PA-{issue_id}#{attempt_index}`、`attempt_index` 从 1 递增，`store.patches` 覆盖语义保持不变
  完成标准：`test_metrics_evidence` 用例断言同一 Issue 两次补丁后 `patch_attempts` 有 2 条且 `attempt_id` 连续、`store.patch_for(issue)` 只返回最新补丁；`python -m unittest backend.tests.test_metrics_evidence backend.tests.test_patcher` 通过
  需求：spec 5.1.1-2(5)、5.2.1-5
  依赖：1.1、1.2

### 1.5 门禁与处置服务追加门禁尝试、处置历史与 PR 就绪时刻
- [x] 在 `backend/app/agents/gatekeeper/service.py` 四条路径（L0 合并成功、L1 开 PR、L2 回滚/仅报告、L3 后门拒绝）追加 `GateAttempt`（每次 `GateResult` 一条，含 `NOT_EXECUTED`/`evidence_missing` 情形）与 `DispositionHistoryEntry`（携带 `attempt_id`）；L0 在 `merge_to_release_auto` 成功后、L1 在 `open_pull_request` 成功后立即取 UTC 时刻写入 `Disposition.ready_at` 与历史条目；不改变三闸判据、回滚流程与 L2/L3 触发条件
  完成标准：`test_metrics_evidence` 用例断言 L1 路径 `ready_at` 非空且为 UTC、L2 路径 `ready_at` 为 `None`、每次门禁后 `gate_attempts_for(patch_id)` 条数递增；`python -m unittest backend.tests.test_metrics_evidence backend.tests.test_gate` 通过
  需求：spec 5.1.1-2(6)(7)、2 术语"PR 就绪"、5.2.1-6、6.1
  依赖：1.1、1.2

### 1.6 阶段 1 回归与正反例守护
- [x] 在 `backend/tests/test_metrics_evidence.py` 补齐 N-07/N-08/N-10/N-11 的组件级正反例：仅有最新补丁无尝试历史、`attempt_index` 缺 1、全部处置缺 `ready_at`、单条 `ready_at < first_observed_at`；确认既有 Agent 行为零回归
  完成标准：`python -m unittest backend.tests.test_metrics_evidence backend.tests.test_reproducer backend.tests.test_patcher backend.tests.test_gate backend.tests.test_state_machine` 通过；既有 253 个用例无一条因新增历史而失败
  需求：spec 5.2.1-5、5.3.3-2
  依赖：1.3、1.4、1.5

---

## 2. 阶段 2：定义登记与通道隔离

**本阶段不得破坏**：`MetricCalculator.describe()` 返回结构不变；`Metric` 不可计算/无值校验不变；`Issue` 指纹去重与归一化规则不变；`EvalRunner` 的独立 store 与执行流程不变；`AppConfig` 的 `extra="forbid"` 与既有配置键不变。

### 2.1 建立固定原因码集合与判定环节映射
- [x] 新建 `backend/app/metrics/reason_codes.py`，定义 `UncomputableReason` 八个稳定英文码（`SOURCE_MISSING`/`DENOMINATOR_EMPTY`/`EVIDENCE_MISSING`/`EVIDENCE_INCONSISTENT`/`COVERAGE_INSUFFICIENT`/`DEFINITION_UNREGISTERED`/`WINDOW_NOT_CLOSED`/`FIRST_ATTEMPT_EVIDENCE_MISSING`）、判定环节枚举与中文展示映射，并提供"仅允许固定集合"的校验函数
  完成标准：新建 `backend/tests/test_metrics_definitions.py`，断言枚举恰为 8 个值、中文映射全覆盖、非法字符串无法进入模型/接口；`python -m unittest backend.tests.test_metrics_definitions` 通过
  需求：spec 5.3.1-5、2 术语"不可计算原因码"、6.2.4
  依赖：1.1

### 2.2 建立指标定义登记表（v1 归档、v2 生效）
- [x] 新建 `backend/app/metrics/definitions.py`，实现 `MetricDefinition`（名称、分子/分母口径、单位、采集源绑定、通道、版本、生效时间、初赛/总决赛目标）与 `DefinitionRegistry`（`effective(metric_id, at)`、`all_effective(at)`）；v1 归档内容取自 `metrics/calculator.py::SPECS` 原文（M6 保留"Pipeline 日志"历史事实），v2 按 spec 5.1.1-2 登记、M6 采集源改为 `GateResult`/`GateAttempt`，M2 标注"口径待评测通道对齐"，目标登记初赛 M1≥0.50/M4≥0.60/M5≥0.45/M9≥24h、总决赛独立登记
  完成标准：`test_metrics_definitions` 用例断言 9 项在 `at=2026-12-01` 均返回 v2、v1 可按历史时间查询且字段不被改写、缺任一项时 `all_effective` 返回缺失编号集合（N-22 的定义层版本）；`python -m unittest backend.tests.test_metrics_definitions` 通过
  需求：spec 5.1.1-1、5.1.1-2、5.1.1-4、5.1.1-5、6.1、4.5.1
  依赖：2.1

### 2.3 扩展指标记录模型并新增五类落库模型
- [x] 在 `backend/app/domain/models.py` 为 `Metric` 新增 `reason_code`、`channel`、`recalc_id`、`snapshot_id`、`snapshot_digest`、`numerator`、`denominator`、`covered_count`、`excluded_count`、`channel_excluded_count`、`not_applicable_count`、`exclusion_ref`、`trial`、`last_success_at`（全部带默认值，模型层不强制 `reason_code`）；新增 `MetricDefinitionRecord`、`MetricSnapshotRef`、`RecalcRun`、`ExclusionEntry`、`MetricReport` 五个模型；`Metric` 的"可计算必须有值/不可计算必须无值"校验保持
  完成标准：`test_metrics_definitions` 用例断言旧式 `Metric(...)`（仅原 8 字段）可直接构造且 `computable/value` 校验仍生效、新增字段默认值符合 design 2.1.3(7)、`computable=False` 且 `value=0` 被拒；`python -m unittest backend.tests.test_metrics_definitions backend.tests.test_domain_models backend.tests.test_m4_admin` 通过
  需求：spec 6.2.1–6.2.11、5.5.1-1、6.3、6.4、6.5、4.5.1
  依赖：1.1、2.1

### 2.4 建立指标侧存储集合与仓储契约
- [x] 在 `backend/app/repo/memory.py` 增加 `metric_definitions`、`metric_snapshots`、`recalc_runs`、`metric_exclusions`、`metric_reports` 五个集合及读写方法（定义按 `metric_id:version`、快照按 `snapshot_id`、复算按 `recalc_id`、剔除清单按 `recalc_id:metric_id`、报告按 `report_id`），纳入事务快照；新建 `backend/app/metrics/repository.py` 定义 `MetricsRepository` 与 `AttemptRepository` 的 `Protocol`（签名对齐 design 2.2.2 C）
  完成标准：`test_metrics_definitions` 用例断言五类集合在事务内异常时回滚、`Metric` 唯一键仍为 `(metric_id, stage_tier, window)` 且覆盖不新增；`python -m unittest backend.tests.test_metrics_definitions backend.tests.test_repo_and_service` 通过
  需求：spec 4.2.1、4.2.2、6.2.1、6.3.1、6.4.1、6.5.1
  依赖：1.2、2.3

### 2.5 实现通道解析与排除计数
- [x] 新建 `backend/app/metrics/isolation.py`，实现 `ChannelResolver.resolve(issue)`：显式 `channel` 优先 → legacy `code_version.startswith("eval-")` 兜底（标注 `legacy=true`）→ 其余 `UNKNOWN`；提供 `ChannelResolution(channel, basis, legacy)` 与排除计数汇总，`EVAL` 计入 `channel_excluded_count`、`UNKNOWN` 计入剔除（`EVIDENCE_INCONSISTENT`，`detail=通道不可判`）
  完成标准：新建 `backend/tests/test_metrics_isolation.py`，覆盖 P-09（3 条 EVAL 记录被排除且 `channel_excluded_count=3`）、N-03（UNKNOWN 剔除）、RK-12（主流程版本号恰为 `eval-` 时显式 `channel=MAIN` 不被误排除）；`python -m unittest backend.tests.test_metrics_isolation` 通过
  需求：spec 5.2.1-2、5.2.3-3、5.1.1-5
  依赖：1.1、2.1

### 2.6 评测通道显式标记并收敛旧前缀法
- [x] 在 `backend/app/eval/runner.py` 的评测 Issue 构造处显式写 `channel=MetricChannel.EVAL`（仅新增字段赋值，不改执行流程）；将 `backend/app/metrics/calculator.py::_in_scope_issues` 改用 `ChannelResolver`（保持 `evaluate`/`calculate` 外部行为兼容），`describe()` 与 `SPECS` 不改
  完成标准：`test_metrics_isolation` 用例断言评测通道产物在主流程 store 中不出现、主流程 Issue 默认 `MAIN`、`MetricCalculator` 旧前缀场景结果与改造前一致；`python -m unittest backend.tests.test_metrics_isolation backend.tests.test_eval backend.tests.test_eval_runner` 通过
  需求：spec 5.2.1-2、5.1.1-5、5.1.3-3
  依赖：2.5

### 2.7 阶段 2 回归
- [x] 复核 `AppConfig` 未新增键时默认值可用；确认 `MetricCalculator.describe()` 输出与 `docs/devlog/m5-eval-report.md` 现状渲染兼容（旧脚本可继续读取）
  完成标准：`python -m unittest backend.tests.test_config backend.tests.test_metrics_definitions backend.tests.test_metrics_isolation backend.tests.test_api_m1` 通过
  需求：spec 4.5.1、4.5.3
  依赖：2.6

---

## 3. 阶段 3：快照构建与校验

**本阶段不得破坏**：`MemoryStore.snapshot_digest()` 的返回值与调用方（既有测试、看板）不变；`LocalEvidenceStore.put_locked/read/verify` 的 key 规则与路径逃逸防护不变；`evidence/replay.py` 的 `RunReplay` 输出结构不变；复算对主流程只读。

### 3.1 存储层增加内容摘要与只读复制
- [x] 在 `backend/app/repo/memory.py` 增加 `content_digest()`（对规范化后的完整记录内容取 sha256，覆盖 issues/alerts/verdicts/proofs/attempts/patches/gates/dispositions/runs/events）与 `snapshot_copy()`（浅拷贝容器 + 记录不可变引用，不做 deepcopy）；`snapshot_digest()` 原实现保持
  完成标准：`backend/tests/test_metrics_snapshot.py` 用例断言"仅修改某 Issue 的 `status`，`snapshot_digest()` 不变而 `content_digest()` 改变"；`python -m unittest backend.tests.test_metrics_snapshot backend.tests.test_repo_and_service` 通过
  需求：spec 5.2.1-4、4.2.5
  依赖：2.4

### 3.2 实现快照构建器（抓取、标注、规范化、摘要、归档）
- [x] 新建 `backend/app/metrics/snapshot.py`，实现 `SnapshotBuilder.capture(window, tier)`：只读抓取 → 标注每个 Issue 的 `channel`/`first_observed_at`/`window_owner`/`tz_ok` → 脱敏 → canonical JSON（`sort_keys`、`ensure_ascii=False`、`separators`、UTC 微秒 ISO8601、列表排序口径按 design 2.1.3(2)）→ `digest=sha256(payload)` → `snapshot_id=SNAP-{window}-{tier}-{digest[:12]}` → `put_locked` 归档；同名快照只 `verify` 不重写；输出 `SnapshotEnvelope`（payload + `MetricSnapshotRef`），记录 `record_counts`、`capture_ms`
  完成标准：`test_metrics_snapshot` 用例断言同一 store 连续两次抓取 `digest` 完全一致（P-12 前置）、重名归档后再次抓取不重写且校验通过、`capture_ms` 被记录；`python -m unittest backend.tests.test_metrics_snapshot` 通过
  需求：spec 5.2.1-1、5.2.1-3、5.2.1-7、6.4.1–6.4.4
  依赖：3.1、2.5

### 3.3 实现快照校验器与事件链校验
- [x] 在 `backend/app/metrics/snapshot.py` 增加 `SnapshotVerifier.verify(snapshot_id, expected_digest)`：校验归档对象存在、sha256 一致、event 链逐 run 重算 `seq/prev_hash/self_hash`（复用 `MemoryStore._event_hash`/`verify_chain` 口径），输出 `IntegrityReport(chain_valid, broken_runs, digest_match, record_counts)`；定义 `SnapshotIntegrityError`
  完成标准：`test_metrics_snapshot` 用例覆盖 N-15（归档文件被篡改 → `digest_match=false`）、N-16（改一条事件内容 → `chain_valid=false` 并列出 run）、快照不存在；`python -m unittest backend.tests.test_metrics_snapshot backend.tests.test_envelope` 通过
  需求：spec 4.3.4、5.2.3-2、5.4.3-3、6.4.5
  依赖：3.2

### 3.4 实现脱敏白名单与摘要豁免
- [x] 在 `backend/app/metrics/snapshot.py` 复用 `backend/app/tools/redactor.py`，仅对人读文本字段（`Alert.snippet`、`Verdict.basis`、`Verdict.taint_path`、`Disposition.action`、`Disposition.reason_code`、`RunStep.detail`、`Event.payload_ref`、`Patch.branch`）脱敏；`sha256`、`diff_ref`、`*_digest` 字段白名单豁免；`redaction_hits` 只记条数不记原文
  完成标准：`test_metrics_snapshot` 用例 N-17：快照内含假凭据文本时归档 payload 无原文、`redaction_hits>0`、脱敏前后 `digest` 可重算一致、证据引用（`diff_ref`/`sha256`）仍可解析；`python -m unittest backend.tests.test_metrics_snapshot backend.tests.test_diff_redactor` 通过
  需求：spec 4.3.3、5.5.1-8
  依赖：3.2

### 3.5 实现只读探针
- [x] 在 `backend/app/metrics/snapshot.py` 增加 `ReadOnlyProbe`：在复算前后采集 `snapshot_digest()`、`content_digest()`、各集合计数与各 run 事件链长度，输出逐项比对结果（不一致即失败）
  完成标准：`test_metrics_snapshot` 用例 READ-01：构造 store → 抓取快照 → 读取 payload 计算 → 探针比对全项一致；并断言"若人为向 store 写入一条 Issue，探针报不一致"；`python -m unittest backend.tests.test_metrics_snapshot` 通过
  需求：spec 5.2.1-4、4.2.5、4.3.4
  依赖：3.1、3.3

### 3.6 阶段 3 回归与窗口边界标注
- [x] 补齐快照阶段窗口标注边界用例：`observed_at=2026-12-01T00:00:00Z` 归属 2026-12，`2026-11-30T23:59:59Z` 归属 2026-11，`2027-01-01T00:00:00Z` 不计入 2026-12；naive 时间标记 `tz_unavailable`
  完成标准：`python -m unittest backend.tests.test_metrics_snapshot` 通过（含 N-21 标注层用例）；`python -m unittest backend.tests.test_metrics_snapshot backend.tests.test_evidence_envelope` 无回归
  需求：spec 5.2.1-6、5.2.1-7
  依赖：3.2、3.5

---

## 4. 阶段 4：采集器与口径规则

**本阶段不得破坏**：规则为纯函数（不读 `store`、不读上次结果、不写任何记录）；不可达/疑似/范围外/窗口外/非目标处置级别只做"口径排除"，不得计入剔除数；M1–M3 不重算评测通道口径。

### 4.1 实现主流程证据采集器与按 Issue 聚合视图
- [x] 新建 `backend/app/metrics/collectors/__init__.py` 与 `backend/app/metrics/collectors/main_flow.py`，实现 `IssueEvidenceView` 与 `MainFlowEvidenceCollector.build(snapshot)`：按 `issue_id` 聚合 Issue/Alert/Verdict/复现尝试/Proof/补丁尝试/Gate 尝试/处置当前值与历史/事件；缺失项显式 `None` 并写入 `missing` 列表，禁止填默认值；计算 universe（`channel=MAIN`、`in_scope=True`、告警首次观测时刻落入 `[window_start, window_end)`；无 Alert 时用 `Issue.occurred_at` 兜底并置 `fallback_occurred_at=true`）
  完成标准：`backend/tests/test_metrics_rules.py` 用例断言完整链路视图字段齐全、缺 Gate 时 `missing` 含 `gate`、窗口边界与 fallback 标记正确、`EVAL` 记录不进入视图 universe；`python -m unittest backend.tests.test_metrics_rules` 通过
  需求：spec 5.2.1-2、5.2.1-3、5.2.1-6、5.2.1-7、5.1.1-2
  依赖：1.3、1.4、1.5、2.5、3.2

### 4.2 定义规则契约与计数一致性
- [x] 新建 `backend/app/metrics/rules/__init__.py` 与 `backend/app/metrics/rules/base.py`，定义 `MetricRule` 协议与 `RuleResult`（`numerator`、`denominator`、`covered_count`、`excluded_count`、`not_applicable_count`、`channel_excluded_count`、`exclusions`、`source_ref`、`evidence_present`、`details`）；提供统一校验：`covered_count + excluded_count` 等于进入分母判定记录数、计数非负、剔除只允许 `EVIDENCE_MISSING`/`EVIDENCE_INCONSISTENT` 两码
  完成标准：`test_metrics_rules` 用例断言非法计数组合（如 `covered+excluded>denominator`）抛内部错误、剔除项原因码越界被拒；`python -m unittest backend.tests.test_metrics_rules` 通过
  需求：spec 6.2.10、6.2.11、5.3.1-5
  依赖：4.1

### 4.3 实现 M4 复现成功率规则
- [x] 新建 `backend/app/metrics/rules/m4.py`：分母为 universe 中 effective verdict 为 `REACHABLE` 且已进入/完成复现的 Issue；分子为分母中最新一次复现状态为 `PROVEN` 且有 `pre_patch_result=FAIL` 的 proof；同一 Issue 取 `attempt_index` 最大者；`REPRO_FAILED` 计入分母不计分子；无 attempt 且状态 `PROVEN` 有 proof 时按 legacy 计数并标 `legacy=true`；`REPRO_FAILED` 却有旧 proof 时记 `EVIDENCE_INCONSISTENT` 剔除
  完成标准：`test_metrics_rules` 用例覆盖 P-03（复现失败分母 +1 分子 +0）、P-05（两次复现取最新）、N-01（仅不可达时分母为 0）、旧数据 legacy 计数；`python -m unittest backend.tests.test_metrics_rules` 通过
  需求：spec 5.1.1-2(4)、5.2.1-3
  依赖：4.2

### 4.4 实现 M5 一次修复通过率规则
- [x] 新建 `backend/app/metrics/rules/m5.py`：分母为 universe 中存在 `attempt_index=1` 的补丁尝试的 Issue；分子要求首次尝试 `gate.outcome=PASSED`、三闸字段通过、处置级别 ∈ {L0,L1} 且处置 `attempt_id` 与首次尝试一致；无法唯一识别首次尝试（仅最新补丁无历史、索引不连续、无法关联门禁/处置）记剔除；分母内全部无法识别时输出专用标记供判定层转 `FIRST_ATTEMPT_EVIDENCE_MISSING`
  完成标准：`test_metrics_rules` 用例覆盖 P-01（M5=1.0）、N-06（首次失败第二次成功分子不含）、N-07/N-08（无历史/索引缺 1 剔除）、N-09（声称 L1 无 PASSED 门禁剔除）；`python -m unittest backend.tests.test_metrics_rules` 通过
  需求：spec 5.1.1-2(5)、5.2.1-5、5.2.3-4
  依赖：4.2

### 4.5 实现 M6 回归破坏率规则（定义 v2 采集源）
- [x] 新建 `backend/app/metrics/rules/m6.py`：分母为 universe 关联补丁中存在门禁结论的记录（`outcome ∈ {PASSED, FAILED}` 且 `evidence_missing=False`，`NOT_EXECUTED` 按口径排除）；分子为 `regression_zero_fail=False` 或 `rescan_new_alerts>0` 或 `coverage_delta_pp < -tolerance_pp`（容忍值来自定义 v2，默认 0.5pp）；无任何门禁记录时输出 `evidence_present=false`（判定层报 `SOURCE_MISSING`），全部 `NOT_EXECUTED` 时分母为 0
  完成标准：`test_metrics_rules` 用例覆盖 P-06（-0.6pp 分子 +1）、P-07（-0.4pp 分子 +0）、N-04（无门禁 → 采集源缺失标记）、N-05（全 NOT_EXECUTED → 分母 0）、N-09 关联失败剔除；断言规则不读 `calculator.SPECS`、不出现"Pipeline 日志"字样；`python -m unittest backend.tests.test_metrics_rules` 通过
  需求：spec 5.1.1-2(6)、5.1.1-1、5.2.1-3
  依赖：4.2、1.5

### 4.6 实现 M7 MTTR 规则
- [x] 新建 `backend/app/metrics/rules/m7.py`：起点取 `Alert.observed_at` 最小值，终点取 `Disposition.ready_at`；分母仅收完成 L0/L1 且两端时间戳齐备的 Issue；`ready_at` 缺失、任一端 naive、`ready_at < first_observed_at`、通道不明记剔除；`ready_at` 全量缺失时输出分母 0 与受影响 Issue 数明细，禁止用 `decided_at` 估算
  完成标准：`test_metrics_rules` 用例覆盖 P-01（正时长均值）、N-10（全量缺 `ready_at` → 分母 0 且 `details.missing_ready_at` 列出条数）、N-11（负时长剔除）、N-12（naive 剔除）；断言结果中从不出现 `decided_at` 作为终点；`python -m unittest backend.tests.test_metrics_rules` 通过
  需求：spec 5.1.1-2(7)、5.2.1-6、2 术语"PR 就绪"
  依赖：4.2、1.5

### 4.7 实现 M8 自动处置率规则
- [x] 新建 `backend/app/metrics/rules/m8.py`：分母为 universe 全部 Issue（含未处置/处置中）；分子为 `disposition.level ∈ {L0,L1}`、`gate_outcome=PASSED` 且能找到 `outcome=PASSED` 的门禁记录；处置与门禁矛盾、告警时间不可用、通道不明记剔除；与 M5 明确区分计数单位（M8 按 Issue、M5 按首次尝试）
  完成标准：`test_metrics_rules` 用例覆盖 P-01/P-02（M8=1.0）、N-09（声称 L1 无 PASSED 门禁剔除）、未处置 Issue 计入分母；`python -m unittest backend.tests.test_metrics_rules` 通过
  需求：spec 5.1.1-2(8)、5.3.3-2
  依赖：4.2、1.5

### 4.8 实现自运行采样写入与读取
- [x] 在 `backend/app/runtime/self_run.py` 增加 `sample()` 返回只读采样对象（`sampled_at`/`continuous_seconds`/`interruptions`/`heartbeat_ok`/`tracker_started_at`），不改变连续/中断计数语义；在 `backend/app/main.py` 的心跳端点追加 JSONL 采样归档（路径取 `metrics.self_run_sample_path`）；新建 `backend/app/metrics/collectors/runtime_sampler.py` 实现 `SelfRunSampleReader.latest(path, now, timeout_s)`，流式读取末尾并在文件不存在时返回 `None`
  完成标准：新建 `backend/tests/test_metrics_sampler.py`，用例覆盖采样追加、`heartbeat_ok=False` 超时判定、无采样返回 `None`、采样文件 100 万行读取 ≤50ms（PERF-03 简化版，写入 10 万行做线性外推并记录耗时）；`python -m unittest backend.tests.test_metrics_sampler` 通过
  需求：spec 5.1.1-2(9)、5.2.1-6
  依赖：1.1

### 4.9 实现 M9 连续自运行规则
- [x] 新建 `backend/app/metrics/rules/m9.py`：取 `sampled_at` 最大采样；要求 `heartbeat_ok=True` 且 `now - sampled_at <= timeout + 允许偏差(30s)`，否则 `EVIDENCE_MISSING`；无采样 `SOURCE_MISSING`；值为 `continuous_seconds/3600`，分子=小时数、分母=1；中断后重新累计的真实 0.0 作为可计算值，并输出中断次数与最近中断时间
  完成标准：`test_metrics_rules` 用例覆盖 P-14（新鲜健康 → 值=小时数）、P-15（中断后为真实 0.0 且中断数可见）、N-28（无采样 → 采集源缺失标记）、N-29（超时 → 证据缺失标记）；`python -m unittest backend.tests.test_metrics_rules backend.tests.test_metrics_sampler` 通过
  需求：spec 5.1.1-2(9)、5.3.1-2
  依赖：4.8、4.2

### 4.10 实现 M1–M3 评测结论读取与报告合并路径
- [x] 新建 `backend/app/metrics/collectors/eval_channel.py` 实现 `EvalConclusionReader.latest_completed(run_dir, expected_set_digest)`：读取最近 `status=COMPLETED` 且 `completed==total` 的 JSON，校验 `set_digest` 与 `eval/eval_set.sha256` 一致，返回 `eval_run_id`/`set_digest`/四类计数与通过率/结果行；新建 `backend/app/metrics/rules/eval_merge.py` 实现 M1–M3 合并：M1 取正例+边界 `detected` 占比，M3 取 `verdict_agrees` 占比，M2 在评测运行未提供显式漏洞检出字段时输出采集源缺失（不本地推导），四类通过率由 results 重算并与文件字段比对
  完成标准：`test_metrics_rules` 用例用现有 `eval/runs/EVALRUN-27714aeffb.json` 断言 `eval_run_id/set_digest` 非空、M1/M3 可计算、M2 为采集源缺失、摘要不符时输出证据不一致（N-25）；`python -m unittest backend.tests.test_metrics_rules backend.tests.test_eval` 通过
  需求：spec 5.5.1-2、5.1.1-5、5.1.3-3
  依赖：2.2、4.2

### 4.11 阶段 4 规则回归与正反例收敛
- [x] 在 `backend/tests/test_metrics_rules.py` 收敛 P-01…P-08、N-01…N-12、N-21、N-30 的规则层断言；确认规则函数在相同输入下多次调用输出完全一致（无隐藏状态）
  完成标准：`python -m unittest backend.tests.test_metrics_rules backend.tests.test_metrics_sampler` 通过；同一视图连续两次 `evaluate` 的 `RuleResult` 逐字段相等
  需求：spec 5.1.1-2、5.3.3、6.2.10
  依赖：4.3、4.4、4.5、4.6、4.7、4.9、4.10

---

## 5. 阶段 5：五道可计算判定

**本阶段不得破坏**：不可计算必须无值（禁止 0/上次值/估算）；原因码只取固定 8 码；判定顺序短路后不得继续计算后续环节；`WINDOW_NOT_CLOSED` 必须同时置 `trial=true`。

### 5.1 实现判定流水线与计算产物
- [x] 新建 `backend/app/metrics/judgment.py`，实现 `ComputabilityPipeline.evaluate(metric_id, definition, rule_result, snapshot, window, now)` 与 `MetricComputation`（值/空值、唯一原因码、缺失采集对象定位、计数、`trial`）；按顺序短路：定义已登记 → 采集源存在 → 证据完整性 → 分母 > 0 → 口径可判定；M1–M3 的采集源为"已完成评测运行"、M9 为"自运行采样"
  完成标准：`backend/tests/test_metrics_judgment.py` 用例逐道构造失败场景，断言首个未通过环节的原因码唯一且后续环节不执行；`python -m unittest backend.tests.test_metrics_judgment` 通过
  需求：spec 5.3.1-1、5.3.1-2、5.3.1-5
  依赖：2.1、2.2、4.2

### 5.2 落地已裁决的口径优先级
- [x] 在 `judgment.py` 固定顺序：分母为 0 → `DENOMINATOR_EMPTY`（先于窗口未闭合）；M5 无法唯一识别首次尝试且受影响 Issue 占分母 → `FIRST_ATTEMPT_EVIDENCE_MISSING`；剔除比例 `> exclusion_ratio_limit(0.10)` → `COVERAGE_INSUFFICIENT`（统一码，附主导剔除原因分布；仅 `covered=0` 且全为证据矛盾时用 `EVIDENCE_INCONSISTENT`）；分母 > 0 且窗口未闭合 → `WINDOW_NOT_CLOSED` 且 `trial=true`；值非有限 → `EVIDENCE_INCONSISTENT`
  完成标准：`test_metrics_judgment` 用例覆盖 N-13（10.1% → `COVERAGE_INSUFFICIENT` 且 `value=None`）、P-08（9.9% → 可计算并带覆盖信息）、N-14（窗口未闭合 → `WINDOW_NOT_CLOSED` + `trial`）、分母 0 与未闭合同时成立时返回 `DENOMINATOR_EMPTY`；`python -m unittest backend.tests.test_metrics_judgment` 通过
  需求：spec 5.3.1-3、5.3.1-4、5.3.1-7、5.3.3-3、5.5.3-4
  依赖：5.1

### 5.3 强制空值与计数一致性
- [x] 在 `MetricComputation` 构造处强制：`computable=true` 时 `value` 为有限实数且 `reason_code=None`；`computable=false` 时 `value=None` 且 `reason_code` 属于 8 码；`trial=true` 蕴含 `computable=false` 与 `WINDOW_NOT_CLOSED`；`covered+excluded` 与分母口径记录数一致
  完成标准：`test_metrics_judgment` 用例尝试构造"不可计算带 0 值""可计算带原因码""trial 与可计算并存"均被拒；`python -m unittest backend.tests.test_metrics_judgment` 通过
  需求：spec 5.3.1-2、6.2.2、6.2.3、6.2.4、5.5.1-5
  依赖：5.2

### 5.4 阶段 5 回归
- [x] 复核判定层不写存储、不读主流程 store；确认 `Metric` 模型层放宽后仍不允许非法组合进入对外输出
  完成标准：`python -m unittest backend.tests.test_metrics_judgment backend.tests.test_metrics_rules` 通过；判定层单测中断言无 `add_*` 调用
  需求：spec 5.3.1-2、4.2.6
  依赖：5.3

---

## 6. 阶段 6：复算服务与三条触发路径

**本阶段不得破坏**：复算对主流程只读；任何失败路径不得改变既有指标记录的 `value/computable/computed_at/recalc_id`；同（窗口, 阶段档）互斥；既有 HTTP 端点行为与错误码不变。

### 6.1 定义复算域类型与异常
- [x] 新建 `backend/app/metrics/types.py`，定义 `RecalcTrigger`（`MANUAL`/`DASHBOARD`/`SCHEDULED`）、`RecalcStatus`（`RUNNING`/`SUCCESS`/`FAILED`）、`RecalcResult`、`RecalcConflict`、`DefinitionMissing`、`RecalcFailed`，并约定 `recalc_id` 形如 `RC-{UTC 时间戳}-{随机后缀}`
  完成标准：`backend/tests/test_metrics_recalc.py` 用例断言 `recalc_id` 唯一、枚举取值固定；`python -m unittest backend.tests.test_metrics_recalc` 通过
  需求：spec 6.3.1、6.3.2、5.4.1-1
  依赖：2.3

### 6.2 实现复算服务主流程与两段式事务
- [x] 新建 `backend/app/metrics/service.py`，实现 `RecalcService.recalc(window, tier, trigger, actor)`：生成 `recalc_id` → 事务外写 `RecalcRun(RUNNING)` → 定义齐备校验（缺任一 → `FAILED(DEFINITION_UNREGISTERED)`，不产生快照）→ 前置校验（快照可读、摘要可核、事件链可校验，失败 → 整次 `FAILED`、零指标写入）→ 采集视图 → 9 个规则 + 判定 → 事务内写 9 条 `Metric` + 剔除清单 + 快照引用 + 复算统计 → 事务外收尾；失败只回滚事务内产物并保留 `RecalcRun(FAILED)`
  完成标准：`test_metrics_recalc` 用例覆盖 N-15/N-16（前置校验失败 → `RecalcRun=FAILED`、零指标写入、既有值不变）、N-18（计算中注入异常 → 事务回滚、无残留剔除清单）、N-22（定义缺失 → 整次拒绝）；`python -m unittest backend.tests.test_metrics_recalc` 通过
  需求：spec 4.2.1、4.2.2、4.2.5、5.4.1-5、5.4.1-6、5.4.1-7、5.4.3-2、4.3.2
  依赖：3.2、3.3、4.11、5.3

### 6.3 实现互斥守卫与幂等覆盖
- [x] 在 `backend/app/metrics/service.py` 实现 `RecalcGuard`（`dict[(window, tier)] -> recalc_id` + `threading.Lock`，非阻塞获取；冲突立即抛 `RecalcConflict` 附进行中 `recalc_id`）并接入 `recalc`；确认同一（窗口, 阶段档, 定义版本）重复复算覆盖同一条 9 条记录、`recalc_id` 为最后一次、指标记录条数恒为 9
  完成标准：`test_metrics_recalc` 用例覆盖 N-19（并发第二个请求被拒、零写入）、P-11（连续两次复算后记录仍 9 条且 `recalc_id` 为第二次）、P-10（同一快照两次复算逐字段一致，除 `computed_at/recalc_id`）；`python -m unittest backend.tests.test_metrics_recalc` 通过
  需求：spec 4.2.2、4.2.3、5.4.1-3、5.4.1-4、5.4.3-1
  依赖：6.2

### 6.4 实现定时调度器（窗口闭合补做与每日复算）
- [x] 新建 `backend/app/metrics/scheduler.py`，实现 `RecalcScheduler.tick(now)`：候选窗口为当前与前 11 个自然月；已归档报告跳过；窗口闭合且无成功复算 → 立即发起（`now > end + 1h` 时 `late=true`）；距上次成功 ≥86400s → 再发起；幂等 key `scheduler:{window}:{tier}:{UTC 日期}`；锁冲突记 `skipped_locked`；`scheduler_enabled=false` 时不执行
  完成标准：`test_metrics_recalc` 用例覆盖"闭合满 1 小时无成功 → 自动发起并标 `late`"、"同一天不重复发起"、"已归档窗口跳过"、"锁冲突跳过"；`python -m unittest backend.tests.test_metrics_recalc` 通过
  需求：spec 5.4.1-1、5.4.1-2、5.4.3-4
  依赖：6.3

### 6.5 扩展错误码并开放三条触发入口
- [x] 在 `backend/app/api/envelope.py` 新增 `VF-7002 RECALC_CONFLICT(409)`、`VF-7003 RECALC_FAILED(500)`、`VF-7004 DEFINITION_MISSING(422)`、`VF-7005 REPORT_INCONSISTENT(409)`、`VF-7006 SNAPSHOT_INTEGRITY(409)`（既有码不变）；在 `backend/app/main.py` 新增 `POST /api/v1/metrics/recalc`（`MANUAL`/`DASHBOARD` 共用服务，显式要求 `window`/`tier`，`x-actor` 必填，`metrics.operator_token` 非空时校验 `x-operator-token`）与 `GET /api/v1/metrics/recalc/{recalc_id}`
  完成标准：新建 `backend/tests/test_metrics_api.py`，用例覆盖三种触发方式均生成 `recalc_id`、并发冲突 409 `VF-7002` 附进行中标识、定义缺失 422 `VF-7004`、令牌不符 401 `VF-1004`（N-27）、失败 500 `VF-7003`；`python -m unittest backend.tests.test_metrics_api` 通过
  需求：spec 5.4.1-1、4.3.1、4.3.2、3.1
  依赖：6.3、6.4

### 6.6 装配服务与生命周期
- [x] 在 `backend/app/container.py` 增加 `RecalcService`、`RecalcGuard`、`RecalcScheduler`、`MetricsRepository` 的装配；在 `backend/app/config.py` 新增 `metrics` 配置段（`definition_version`、`exclusion_ratio_limit`、`coverage_delta_tolerance_pp`、`snapshot_dir`、`report_dir`、`eval_run_dir`、`self_run_sample_path`、`scheduler_enabled`、`scheduler_tick_seconds`、`recalc_on_close_delay_seconds`、`daily_recalc_seconds`、`operator_token`、`capture_budget_ms`，全部带默认值，`extra="forbid"` 不变）；在 `main.py` lifespan 中按开关启动调度后台任务
  完成标准：`python -m unittest backend.tests.test_config backend.tests.test_metrics_api` 通过；断言不写 `metrics` 段时全部取默认值、`scheduler_enabled` 默认 `false`、`operator_token` 为空时不强制
  需求：spec 4.1、4.3.1、5.4.1-2
  依赖：6.5

### 6.7 阶段 6 回归
- [x] 复核复算失败不污染、只读探针、互斥释放（异常路径也必须释放锁）；确认既有 253 用例基线不回归
  完成标准：`python -m unittest backend.tests.test_metrics_recalc backend.tests.test_metrics_api backend.tests.test_state_machine backend.tests.test_gate` 通过；断言 `RecalcGuard` 在异常后无残留锁
  需求：spec 4.2.5、5.4.3-2、5.4.1-5
  依赖：6.6

---

## 7. 阶段 7：落库与报告改造

**本阶段不得破坏**：报告只读落库记录、不重算；同窗口同档历史报告不被覆盖；`GET /api/v1/metrics` 只增字段；看板既有在办数/熔断/失败 Top N 口径不变；`docs/devlog/m5-eval-report.md` 不被改写。

### 7.1 实现指标侧仓储读写
- [x] 在 `backend/app/metrics/repository.py` 完成 `MetricsRepository`/`AttemptRepository` 的 `MemoryStore` 适配实现（`put_definition/effective_definition`、`put_snapshot/get_snapshot`、`put_recalc/update_recalc/get_recalc/in_progress`、`put_metric/metrics_for`、`put_exclusions/exclusions`、`put_report/get_report/next_report_version`、四类尝试历史的 `record_*/list_*`）
  完成标准：`backend/tests/test_metrics_report.py` 用例断言 `metrics_for` 按窗口/档过滤、`next_report_version` 同窗口同档递增（1→2）、剔除清单按 `(recalc_id, metric_id)` 独立保存且历史复算清单可回读；`python -m unittest backend.tests.test_metrics_report` 通过
  需求：spec 6.2、6.3、6.4、6.5、5.4.1-8
  依赖：2.4、6.2

### 7.2 实现报告服务（要素校验、一致性、结论、版本、归档）
- [x] 新建 `backend/app/metrics/report.py`，实现 `MetricReportService.generate(window, tier, actor)`：前置校验 9 项定义已生效、9 条记录存在；逐指标比对 `value/computable/reason_code/definition_version/recalc_id/computed_at/covered_count/excluded_count` 与落库记录（不一致 → `VF-7005` 拒绝）；结论规则（`trial` → "不可判定（试算）"；初赛必需指标 M1/M4/M5/M9 任一不可计算 → `UNDETERMINED`；全部可计算且任一未达标 → `FAIL`；M1–M3 缺 `eval_run_id/set_digest` 或 M4–M9 缺 `recalc_id/snapshot_digest` → 该行不进对外报告且结论 `UNDETERMINED`；全部满足 → `PASS`）；版本递增并归档（`RPT-{window}-{tier}-{4 位序号}`，`put_locked`），渲染 Markdown + JSON
  完成标准：`test_metrics_report` 用例覆盖 P-13（版本 1→2 且版本 1 可回读）、N-23（篡改记录值 → 拒绝生成并列出编号）、N-24（混合定义版本 → 拒绝）、N-25（缺评测标识 → 行移除且结论不可判定）、必需指标不可计算 → 不可判定、结论禁止在不可计算时写 PASS；`python -m unittest backend.tests.test_metrics_report` 通过
  需求：spec 5.5.1-2、5.5.1-3、5.5.1-4、5.5.1-5、5.5.1-6、5.5.1-7、5.5.3-1、6.5
  依赖：7.1、5.3

### 7.3 开放报告与快照校验接口
- [x] 在 `backend/app/main.py` 新增 `POST /api/v1/metrics/reports`、`GET /api/v1/metrics/reports/{report_id}`、`GET /api/v1/metrics/snapshots/{snapshot_id}/verify`，错误映射到 `VF-7004/VF-7005/VF-7001/VF-7006`；归档不可用时返回成功但 `archived=false` 且禁止对外发布
  完成标准：`test_metrics_api` 用例覆盖报告生成/回读摘要一致（spec 5.5.1-8）、快照摘要不符 → 409 `VF-7006`、报告不一致 → 409 `VF-7005`、归档失败 → `archived=false`；`python -m unittest backend.tests.test_metrics_api` 通过
  需求：spec 5.5.1-8、5.5.3-3、4.3.1
  依赖：7.2

### 7.4 改造看板首屏与指标查询字段
- [x] 在 `backend/app/dashboard/service.py` 的 `summary.metrics` 增加 `reason_code`/`channel`/`recalc_id`/`computed_at`/`trial`/`last_success_at`/`last_failure`（最近失败时间与原因）；在 `main.py` 的 `GET /api/v1/metrics` 增加新字段并支持 `window`/`tier` 过滤（不传时仍返回全部，兼容旧调用）；不可计算项显示原因码，最近失败时并列显示上次成功时间
  完成标准：`test_metrics_api` 用例断言字段超集、不传参数返回全量（兼容）、失败后 `last_failure` 与 `last_success_at` 同时存在、只读无修改入口；`python -m unittest backend.tests.test_metrics_api backend.tests.test_m4_dashboard` 通过
  需求：spec 5.6.1-1、5.6.1-3、5.6.1-4、5.6.3-1
  依赖：7.2

### 7.5 实现指标下钻
- [x] 新建 `backend/app/dashboard/drilldown.py`，实现 `MetricDrilldownService`：按（指标, 档, 窗口）返回参与计算 Issue 清单与证据引用、剔除清单（Issue 标识 + 原因码 + detail）、`channel_excluded_count`、快照可校验状态；快照不可用时 `verifiable=false` 但保留指标值；在 `main.py` 开放 `GET /api/v1/metrics/{metric_id}/drilldown`，窗口与记录不一致时拒绝（禁止跨窗口拼合）
  完成标准：`test_metrics_api` 用例覆盖下钻返回覆盖/剔除清单（spec 5.6.1-2）、快照被清理时提示"证据不可用"且值保留（N-环境用例）、跨窗口请求返回错误；`python -m unittest backend.tests.test_metrics_api` 通过
  需求：spec 5.6.1-2、5.6.3-2、5.6.3-3
  依赖：7.4

### 7.6 迁移报告脚本并保留历史文件
- [x] 改造 `scripts/run_eval.py`：只输出评测通道专项报告（四类通过率 + M1–M3），并调用 `MetricReportService` 生成主流程报告到 `docs/devlog/metrics-report.md` 与归档目录 `docs/devlog/metrics/`；不再用空 `MemoryStore` 计算 M4–M9、不再输出硬编码"缺采集源"；`docs/devlog/m5-eval-report.md` 保持只读、不再追加内容；将 `MetricCalculator.calculate()` 降级为 legacy 兼容入口（固定旧定义/窗口，委托新服务或保留旧行为并标 deprecated），`describe()` 不变
  完成标准：`test_metrics_report` 用例 N-26：空 store 场景输出 8 码真实原因（`SOURCE_MISSING` 等）而非硬编码文案；生成后断言 `m5-eval-report.md` 的 sha256 与运行前一致；`MetricCalculator.describe()` 输出与改造前逐字段相等；`python -m unittest backend.tests.test_metrics_report backend.tests.test_eval_runner` 通过
  需求：spec 5.5.1-5、4.5.1、4.5.2
  依赖：7.2、7.3

### 7.7 阶段 7 回归
- [x] 复核落库与报告一致、历史版本可检索、看板既有字段不回归；确认 `GET /api/v1/metrics` 旧响应字段全部保留
  完成标准：`python -m unittest backend.tests.test_metrics_report backend.tests.test_metrics_api backend.tests.test_m4_admin backend.tests.test_m4_dashboard backend.tests.test_api_m1` 通过
  需求：spec 5.5.1-7、4.5.1、5.6.1-4
  依赖：7.6

---

## 8. 阶段 8：主流程实跑复算与报告产出

**本阶段不得破坏**：实跑只使用本地适配器，不触碰真实外部系统；实跑产生的证据只追加、不复写既有 Agent 结果；旧报告文件保持原样。

### 8.1 建立主流程证据夹具
- [x] 新建 `backend/tests/support/__init__.py` 与 `backend/tests/support/mainflow_builder.py`：提供 `run_full_chain(store, issue_id, ...)`（复用 `LocalRepoAdapter` + `RecordedPipelineClient.all_passed()` + Reproducer/Patcher/Critic/Gatekeeper，走真实迁移产生证据）与 `seed_synthetic(store, window, counts)`（直接写入完整/半链路/矛盾/跨窗口/多尝试/EVAL 记录，用于规模与规则覆盖）；提供 `build_preliminary_window(...)` 一次性构造 2026-12 初赛窗口
  完成标准：`backend/tests/test_metrics_e2e.py` 用例断言 `run_full_chain` 产出 `Verdict/Proof/ReproductionAttempt/Patch/PatchAttempt/GateAttempt/GateResult/Disposition(ready_at)/Event` 且事件链 `verify_chain` 为真；`python -m unittest backend.tests.test_metrics_e2e` 通过
  需求：spec 1.2、5.2.1-3、2 术语"主流程运行证据"
  依赖：1.6、7.2

### 8.2 提供离线复算命令
- [x] 新建 `scripts/recalc_metrics.py`，参数 `--window`、`--tier`、`--now`、`--evidence-root`、`--report-path`，流程：构造/加载主流程 store（夹具或 `--fixture` 模式）→ `RecalcService.recalc(...)` → `MetricReportService.generate(...)` → 打印 9 行摘要（值/可计算/原因码/覆盖/剔除）与报告路径；退出码：成功 0、失败 1，失败时打印 `recalc_id` 与失败原因
  完成标准：`python scripts/recalc_metrics.py --window 2026-12 --tier PRELIMINARY` 退出码 0，输出 9 行摘要且 `docs/devlog/metrics-report.md` 存在；同一命令连续执行两次后指标记录仍为 9 条、报告版本递增；`python -m unittest backend.tests.test_metrics_e2e` 通过
  需求：spec 5.4.1-1、5.5.1-1、5.5.1-6
  依赖：8.1、7.6

### 8.3 执行主流程全量复算并核对口径
- [x] 用 2026-12 初赛窗口夹具执行一次全量复算：生成 `RecalcRun(SUCCESS)`、9 条 `Metric`、剔除清单、`MetricSnapshotRef`，并核对 M4/M5/M7/M8 可计算且分子分母可逐条对应，M6 有门禁结论时可计算，M9 有新鲜采样时可计算
  完成标准：`test_metrics_e2e` 用例断言 P-01 全部指标可计算、`value` 与 `numerator/denominator` 一致、`covered+excluded` 与分母口径一致、`recalc_id/snapshot_digest` 非空；`python -m unittest backend.tests.test_metrics_e2e` 通过
  需求：spec 5.1.1-2(4)–(9)、5.5.1-1、6.2.2、6.2.5、6.2.7
  依赖：8.2

### 8.4 生成对外指标报告并保留历史留痕
- [x] 用报告服务生成 `docs/devlog/metrics-report.md`（含 M1–M9 定义、分子分母、采集源、通道、值、可计算状态、原因码、初赛目标、是否达标、计算时间、复算标识、快照摘要/评测运行标识、覆盖/剔除摘要、结论），并把版本化报告归档到 `docs/devlog/metrics/`；确认 `docs/devlog/m5-eval-report.md` 内容与 sha256 不变
  完成标准：报告文件包含 9 行且每行标识齐备（缺标识行不出现）、结论与落库一致；`test_metrics_e2e` 用例断言旧报告文件前后 sha256 相同、归档目录新增 `RPT-*.md|json`；`python -m unittest backend.tests.test_metrics_e2e` 通过
  需求：spec 5.5.1-2、5.5.1-3、5.5.1-4、5.5.1-6、6.5
  依赖：8.3

### 8.5 实跑三条触发路径
- [x] 分别以人工 API（`MANUAL`）、看板触发（`DASHBOARD`）、定时 tick（`SCHEDULED`，含窗口闭合补做）执行复算，确认三者共用同一服务路径、均生成 `recalc_id`、均记录触发方式与发起主体、并发冲突时零写入
  完成标准：`test_metrics_e2e` 用例断言三种触发方式的 `RecalcRun.trigger` 正确、`actor` 记录（定时为 `scheduler:metrics`）、补做场景 `late=true`、第二次并发请求 409；`python -m unittest backend.tests.test_metrics_e2e backend.tests.test_metrics_api` 通过
  需求：spec 5.4.1-1、5.4.1-2、5.4.1-4、6.3.2、6.3.3
  依赖：8.3、6.5

### 8.6 替换"不可计算（缺采集源）"的验收核对
- [x] 对照 `docs/devlog/m5-eval-report.md` 中 M4–M9 行逐项核对：M4/M5/M7/M8 由复算给出数值；M6 不再写"缺 Pipeline 日志"；M9 由采样给出小时数；无采集源时输出对应真实原因码与缺失对象定位；把核对结论写入 `docs/devlog/metrics-report.md` 的目标达成说明
  完成标准：`python scripts/recalc_metrics.py --window 2026-12 --tier PRELIMINARY` 输出中 M4–M9 无"缺采集源"硬编码文案；`test_metrics_e2e` 用例断言 `metrics-report.md` 不含字符串"缺 Pipeline 日志"、且每个不可计算项带 8 码之一；DoD 1/2/3 逐项有对应断言
  需求：spec 5.1.1-2、5.3.1-5、design 完成定义 1–3
  依赖：8.4、8.5

---

## 9. 阶段 9：回归加固与交付收口

**本阶段不得破坏**：既有 253 用例基线；状态机、`main` 不合并、通道隔离、旧数据兼容四类硬约束必须由测试守护，而不是仅靠文档声明。

### 9.1 全量回归
- [x] 执行全量 unittest 回归，确认既有 253 用例与新增用例全部通过；记录用例总数与耗时到 `docs/devlog/metrics-report.md` 的验证说明
  完成标准：`python -m unittest discover -s backend/tests -p "test_*.py"` 通过（0 failure/0 error，用例数 ≥253）；单文件失败时给出可复现命令
  需求：spec 4.2、4.4
  依赖：8.6

### 9.2 不变量守护测试
- [x] 新建 `backend/tests/test_metrics_invariants.py`，固化：① 状态迁移集合与关键守卫（跳步被拒、`main` 硬拒）不变；② `computable=False` 时 `value` 必空、`reason_code` 必属 8 码；③ `EVAL` 记录不进入 M4–M9 分子分母（P-09/N-03）；④ `GET /api/v1/metrics` 响应为旧字段超集、旧式 `Metric` 构造可用；⑤ 旧 v1 定义可查、旧 v1 指标记录可读；⑥ 复算 2026-12 不改变 2026-11 窗口记录
  完成标准：`python -m unittest backend.tests.test_metrics_invariants` 通过；用例失败信息明确指出被破坏的不变式编号
  需求：spec 4.2.5、5.1.1-5、5.2.1-2、4.5.1、5.4.1-8
  依赖：9.1

### 9.3 性能预算验证
- [x] 新建 `backend/tests/test_metrics_perf.py`，用 `time.perf_counter` 断言：50 Issue 全量复算 ≤5s（PERF-01）、1000 Issue/约 1.2 万事件 ≤60s 且快照抓取 ≤200ms（PERF-02）、报告生成 ≤3s（PERF-04）、复算前后记录与摘要逐项一致（READ-01）；支持 `VERIFIX_SKIP_PERF=1` 跳过
  完成标准：`python -m unittest backend.tests.test_metrics_perf` 通过并把实测耗时打印到标准输出；跳过模式下 `VERIFIX_SKIP_PERF=1 python -m unittest backend.tests.test_metrics_perf` 通过（用例标记 skipped）
  需求：spec 4.1-1、4.1-2、4.1-3、4.2.4
  依赖：9.1

### 9.4 兼容性与历史保留核对
- [x] 核对：旧 `Metric`（v1 字段集）记录可被 `GET /api/v1/metrics` 与看板展示；旧报告 `m5-eval-report.md` 可读且未被改写；历史窗口（2026-11 及更早）指标记录在复算 2026-12 后值/时间/复算标识不变；`AppConfig` 不写 `metrics` 段仍可加载
  完成标准：`python -m unittest backend.tests.test_metrics_invariants backend.tests.test_config backend.tests.test_m4_dashboard` 通过；`python -c` 冒烟：加载旧配置文件并调用 `load_config()` 成功（在 `test_config` 中固化，不新增裸命令）
  需求：spec 4.5.1、4.5.3、5.4.1-8、6.2
  依赖：9.2

### 9.5 文档与边界说明
- [x] 更新 `docs/devlog/metrics-report.md` 的验证说明章节（验收命令、用例数、性能实测、无 Docker/无云凭据/无 redis 的验证方式）与 `docs/devlog/00-conventions.md` 的指标口径索引；记录单实例边界（`RecalcGuard` 仅进程内有效，多实例需外部锁，不在本次范围）
  完成标准：文档包含九阶段验收命令清单与 4 项已裁决口径的落点说明；`m5-eval-report.md` 未被修改
  需求：spec 4.2.3、4.4.1、4.4.3
  依赖：9.3、9.4

### 9.6 最终验收清单与 DoD 对照
- [x] 逐项核对 design 完成定义 1–5 与本文件阶段 1–9 的验收门，输出"通过/未通过/不适用"三态清单；未通过项给出阻塞任务编号与复现命令，不允许以"环境限制"作为通过理由
  完成标准：`docs/devlog/metrics-report.md` 中 DoD 1–5 每项均有对应命令与结论；`python -m unittest discover -s backend/tests -p "test_*.py"` 与 `python scripts/recalc_metrics.py --window 2026-12 --tier PRELIMINARY` 均通过；任务清单 60 项全部勾选或明确标注阻塞
  需求：design 完成定义 1–5、spec 1.3、5.5.1
  依赖：9.1–9.5

---

## 附：交付物清单

| 类别 | 交付物 |
|---|---|
| 新增源码 | `backend/app/metrics/{reason_codes,definitions,isolation,snapshot,judgment,service,scheduler,report,types,repository}.py`、`backend/app/metrics/collectors/{main_flow,eval_channel,runtime_sampler}.py`、`backend/app/metrics/rules/{base,m4,m5,m6,m7,m8,m9,eval_merge}.py`、`backend/app/dashboard/drilldown.py` |
| 改造源码 | `backend/app/domain/{enums,models}.py`、`backend/app/repo/{memory,interfaces}.py`、`backend/app/agents/{reproducer,patcher,gatekeeper}/service.py`、`backend/app/runtime/self_run.py`、`backend/app/eval/runner.py`、`backend/app/dashboard/service.py`、`backend/app/main.py`、`backend/app/container.py`、`backend/app/config.py`、`backend/app/api/envelope.py`、`backend/app/metrics/calculator.py`、`scripts/run_eval.py` |
| 新增测试 | `backend/tests/test_metrics_{evidence,definitions,isolation,snapshot,rules,sampler,judgment,recalc,api,report,e2e,invariants,perf}.py`、`backend/tests/support/mainflow_builder.py` |
| 新增脚本 | `scripts/recalc_metrics.py` |
| 产出文件 | `docs/devlog/metrics-report.md`、`docs/devlog/metrics/RPT-*.md|json`（归档）；`docs/devlog/m5-eval-report.md` 保持原样 |