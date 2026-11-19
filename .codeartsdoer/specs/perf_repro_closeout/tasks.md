# PERF-02 阈值口径与 D1-1 编码依赖 · 编码任务清单（tasks.md）

> 上游需求：`.codeartsdoer/specs/perf_repro_closeout/spec.md`（393 行，v1.0）
> 上游设计：`.codeartsdoer/specs/perf_repro_closeout/design.md`（751 行，v1.0，D-01…D-14 / I-01…I-07 / AC-P01…AC-P12）
> 生成日期：2026-11-19
> 本轮性质：**裁定 + 测量协议 + 证据登记 + 验收**。不含产品代码修复，不含断言/阈值/sleep/skip/数据量调整。
> 本清单只做任务规划，**不执行任何编码、不执行任何 git 操作、不修改任何既有文档或代码**。

---

## 0. 前置强制口径（先读，违反即判任务不合格）

### 0.1 冻结项 F-1…F-7（逐条可检测，任何一项被突破即整轮不验收）

| 编号 | 冻结内容 | 检测方式（可实测） | 对应条款 |
|---|---|---|---|
| F-1 | 断言与门槛数值一律不改：`PERF-02/metrics-capture` 200ms、全量复算 60s、`PERF-01` 5s、`PERF-04` 3s、`PERF-02/eval-digest` 500ms | `git diff --stat -- backend/tests/test_metrics_perf.py backend/app/config.py` 输出为空；`grep -n "capture_budget_ms" backend/app/config.py` 仍为 `140`、`275`、`276` 三行 | spec 4.1-1、5.1.1-6 |
| F-2 | 不引入 `sleep` / 重试放大 / 等待窗口等"修绿"手段 | 变更集 `git diff` 中 `sleep`、`time.sleep` 命中数为 0（`scripts/perf_probe.py`、`scripts/d1_clean_install_check.py` 内的线程同步仅允许 `threading.Event`，且必须只用于并发段启停） | spec 1.4-2、5.1.1-6a |
| F-3 | 不跳用例：`VERIFIX_SKIP_PERF` 不得使用，`@unittest.skip` 不得新增 | `grep -rn "VERIFIX_SKIP_PERF" backend/tests/` 命中行号不变；`git diff -- backend/tests/` 为空 | spec 1.4-2、design 1.2.2 |
| F-4 | 不减数据量：构造数据保持 **1100 Issue / 12000 事件** | 采集器 `--selftest` 输出 `scale issue=1100 events=12000` 且 `assertEqual(event_count,12000)` 通过 | spec 6.1-4、design 1.2.2 |
| F-5 | 不改历史报告正文与已归档自检结果：`docs/devlog/selfcheck/SC-*`（4 目录 × 2 文件）、`index.json`、`m13-analysis-plan.md`、`m13-selfcheck-report.md`、`m12-closure-and-blockers.md`、`vcs-baseline.md`、`.evidence/git-baseline/*`、`README.md`、`metrics-report.md` | 组 0.2 的 `sha256` 基线在结项时逐项复算一致（36 个路径，差异必须为 0） | spec 4.5-1、6.3-6、D-06 |
| F-6 | 不接远端、不出网：不做 `git push`/`fetch`/`clone`，不访问云服务 | 变更记录中 `git` 子命令仅允许 `archive`、`rev-parse`、`status`、`ls-files`、`diff`、`log`；`git branch -r` 输出不新增 | spec 1.4-5、4.3-2、design 2.6-6 |
| F-7 | 不补五步留痕提交、不 `amend`、不改历史提交时间 | `git rev-list --count HEAD` 结项时仍为 `4`（`ecfcad3`/`b61445b`/`bb93b31`/`9b24a95`）；`git log --format=%H -4` 哈希不变；环境变量 `GIT_AUTHOR_DATE`/`GIT_COMMITTER_DATE` 从未被设置 | spec 1.4-5、design 2.6 |

### 0.2 只登记不修复项（**不得为其生成任何修复型编码任务**）

| 编号 | 事实 | 本项允许的动作 | 明确禁止 |
|---|---|---|---|
| `RF-01` | `backend/tests/test_check_devlog.py:90-94` 断言"非 Git 仓库"，Git 化后稳定失败（实测 `failures=1`，输出"阻塞项合计：7"） | 登记七字段（spec 6.4） | 改用例断言、改 `scripts/check_devlog.py`、加 `skip`、改返回值 `0/2/3` 语义 |
| `RF-02` | `PERF-02` 同时指 200ms 抓取（`test_metrics_perf.py:104`）与 500ms 摘要三元组（`:168`） | 登记位置索引 + 新载体强制限定词 | 改历史文档裸写、改任一用例编号、合并两个用例 |
| `RF-03` | 全量回归写被 Git 跟踪的 `.evidence/self_run_samples.jsonl`（`main.py:583-585`） | 登记 + 结项前还原为 HEAD | 改 `main.py` 写入逻辑、把文件加入 `.gitignore`、删文件、测试注入隔离（属另立项） |
| `IF-01` | `metrics.capture_budget_ms`（`config.py:140`）全仓无消费点 | 登记为实现缺口 | 实现 `CAPTURE_SLOW` 告警（本项不含产品代码） |

### 0.3 命名与表述强制口径

| 编号 | 口径 | 禁止写法 |
|---|---|---|
| N-1 | `PERF-02` 一律带限定词：`PERF-02/metrics-capture` 或 `PERF-02/eval-digest` | 裸写 `PERF-02` 作为结论主体 |
| N-2 | 环境只允许两档：`default`（剥离全部 `PYTHON*`）/ `clean`（显式保留集合） | 写"默认环境""本机环境"而不列 `PYTHON*` 状态 |
| N-3 | 结论只允许四类：性能缺陷 / 阈值口径问题 / 环境可复现性缺陷 / 文档口径问题 | "性能已优化""全部用例通过""可复现性已修复""已修复" |
| N-4 | 每份证据必须同时含：命令 + 退出码 + 环境声明 + 样本/用例数 + 证据路径 | 只给结论、只给单一数字 |
| N-5 | 证据文件名时间戳**精确到秒**，同名即报错，禁止覆盖 | 覆盖既有 `samples-*.jsonl` |

### 0.4 提交边界（本清单默认**零提交**）

| 编号 | 情形 | 是否产生提交 | 说明 |
|---|---|---|---|
| C-0 | **默认执行路径** | **0 个** | 全部任务只写工作区文件（`scripts/*`、`docs/devlog/perf-repro-closeout.md`、`.evidence/perf-repro/*`），不执行 `git add` / `git commit` |
| C-1 | 维护者**显式书面授权**后（可选，不属于本清单任务） | 至多 1 个 | 唯一候选时点：组 7.8 与组 8.4 完成后的一次性登记提交，标题建议 `docs(perf-repro): 登记 PERF-02 阈值口径与 D1-1 分层补验证据`；**不得**使用 `[step-N/…]` 五步前缀，**不得** `amend`，**不得** `push` |
| C-2 | 任何其他时点 | 0 个 | 组 9 只登记未跟踪清单，不收纳提交 |

> 执行纪律：未获得 C-1 授权前，**任何任务都不得调用 `git add` / `git commit` / `git tag`**；`git archive` 仅用于组 3.1 的只读导出。

### 0.5 执行顺序总览

| 组 | 名称 | 依赖 | 不可调换点 |
|---|---|---|---|
| 0 | 冻结与基线采集 | — | ⛔ 必须最先执行，0.2 的指纹是结项对账基准 |
| 1 | 证据载体与写入契约 | 0 | ⛔ 必须先于组 2/3/4（写入通道先于取证） |
| 2 | `PERF-02/metrics-capture` 测量协议 | 1 | ⛔ 2.1 环境声明先于 2.3/2.4 采样 |
| 3 | D1-1 逐层补验 | 1 | ⛔ 3.1 → 3.2 → 3.3 → 3.4 严格串行，任一层未通过不得执行下一层 |
| 4 | 裁定与三方语义对照 | 2、3 | ⛔ 4.1 三方原文先于 4.2/4.3 裁定 |
| 5 | 回归基线与四类失败分列 | 3、4 | ⛔ 基线必须晚于 D1-1 分层结论 |
| 6 | 关联发现登记（只登记不修复） | 5 | 只写登记，不写修复代码 |
| 7 | 登记载体成文 | 2、3、4、5、6 | ⛔ 7.8 指纹对账必须最后 |
| 8 | 验收映射与冻结自检 | 7 | ⛔ 最后一组 |
| 9 | 交接与边界声明 | 8 | 只登记，不提交 |

---

## 1. 冻结与基线采集

> 冻结项：F-1…F-7 全量生效。本组只读采集，零写入既有载体。

- [ ] **1.1 冻结 F-1…F-7 并落成可检测清单**
  - 动作：把 §0.1 表格写入 `.evidence/perf-repro/freeze-manifest-<ts>.md`，每条补齐"当前基线值 + 检测命令 + 违反判定"，并把检测命令写成可直接粘贴执行的单行。
  - 完成判定：表格 7 行齐全；7 条检测命令逐条实跑并记录退出码与输出摘要（其中 F-1 的 `git diff --stat` 必须输出为空、F-7 的 `git rev-list --count HEAD` 必须输出 `4`）；文件内无"允许放宽/可接受偏离"表述（`grep -c "允许放宽" = 0`）。
  - 依赖：无。
  - 引用：spec 1.4-1…7、5.1.1-6a、5.3.1-6a；design 2.6、2.8；F-1…F-7。

- [x] **1.2 采集不可变载体指纹基线（36 个具体路径）**
  - 动作：按 design 1.2.8 清单展开为具体路径，逐条记录 `path / bytes / sha256 / mtime / captured_at`，写入 `.evidence/perf-repro/immutable-baseline-<ts>.json`。展开口径：自检归档 `SC-*/report.md` × 4 + `SC-*/selfcheck.json` × 4 + `selfcheck/index.json` × 1 + 文档 6（`m13-analysis-plan.md`、`m13-selfcheck-report.md`、`m12-closure-and-blockers.md`、`vcs-baseline.md`、`metrics-report.md`、根 `README.md`）+ `.evidence/git-baseline/` 实测 17 个文件 + 代码 4（`backend/tests/test_metrics_perf.py`、`backend/tests/test_check_devlog.py`、`backend/app/metrics/snapshot.py`、`backend/app/config.py`）。
  - 完成判定：条目数 = 36；每项 `sha256` 为 64 位小写十六进制且与 `sha256sum` 独立复算一致；文件可被 `python -c "import json;json.load(open(...))"` 解析成功；清单中**不含**本轮将新增的 4 个路径（`scripts/perf_probe.py`、`scripts/d1_clean_install_check.py`、`docs/devlog/perf-repro-closeout.md`、`.evidence/perf-repro/**`）。
  - 依赖：1.1。
  - 引用：spec 4.5-1、6.3-6；design 1.2.8、D-06；F-5。

- [ ] **1.3 冻结门槛数值表（5 个数值 + 来源行号）**
  - 动作：登记 `PERF-02/metrics-capture`=200ms（`config.py:140`、`test_metrics_perf.py:104`）、全量复算=60s（`test_metrics_perf.py:111`）、`PERF-01` 复算=5s（`test_metrics_perf.py:74`）、`PERF-04` 报告=3s（`test_metrics_perf.py:123`）、`PERF-02/eval-digest`=500ms（`test_metrics_perf.py:168`）。
  - 完成判定：5 行齐全，每行"数值 + 文件 + 行号"可就地复读（按行号打开该文件，数值字符串完全命中）；文件内标注 `immutable=true` 且写明"本项不授权任何门槛调整"。
  - 依赖：1.1。
  - 引用：spec 4.1-1、5.1.1-6；design 1.2.2；F-1。

- [x] **1.4 采集环境事实基线并判定 `default` 模式是否成立**
  - 动作：记录 `os`（Windows-11-10.0.26300-SP0）、`python_version`（3.12.10）、`PYTHONUTF8`、`PYTHONIOENCODING`、`PYTHONPATH` 实测值，并给出结论：当前 shell `PYTHONIOENCODING='utf8'`，因此**继承式运行不构成 spec 定义的 `default` 模式**，采集器必须剥离后再声明。
  - 完成判定：5 个环境项均有实测值（`None` 与空值须区分写法）；记录含一条判定句"继承 `PYTHONIOENCODING='utf8'` 的执行不得声明为 `default`"；同一条命令连续执行 2 次得到相同值（证明非偶发）。
  - 依赖：1.1。
  - 引用：spec 5.2.1-6、5.2.3-3、6.1-5；design 1.2.4、D-02、I-06；N-2。

---

## 2. 证据载体与写入契约

> 冻结项：F-5（写入目标必须在白名单内）、F-6（不出网）。
> 本组产物是后续所有证据的唯一写入通道，任何后续任务**不得绕过** `append_record`。

- [ ] **2.1 创建证据目录与文件命名规范**
  - 动作：创建 `.evidence/perf-repro/`，落一份命名规范 `naming.md`，定义 7 类文件名：`samples-<case>-<ts>.jsonl`、`measure-<case>-<ts>.json`、`write-block-<case>-<ts>.json`、`d1-1-<layer>-<ts>.json`、`decision-<topic>-<ts>.json`、`immutable-baseline-<ts>.json`、`freeze-manifest-<ts>.md`；`<ts>` 为 `YYYYMMDDTHHMMSS`（秒级），`<case>` 只允许 `metrics-capture` / `eval-digest`，`<layer>` 只允许 `config-load` / `clean-export` / `install` / `full-regression`。
  - 完成判定：目录存在；`naming.md` 列出 7 类名称且 `<case>`、`<layer>` 枚举值与设计一致；用规范内的名字构造 2 个样例路径（一个合法、一个 `<case>=PERF-02` 裸编号），合法路径被接受、裸编号被拒绝并报 `INVALID_CASE_ID`。
  - 依赖：1.2。
  - 引用：spec 6.1-1、6.2-1、4.4-2；design 2.1.2、D-05、D-08；N-1、N-5。

- [x] **2.2 实现 `append_record` 追加写契约与 `READONLY_VIOLATION` 硬门**
  - 动作：在 `scripts/perf_probe.py` 内实现 `append_record(path, record)`：JSONL 追加 1 行、JSON 单次独占、同名抛 `OUTPUT_EXISTS`、目标落在 §1.2 的 36 个不可变路径或 `docs/devlog/selfcheck/**` 内抛 `READONLY_VIOLATION`。
  - 完成判定：`python scripts/perf_probe.py --selftest` 退出码 0，输出 3 条 `PASS`：（a）追加后目标文件行数由 N 变 N+1 且原前 N 行 `sha256` 不变；（b）对已存在 JSON 重名写入抛 `OUTPUT_EXISTS` 且文件字节未变；（c）向 `docs/devlog/selfcheck/index.json` 写入抛 `READONLY_VIOLATION` 且该文件 `sha256` 不变。
  - 依赖：2.1。
  - 引用：spec 4.4-2、4.5-1；design I-04、D-05；F-5。

- [x] **2.3 实现 8 类记录的 schema 校验（缺字段即拒写）**
  - 动作：为 `EnvironmentDeclaration`、`PerfSampleRecord`、`MeasurementRecord`、`WriteBlockRecord`、`ReproducibilityRecord`、`CloseoutDecisionRecord`、`RelatedFindingRecord`、`SemanticsLedger` 定义必填字段集（取值见 design 2.3.2 字段口径表），缺失任一字段抛 `SCHEMA_INVALID`。
  - 完成判定：`--selftest` 输出 8 条 `SCHEMA` 检查结果，每类"完整记录通过 + 缺 1 字段被拒"两种情形均被断言；断言计数 = 16；`RelatedFindingRecord` 的 `finding_id` 以 `RF-` 开头、`ownership ∈ {本项范围, 范围外}` 被强制校验。
  - 依赖：2.2。
  - 引用：spec 6.1…6.4；design 2.3.2、I-06。

---

## 3. `PERF-02/metrics-capture` 测量协议

> 冻结项：F-1（200ms 只读引用，不得作为可调参数）、F-4（数据规模不变）。
> 范围边界：本组产出**只作阈值口径证据**，不得用于证明 spec 4.1-2 的"写阻塞"（design D-01）。

- [x] **3.1 实现环境声明器（`default` / `clean` 两档 + 保留键回显）**
  - 动作：实现 `--env default`（剥离全部 `PYTHON*` 后声明）与 `--env clean`（额外记录 `retained_env_keys`），输出 `mode / os_name / os_release / python_version / python_utf8_env / python_io_encoding / python_path / retained_env_keys / concurrent_load / declared_at` 十项。
  - 完成判定：`--env default` 时输出中三个 `PYTHON*` 字段均为 `None`（若实测非空则退出码非 0 并报 `ENV_DECLARATION_INVALID`）；`--env clean` 时 `retained_env_keys` 非空且至少含 `PATH`、`SYSTEMROOT`、`TEMP`；`declared_at` 可被解析为精确到分钟的 ISO 时间；故意在当前 shell（`PYTHONIOENCODING='utf8'`）下不加参数跑一次，必须以 `ENV_DECLARATION_INVALID` 退出，不得静默标 `default`。
  - 依赖：2.3。
  - 引用：spec 5.2.1-6a、6.1-5、6.2-2；design I-06、D-02、D-13；N-2、F-5。

- [x] **3.2 实现同规模数据构造器（不 import 测试代码）**
  - 动作：按 `test_metrics_perf.py:78-97` 的参数独立构造 `full=1000` + `repro_failed=100` 的 Issue 与每 Run 12 事件，共 1100 Issue / 12000 事件；构造过程只调用 `backend/app/repo/memory.py` 的公开方法，**不 import `backend/tests/*`**。
  - 完成判定：`--selftest` 输出 `scale issue=1100 events=12000`；`grep -nE "^(from|import).*tests" scripts/perf_probe.py` 命中数为 0；构造后 `MemoryStore` 的事件计数断言 `== 12000` 通过；模块内无 `importlib` 动态加载 `tests` 包的分支（`grep -c "importlib"` = 0）。
  - 依赖：2.3。
  - 引用：spec 6.1-4；design 1.2.2、D-04；F-4。

- [x] **3.3 实现协议 A：抓取端到端 5 次采样 + 统计**
  - 动作：实现 `perf_probe capture --case PERF-02/metrics-capture --samples 5 --env default|clean --out .evidence/perf-repro`，逐样本写 `samples-*.jsonl`，汇总写 `measure-*.json`，含 `median_ms / max_ms / over_budget_count / threshold_ms=200 / measurement_scope（五项逐项标注）/ data_scale / evidence_level / fingerprint_sha256`。
  - 完成判定：`--samples 4` 必须以 `SAMPLE_COUNT_INSUFFICIENT` 退出且不产文件；`--samples 5` 成功时 jsonl 行数 = 5、`sample_index` 为 1…5 连续、`over_budget_count` 等于对 5 行按 `>200ms` 重算的结果（差值 0）、`median_ms` 等于对 5 个 `elapsed_ms` 取中位数的重算值（误差 ≤1e-6）；`measurement_scope` 五项（容器拷贝 / 字段脱敏 / 序列化 / 摘要计算 / 落盘写入）均有布尔标注，无空值。
  - 依赖：3.1、3.2。
  - 引用：spec 4.1-2、4.1-3、5.1.1-1a、6.1-2/3/6；design I-01、1.2.1、AC-P02、AC-P04；F-1、F-4。

- [x] **3.4 实现协议 W：写阻塞增量（基线段 vs 并发抓取段）**
  - 动作：实现 `perf_probe write-block --case PERF-02/metrics-capture --samples 5 --write-ops 200`，基线段串行 `append`/`add_run` 200 次取 `p50/p95/max`，干扰段在另一线程持续 `capture` 时重复同一写入序列，输出 `delta_p95_ms = interference_p95 - baseline_p95`；记录 `thread_model_note`（内存实现、CPython GIL、阻塞表现为调度延迟）与 `evidence_level=L3`。
  - 完成判定：输出 `baseline_p50_ms <= baseline_p95_ms <= baseline_max_ms` 且 `interference_*` 同样单调；两段写入次数均为 200 且写入序列 `event_id` 集合完全相同（差集为空）；`thread_model_note` 与 `evidence_level=L3` 非空且含"不得外推至 MySQL/持久化后端"字样；`measurement_scope` 明确标注不含落盘写入。
  - 依赖：3.2。
  - 引用：spec 4.1-2、5.1.1-1、6.1-2/3；design I-02、1.2.1、2.8（W 协议风险）、D-01。

- [x] **3.5 实现判定函数 `judge`（六行决策表 + 禁止人工覆盖）**
  - 动作：实现纯函数 `judge(record, ledger) -> DecisionClass`，按 design 2.1.3(3) 六行条件机械判定，返回 `阈值口径问题 | 性能缺陷 | 偶发抖动 | 证据不足 | 不合规 | 实现缺口`，并写 `decision_reason`；`ledger` 缺任一原文引用抛 `LEDGER_INCOMPLETE`。
  - 完成判定：`--selftest` 用 6 组合成 fixture 分别命中 6 种判定，6 条断言全部通过（构造数值须落在条件边界上：4/5 超门槛 + 规模单调→性能缺陷；1/5 超门槛且仅并发段→偶发抖动；语义不一致但 0/5 超门槛→阈值口径问题；样本 4→证据不足；变更集含 `skip`→不合规；超预算无标记→实现缺口）；判定优先级实测为"口径一致性 > 统计证据"（语义不一致 + 4/5 超门槛时，输出必须是阈值口径问题而非性能缺陷）。
  - 依赖：3.3、3.4。
  - 引用：spec 5.1.1-2a/b/c、5.1.3-1、5.1.1-5a；design I-07、2.1.3(2)(3)、D-03。

---

## 4. D1-1 逐层补验

> 冻结项：F-6（`git archive` 只读，不推送）、F-7（不提交）。
> 核心纪律：**L1→L4 严格串行，任一层不通过即停止**，未执行层登记 `EVIDENCE_GAP`，**绝不折叠为"通过"**（design D-07）。

- [x] **4.1 实现 L1 `clean-export`（`git archive` 导出到系统临时目录）**
  - 动作：实现 `d1_clean_install_check run --check D1-1 --layer clean-export --env default|clean`，用 `git archive` 把 HEAD 导出至系统临时目录（非工作区），记录 `command / exit_code / duration_seconds / coverage_layer / stopped_at_layer`。
  - 完成判定：成功时 `exit_code=0` 且导出文件的 Git 跟踪文件数等于 `git ls-files | wc -l`（差值 0）；临时目录路径位于系统 temp 而非仓库内（断言路径不以仓库根为前缀）；失败时写 `sub_reason=EXPORT_FAILED` 并保留 stderr 尾部 ≥ 500 字符，且 `stopped_at_layer=clean-export`。
  - 依赖：2.2。
  - 引用：spec 5.2.1-4a、5.2.1-5a、6.2-3/6；design 2.1.3(4)、I-03、D-07；F-6。

- [x] **4.2 实现 L2 `install`（临时 venv + `pip install -r backend/requirements.txt`）**
  - 动作：在 L1 导出目录内 `python -m venv .venv` 并安装依赖，记录 pip 退出码、末 20 行输出、已安装包清单；无网络/无缓存时按 design D-10 登记 `INSTALL_UNAVAILABLE` + `evidence_gap=true`。
  - 完成判定：成功时 `exit_code=0` 且包清单包含 `backend/requirements.txt` 的全部 7 个直接依赖（fastapi/uvicorn/pydantic/PyYAML/httpx/SQLAlchemy/PyMySQL）；不可用时记录含 `evidence_gap=true`、`stopped_at_layer=install`，且**该层结论字段取值为 `EVIDENCE_GAP` 而非 `通过`**（对记录做字符串断言：`"通过" not in conclusion`）。
  - 依赖：4.1（L1 必须先通过）。
  - 引用：spec 5.2.1-4a、5.2.1-5a、5.2.3-2；design D-10、2.1.3(4)。

- [x] **4.3 实现 L3 `config-load`（`default`/`clean` + `-X utf8=0`）**
  - 动作：在导出目录内以 `default` 与 `clean` 两档分别执行 `python -X utf8=0 -c "…load_config()…print('config ok')"`，记录退出码与 stdout/stderr。
  - 完成判定：`default` 与 `clean` 两档**各自** `exit_code=0` 且 stdout 含 `config ok`；两档记录均写明 `env_mode` 与 `retained_env_keys`（`clean` 档非空）；若任一档出现编码类异常，记录升级为 `环境可复现性缺陷` 并附完整 stderr（`Traceback` 或 `UnicodeDecodeError`/`UnicodeEncodeError` 字样必须原样保留）。
  - 依赖：4.2（或 L2 登记 `EVIDENCE_GAP` 时仍可对工作区外的导出目录做降级取证，但必须在记录中注明 `degraded_from=install-unavailable`）。
  - 引用：spec 5.2.1-2a/3a、5.2.1-5a、6.2-2/7；design 1.2.4、D-02、D-10。

- [ ] **4.4 实现 L4 `full-regression`（可选层，四类分列）**
  - 动作：同模式下执行全量回归（实际命令须完整记录，例如仓库根 `python -m unittest discover -s backend/tests -t backend -p "test_*.py"`，或 `backend/` 下 `python -m unittest discover -s tests -p "test_*.py"`），解析 `Ran N tests` / `errors=` / `failures=`，列出失败用例全名。
  - 完成判定：记录含 `ran / errors / failures` 三个整数与实际执行命令原文；`failures>0` 时 `failed_test_names` 列出全名且条数等于 `failures`；四类计数（`PERF-02/metrics-capture`、`PERF-02/eval-digest`、过期用例、功能性失败）之和 == `failures`；记录可被同一命令重跑复现同一 `Ran` 值（±0）。
  - 依赖：4.3。
  - 引用：spec 5.3.1-2a、5.3.1-3a、6.2-4/5；design 2.1.3(4)、AC-P11。

- [x] **4.5 落盘四条分层记录并标注覆盖层次与缺口**
  - 动作：将 L1–L4 逐层独立写为 `d1-1-<layer>-<ts>.json`，每条含 `check_id=D1-1`、`coverage_layer`、`evidence_gap`、`stopped_at_layer`、`env_mode`、`retained_env_keys`、`command`、`exit_code`、`duration_seconds`、`ran/errors/failures`、`failed_test_names`。
  - 完成判定：4 个文件均存在且 `json.load` 成功；`coverage_layer` 取值集合 ⊆ 四个枚举值；未执行的层 `evidence_gap=true`；**不得出现"仅 L3 通过即宣称 D1-1 全通过"**（对汇总条目做断言：若存在 `evidence_gap=true` 的层，则汇总结论字段必须为 `部分通过（分层登记）` 且含缺口层清单）。
  - 依赖：4.1…4.4。
  - 引用：spec 5.2.1-4a、6.2-6/7；design D-07、AC-P07。

---

## 5. 裁定与三方语义对照

> 冻结项：F-5（三方原文只引用不改写）、N-3（结论只按类别表述）。

- [ ] **5.1 采集三方语义原文（需求 / 设计 / 断言）并逐字引用**
  - 动作：采集 `metrics_recalc/spec.md` §4.1-2 原文、`metrics_recalc/design.md:465`、`:766`、`:1315`、`:1408` 原文、`backend/tests/test_metrics_perf.py:104`、`:111`、`:168` 断言原文，写入 `SemanticsLedger`（含文件路径、行号、逐字文本、`captured_at`）。
  - 完成判定：每条记录按"文件 + 行号"复读，字符串与记录完全相等（逐条 `==` 断言，不允许省略号截断）；断言原文必须体现 `assertLess(capture_elapsed, 0.2)` 与 `assertLessEqual(elapsed_ms, 500)` 两个不同门槛；`captured_at` 可解析；三方文件 `sha256` 与 §1.2 基线一致（证明只读）。
  - 依赖：1.2。
  - 引用：spec 5.1.1-4a、5.1.1-7、6.3-3；design 2.5.1 第 3 节、AC-P03；F-5。

- [x] **5.2 生成 `PERF-02/metrics-capture` 裁定记录（阈值口径问题）**
  - 动作：按 design 2.5.1 生成 `decision-perf02-metrics-capture-<ts>.json`，`decision_class=阈值口径问题`，附 `spec_refs`、`original_text_refs`、`evidence_paths`（指向 3.3 的 `samples/measure`）、`immutable_carriers`、`effective_date`。
  - 完成判定：`decision_class` 在四类枚举内且等于 `阈值口径问题`；`evidence_paths` 每个路径 `Path.exists()==True`；`immutable_carriers` 覆盖 §1.2 的 36 条；记录中同时出现"测量对象""测量范围""环境声明"三个字段且均非空（缺一即判无效，`SCHEMA_INVALID`）；结论句不含"性能缺陷""已优化""已修复"。
  - 依赖：3.3、3.5、5.1。
  - 引用：spec 5.1.1-1a、5.1.1-2c、5.1.1-3、6.3-1…6；design AC-P03、D-01、D-03；N-3。

- [ ] **5.3 生成 `D1-1` 裁定记录（文档口径问题，条件式）**
  - 动作：生成 `decision-d1-1-<ts>.json`，按条件分支填写：若 4.3 两档 `config-load` 均通过且 4.4 `errors=0` → `文档口径问题`；若出现编码类错误 → `环境可复现性缺陷` 并附 stderr。
  - 完成判定：`decision_class` 与 4.3/4.4 的实际记录字段一致（脚本断言：从 `d1-1-*.json` 读取 `exit_code`/`errors` 后重算，结果与 `decision_class` 匹配，不匹配即失败）；记录中**不出现**"依赖 `PYTHONUTF8`"作为当前结论（允许出现在"原表述引用"字段并标注 `outdated=true`）；附 `coverage_layer` 与 `evidence_gap` 清单。
  - 依赖：4.3、4.4、5.1。
  - 引用：spec 5.2.1-2、5.2.1-3a/b、5.2.3-1、6.3-2/4；design 2.5.3、AC-P08；N-3。

- [ ] **5.4 登记 `IF-01` 实现缺口（`capture_budget_ms` 无消费点）**
  - 动作：以实检索证明 `capture_budget_ms` 仅有定义与校验三处、无任何读取/比较点，登记为 `IF-01`，并注明"复算仍返回成功、告警不可观测"。
  - 完成判定：记录中给出 `grep -rn "capture_budget_ms" backend/` 的命中行号清单，且命中集合 == `{config.py:140, config.py:275, config.py:276}`（不允许超出）；同时给出 `grep -rn "CAPTURE_SLOW" backend/` 命中数 = 0 的实测输出；结论字段固定为 `实现缺口`，不得写 `性能缺陷`。
  - 依赖：5.2。
  - 引用：spec 5.1.1-5、5.1.1-5a、5.1.3-4；design 1.2.3、D-11、AC-P06；§0.2 IF-01。

---

## 6. 回归基线与四类失败分列

> 冻结项：F-1…F-4、F-6。基线必须与缺省环境一致，失败**禁止合并为单一数字**。

- [ ] **6.1 生成缺省环境全量回归基线快照**
  - 动作：在剥离全部 `PYTHON*` 的环境下执行一次全量回归（实际命令完整记录），登记 `command / exit_code / env_declaration / duration_seconds / ran / errors / failures`，写 `regression-baseline-<ts>.json`。
  - 完成判定：`ran>0` 且 `errors`/`failures` 为整数；命令可原样复制重跑（记录中命令含 `-s`/`-t` 与 `-p` 参数原文）；环境声明含三个 `PYTHON*` 状态且 `mode` 字段非空；耗时与用例数均落盘；文件可 `json.load`。
  - 依赖：4.5、5.2。
  - 引用：spec 5.3.1-3a、6.2-4；design AC-P11。

- [ ] **6.2 四类失败分列（含失败用例全名）**
  - 动作：把 `failures` 拆为 `PERF-02/metrics-capture` / `PERF-02/eval-digest` / 过期用例 / 功能性失败 四类，每类给计数与全名清单。
  - 完成判定：四类计数之和 == 6.1 的 `failures`（差值 0）；每类均存在字段（空类写 `0` 并注明"本次无"）；未限定词 `PERF-02` 在该表中出现次数为 0（`grep -cE "^\\| *PERF-02 *\\|" = 0`）；`test_check_devlog` 相关失败归入"过期用例"类并标注 `RF-01`。
  - 依赖：6.1。
  - 引用：spec 4.2-3、5.3.1-2a、5.3.2-1a；design AC-P11；N-1。

- [ ] **6.3 复核 `check_devlog` 阻塞保持 7 条（不因新增载体而变化）**
  - 动作：执行 `python scripts/check_devlog.py --json`，记录 `blocking_total` 与 `git_commits` 五前缀计数，并说明新增 `docs/devlog/perf-repro-closeout.md` 不在 `STEPS` 解析范围。
  - 完成判定：`blocking_total == 7`；`git_commits` 五个前缀计数均为 `0`（与本次执行前同值）；`scripts/check_devlog.py` 的 `sha256` 与 §1.2 基线一致；记录中给出 `STEPS` 只含 `01-`…`05-` 五个文件名的实读证据。
  - 依赖：6.1。
  - 引用：spec 1.4-6、5.3.1-5；design 1.2.8、2.6-2；F-5。

- [ ] **6.4 `RF-03` 污染核对并还原为 HEAD**
  - 动作：回归执行后检查 `git status --short -- .evidence/self_run_samples.jsonl`，若出现变更则 `git checkout -- .evidence/self_run_samples.jsonl` 还原，并记录还原前后行数与 `sha256`。
  - 完成判定：还原后 `git status --short -- .evidence/self_run_samples.jsonl` 输出为空；`sha256` 等于 §1.2 基线值；记录含"该写入属产品路径、修复需另立项（`RF-03`）"的登记句，且**未修改** `backend/app/main.py`（`git diff --stat -- backend/app/main.py` 为空）。
  - 依赖：6.1。
  - 引用：spec 4.5-1、5.3.3-2；design 1.2.7、2.6-5、D-12；§0.2 RF-03。

---

## 7. 关联发现登记（**只登记不修复**）

> 铁律：本组**不产生任何修复型编码任务**。允许的唯一代码形态是与登记无关的只读复现命令。违反即判越界（spec 5.3.3-2）。

- [ ] **7.1 登记 `RF-01`（`check_devlog` 过期用例，范围外稳定复现）**
  - 动作：在 `backend/` 下执行 `python -m unittest tests.test_check_devlog.CheckDevlogTest.test_real_repository_reports_blocking_not_pass`，登记七字段。
  - 完成判定：七字段齐备（编号/标题/复现命令/稳定性/归属/阻断关系/处理建议）；`stability=稳定复现`；`ownership=范围外`；`blocking_relation` 写明"阻断全量回归 `failures` 清零，不阻断本项口径裁定与验收"；复现命令的实测输出含 `AssertionError` 与 `'非 Git 仓库' not found`；建议字段含"另立项（需维护者决策），本项不做"。
  - 依赖：6.2（需先有分类结果作为依据）。
  - 引用：spec 5.3.1-4a、6.4-1…7；design 1.2.5、2.5.2、AC-P09；§0.2 RF-01。

- [ ] **7.2 登记 `RF-02`（同名歧义，仅消歧要求 + 位置索引）**
  - 动作：以 `grep -rn "PERF-02" --include=*.md` 的实测命中为索引全集，逐条登记"文件 + 行号 + 原文片段 + 指代（metrics-capture / eval-digest / 未限定）"，至少覆盖 `README.md:170`、`README.md:192`、`docs/devlog/metrics-report.md:41`、`metrics_recalc/design.md:1408`。
  - 完成判定：索引条目数等于 grep 实测命中行数（差值 0）；每条含指代判定；`design` 列出的 4 处均在索引内；同页登记"新载体强制限定词"规则（`PERF-02/metrics-capture` 门槛 200ms、`PERF-02/eval-digest` 门槛 500ms）；**未修改**上述任一 md 文件（`git diff --stat` 对它们为空）。
  - 依赖：5.1。
  - 引用：spec 5.1.1-7a、4.5-1、6.4；design 2.5.2、D-08；§0.2 RF-02；N-1。

- [ ] **7.3 登记 `RF-03`（回归写被跟踪证据文件，范围外）**
  - 动作：执行 `python -m unittest tests.test_api_m4.ApiM4Test.test_heartbeat_and_dashboard`（`backend/` 下），观察 `.evidence/self_run_samples.jsonl` 行数变化，登记七字段并附"HEAD 72 行 / 最近写入 `2026-11-18T09:53:04Z`"的基线事实（行数以实测为准，须与实际 `git show HEAD:.evidence/self_run_samples.jsonl | wc -l` 一致）。
  - 完成判定：七字段齐备；`stability=稳定追加`；`ownership=范围外`；记录含"写入属产品路径（`main.py:583-585`），修复需另立项"；执行后已按 6.4 还原（`git status` 该文件为空）；`backend/app/main.py` 与 `backend/tests/test_api_m4.py` 的 `git diff` 为空。
  - 依赖：6.4。
  - 引用：spec 6.4、5.3.3-2、4.5-1；design 1.2.7、D-12；§0.2 RF-03。

- [ ] **7.4 越界自检（证明本组未产生修复行为）**
  - 动作：对 §0.2 四项逐一列出"本项实际改动 = 无"的核对命令与输出。
  - 完成判定：四条命令输出全部为空或命中数 0：`git diff --stat -- backend/tests/test_check_devlog.py scripts/check_devlog.py`、`git diff --stat -- backend/app/main.py backend/tests/test_api_m4.py`、`git diff --stat -- README.md docs/devlog/metrics-report.md`、`grep -rn "CAPTURE_SLOW" backend/`；登记表中四项均标注"只登记不修复"。
  - 依赖：7.1、7.2、7.3。
  - 引用：spec 1.4-1、1.4-6、5.1.1-6a、5.3.3-2；design 2.8。

---

## 8. 登记载体成文（`docs/devlog/perf-repro-closeout.md`）

> 冻结项：F-5（新文件、追加式；不得回改任何既有文档正文）、N-3、N-4。
> 写入纪律：本文件为**新建**；后续更新只允许追加节，写入前后取 sha256，差异仅允许"长度增加"。

- [ ] **8.1 建立 8 节骨架**
  - 动作：新建 `docs/devlog/perf-repro-closeout.md`，按 design 2.5.1 建 8 个二级标题：摘要 / 口径单一来源表 / 三方语义对照 / 测量协议 / 证据登记表 / 关联发现 / 口径更正登记 / 不可变载体清单。
  - 完成判定：8 个二级标题按序存在（`grep -n "^## "` 输出 8 行且顺序一致）；每节首行标注对应 spec 条款号；文件内无 `PERF-02` 裸写（`grep -oE "PERF-02(?![/a-z])"` 命中数 0，须配合 `grep -n "PERF-02[^/]"` 人工复核为 0）。
  - 依赖：2.1。
  - 引用：spec 5.3.1-1a；design 2.5.1、D-06；N-1。

- [ ] **8.2 填第 2 节：口径单一来源表（4 条口径）**
  - 动作：登记 `PERF-02/metrics-capture`、`PERF-02/eval-digest`、`D1-1`、`D1-2` 四条口径的"测量对象 / 门槛 / 判定规则 / 唯一来源行号"。
  - 完成判定：4 行齐全；每行"测量对象"与"门槛"均非空（`D1-1`/`D1-2` 填"无门槛，判定为退出码+计数"）；门槛值与 §1.3 完全一致（逐值断言，不得出现 201ms/60000ms 之类改写）；表头含"本节为唯一来源，其他文档只能引用"。
  - 依赖：8.1、1.3。
  - 引用：spec 4.4-1、5.1.1-7；design 2.5.1 第 2 节。

- [ ] **8.3 填第 3 节：三方语义对照 + 修订前后差异**
  - 动作：把 5.1 的 `SemanticsLedger` 渲染为三列表（需求 / 设计 / 用例断言），逐条附行号，并给出"修订前后差异"说明（只描述应有差异，**不实施修改**）。
  - 完成判定：三列均非空；引用的 `metrics_recalc/design.md:465`、`:766`、`:1315`、`:1408` 与 `test_metrics_perf.py:104`、`:111`、`:168` 全部出现；"修订前后差异"段落明确写"只给出修订要求，本轮不修改任何原文"；无任何 md/py 文件被改动（`git diff --stat -- metrics_recalc_docs 相关路径` 为空）。
  - 依赖：5.1、5.2。
  - 引用：spec 5.1.1-4a；design AC-P03、D-06。

- [ ] **8.4 填第 4 节：测量协议七要素**
  - 动作：把协议 A、协议 W、D1-1 三层协议的"测量对象 / 测量范围 / 数据规模 / 环境声明 / 采样次数 / 统计取值 / 判定规则"逐项列齐。
  - 完成判定：三条协议 × 七要素 = 21 个单元格全部非空；协议 A 注明"仅作口径证据"、协议 W 注明 `evidence_level=L3` 与 GIL 局限、D1-1 注明四层与 `EVIDENCE_GAP` 规则；采样次数均为 `5`（D1-1 各层为 1 次）；与 3.1–3.5、4.1–4.5 的实现参数一致（逐项比对，差异 0）。
  - 依赖：3.5、4.5。
  - 引用：spec 1.3-2、4.1-2、5.2.1-4；design AC-P01。

- [ ] **8.5 填第 5 节：证据登记表（命令/退出码/样本/分布/环境/路径/指纹）**
  - 动作：每条证据一行，含 `command`、`exit_code`、`samples 或 ran`、`median/max 或 failures`、`env_declaration`、`evidence_path`、`fingerprint_sha256`。
  - 完成判定：行数等于实际落盘的证据文件数（采集 A/W + D1-1 四层 + 回归基线 + 冻结/不可变基线）；每行 `evidence_path` 均 `exists()`；每行 `fingerprint_sha256` 与文件实算 `sha256` 一致（逐行断言，差异 0）；环境列均含 `default` 或 `clean` 且附三个 `PYTHON*` 状态。
  - 依赖：8.4、6.2。
  - 引用：spec 1.3-4、4.4-2、6.1-8、6.2-4；design AC-P04、AC-P11。

- [ ] **8.6 填第 6 节：关联发现（`RF-01`…`RF-03` + `IF-01`）**
  - 动作：把 7.1–7.3 与 5.4 的登记渲染为表，七字段完整。
  - 完成判定：4 行齐全；`RF-01`/`RF-03` 的 `ownership=范围外`、`RF-02` 标注"本项仅登记与消歧要求"、`IF-01` 标注"实现缺口，不记性能缺陷"；每行"处理建议"均含"本项不做/另立项"语义；阻断关系列非空。
  - 依赖：7.4、5.4。
  - 引用：spec 6.4-1…7、5.3.1-4a；design AC-P06、AC-P09。

- [ ] **8.7 填第 7 节：口径更正登记（追加式，带日期）**
  - 动作：按 design 2.5.3 三条模板登记更正条目（`PERF-02` 抖动的原表述 → 阈值口径问题；D1-1 "依赖 `PYTHONUTF8=1`" → 过期观测；D1-2 "8 error + 1 failure" → 计划值假设），每条含"更正日期 / 原表述位置 / 机器证据 / 新结论"。
  - 完成判定：3 条齐全，每条"原表述位置"给出文件 + 行号（`README.md:170`、`README.md:192`、`docs/devlog/03-build.md:51`、`docs/devlog/m12-closure-and-blockers.md:11`、`docs/devlog/m13-analysis-plan.md:46`、`:47`）；**仅写在本文件**，目标原文件的 `sha256` 与 §1.2 基线一致（逐项断言，差异 0）；每条含日期 `2026-11-19` 字样。
  - 依赖：5.2、5.3。
  - 引用：spec 1.3-6、4.4-3、5.2.1-7a；design 2.5.3、D-06；F-5。

- [ ] **8.8 填第 8 节：不可变载体清单 + 写入前后 sha256 对账**
  - 动作：列出 §1.2 的 36 条清单，并在结项时逐条复算 `sha256`，与基线逐项比对，输出"一致条数 / 不一致条数"。
  - 完成判定：`一致条数 == 36`、`不一致条数 == 0`；表内每条含"路径 / 基线 sha256 / 结项 sha256 / 结果"；同时列出本轮新增的 4 个路径族并标注"新增（不在不可变清单内）"；对账脚本的输出原文（含时间戳）附在节末。
  - 依赖：8.1…8.7、§1.2。
  - 引用：spec 4.5-1、6.3-6；design AC-P10、2.5.1 第 8 节；F-5。

---

## 9. 验收映射与冻结自检

> 冻结项：全量生效。本组是结项前的最后门禁，**任何 `fail` 都不得写成"可接受"**。

- [ ] **9.1 `AC-P01`…`AC-P12` 逐项映射与判定**
  - 动作：按 design 2.7 建 12 行表，逐项填 `pass/fail` + 证据路径 + spec 条款。
  - 完成判定：12 行齐全；每行 `pass` 必须给出可点开存在的证据路径与行号（`evidence_path.exists()` 为真）；`fail` 行须写明缺失项与后续动作；不允许出现"部分通过"以外的模糊表述充当 pass。
  - 依赖：8.8。
  - 引用：design 2.7、AC-P01…AC-P12。

- [ ] **9.2 冻结项 F-1…F-7 终检**
  - 动作：重跑 §1.1 的 7 条检测命令，逐条记录结果。
  - 完成判定：7 条全部满足冻结条件（`git diff` 空、`sleep` 命中 0、`VERIFIX_SKIP_PERF` 行号不变、`issue=1100/events=12000`、36 条 sha256 一致、无 `push`/`fetch`、`rev-list --count HEAD == 4` 且 4 个哈希不变）；任一不满足则该行标 `fail` 并在结论写"本轮不通过"。
  - 依赖：9.1。
  - 引用：spec 1.4、4.1-1、4.5-1；F-1…F-7。

- [ ] **9.3 表述纪律与编号消歧自检**
  - 动作：对全部新增载体（`docs/devlog/perf-repro-closeout.md`、`.evidence/perf-repro/*.md|json`）做绝对化表述与裸编号扫描。
  - 完成判定：`grep -nE "性能已优化|全部用例通过|可复现性已修复|已修复"` 在新增载体中命中数 0（若命中仅出现在"禁止写法"示例行，须逐条列出并标注上下文）；`PERF-02` 未带限定词的出现次数 0（排除"禁止裸写"示例行，同样逐条标注）；两处列举均写入结项记录。
  - 依赖：9.1。
  - 引用：spec 5.3.1-6a、4.5-2；design D-14、AC-P12；N-1、N-3。

- [ ] **9.4 提交边界与未跟踪清单声明**
  - 动作：记录 `git status --short` 全量与 `git rev-list --count HEAD`，说明"本轮默认零提交（C-0），新增文件均为工作区未跟踪/未暂存改动"。
  - 完成判定：`rev-list --count HEAD == 4`；`git status --short` 输出中新增项逐条列出并归类（脚本 / 登记文档 / 证据文件）；输出中**不含** `.evidence/self_run_samples.jsonl`；记录含"未执行 `git add`/`git commit`/`git push`"的明确声明；若维护者已授权 C-1，则须另附"授权记录 + 提交哈希 + 提交标题不含五步前缀"三项证据。
  - 依赖：9.2。
  - 引用：spec 1.4-5、design 2.6-5、§0.4；F-6、F-7。

---

## 10. 交接与后续决策（不实施）

- [ ] **10.1 输出四项产出索引（结项依据）**
  - 动作：把"归属裁定 / 测量协议 / 验收标准 / 证据登记"四项与对应路径列成一张表。
  - 完成判定：4 行齐全，每行路径存在且可打开；缺失任一项则结论写"本轮不通过（缺第 N 项）"。
  - 依赖：9.4。
  - 引用：spec 1.3-1…4、5.3.1-1a；design AC-P01…AC-P12。

- [ ] **10.2 登记待维护者决策的后续事项**
  - 动作：列出 `RF-01`（用例断言更新）、`RF-03`（样本路径隔离/门控）、`IF-01`（`CAPTURE_SLOW` 告警）、`AC` 中 `fail` 项、以及"是否授权 C-1 提交"。
  - 完成判定：每项含"现象 / 依据路径 / 建议方案 / 决策人 / 状态=待决策"；每项均标注"本项不实施"；不存在把上述任一项写成已完成的内容。
  - 依赖：10.1。
  - 引用：spec 5.3.1-4a、5.3.3-2；design 2.8"明确不做"。

- [ ] **10.3 输出本轮边界声明**
  - 动作：写明"本轮只做裁定与证据登记：无产品代码修复、无断言/阈值/sleep/skip/数据量调整、无历史载体改动、无远端接入、无五步提交补建"。
  - 完成判定：声明 6 条齐全且逐条可被 9.2/9.3/9.4 的证据复核；结论句为"分类结论"，不含"通过验收 = 缺陷已修复"的等价表述。
  - 依赖：10.2。
  - 引用：spec 1.4-1…7、5.3.1-6a；design 2.8。

---

## 覆盖对照（需求 → 任务）

| spec / design 条目 | 覆盖任务 |
|---|---|
| spec 1.3-1…6（核心输出） | 5.2、5.3、8.1–8.8、10.1 |
| spec 1.4-1…7（职责边界） | 1.1、7.4、9.2、10.3 |
| spec 4.1-1/2/3（性能约束） | 1.3、3.3、3.4、9.2 |
| spec 4.2-1/2/3（可靠性） | 3.1、4.5、6.1、6.2 |
| spec 4.3-1/2/3（安全只读不出网） | 2.2、3.4、4.1、9.2 |
| spec 4.4-1/2/3（口径单一来源/可检索/追加更正） | 2.1、8.2、8.5、8.7 |
| spec 4.5-1/2/3（历史不可变/编号消歧/持续可用） | 1.2、7.2、8.8、9.3 |
| spec 5.1.1-1…8（PERF-02 裁定） | 3.3、3.4、3.5、5.1、5.2、5.4 |
| spec 5.1.3-1…5（异常场景） | 3.5、5.2、7.2 |
| spec 5.2.1-1…8（D1-1 裁定） | 3.1、4.1–4.5、5.3 |
| spec 5.2.3-1…4（异常场景） | 3.1、4.2、4.3、5.3、8.7 |
| spec 5.3.1-1…6（收尾验收） | 6.1、6.2、8.8、9.1、9.3、10.1 |
| spec 6.1-1…8（性能样本） | 2.1、2.3、3.3、8.5 |
| spec 6.2-1…7（可复现记录） | 4.1–4.5、8.5 |
| spec 6.3-1…6（裁定记录） | 5.2、5.3、8.2 |
| spec 6.4-1…7（关联发现） | 7.1、7.2、7.3、8.6 |
| design D-01…D-14 | 3.4、3.5、3.1、3.2、2.1、8.7、4.5、7.2、5.2（`--selftest` 不进 discover）、4.2、5.4、6.4、3.1、9.3 |
| design I-01…I-07 | 3.3、3.4、4.1、2.2、8.2、3.1、3.5 |
| design AC-P01…AC-P12 | 9.1（逐项映射） |
| design §0.2（RF-01/02/03 + IF-01 只登记） | 7.1–7.4、5.4、8.6 |

---

## 勾选规则

- 仅当"完成判定"已被**实测证据**满足时才可勾选；未满足者保持 `- [ ]` 并在 10.2 登记原因。
- 不存在"先勾选后补证据"；不得以"已按设计实现"代替实测输出。
- 不得代填 `AC-Pxx` 结果；`fail` 即 `fail`，不得降级表述为"可接受"。
- 任一冻结项（F-1…F-7）被突破，本轮结论固定为"不通过"，不得以其他条目通过为由放行。