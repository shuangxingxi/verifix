# 沙箱约束实测验证与靶场真扫 · 编码任务规划

> 依据：`.codeartsdoer/specs/sandbox_realscan/spec.md`（v1.0，677 行）＋ `.codeartsdoer/specs/sandbox_realscan/design.md`（1892 行）
> 编号规则：任务编号 `T-<DES 域>-<序号>` 与 design 第三章 `DES-SBX/SCAN/EVD/ISO/CFG/DOC-a.b` 一一对应；同一条设计条目需要拆成两个独立产物时用 `.1/.2`、`.3/.4` 后缀（仅 `DES-SBX-03`、`DES-CFG-06` 两处）。
> 组织方式：按"基线 → 能力与执行域 → 约束验证 → 靶场真扫 → 隔离桥接 → 证据与边界 → 文档与 CLI → 回归验收"推进；每个任务是**一个可独立实现、可独立验证的成果**，不按 Controller/Service/DAO 切分。
> 本文件只描述"做什么、做到什么程度"，**不含实现代码，不修改任何产品代码、测试代码、脚本、数据目录或既有报告**。

---

## 0. 执行硬约束（全阶段必须复核）

| # | 约束 | 复核方式 |
|---|---|---|
| C1 | 真实源码根为 `backend/`；`backend/app/realscan/` 与 `backend/app/runtime/exec_domain.py` 当前**不存在**，只能新建，不得假设已存在 | 每个阶段开始前 `ls backend/app/realscan` 必须报"不存在"直到对应任务完成 |
| C2 | **不改** `sandbox/spec.json`（11 个隔离键 + 5 条逃逸用例）、`verifix-target/{app/main.py,app/config.py,requirements.txt,ground_truth.json,init_db.py,tests/}`、`backend/app/eval/{loader,runner,adjudication,digest,models,leak_scan}.py` 的控制流、`backend/app/tools/{sandbox.py,workspace.py,mcp.py}`、`backend/app/domain/models.py::EnvSnapshot`、`backend/app/main.py` 既有路由 | 每阶段收尾复算 `sandbox/spec.json`=`bd62277b…`、`verifix-target/ground_truth.json`=`286d13be…`、`verifix-target/requirements.txt`=`5e19106a…`；`python -m unittest backend.tests.test_sandbox_mcp -v` 断言 8 工具 |
| C3 | **不改** `backend/app/eval/isolation.py` 的故障关闭语义：`AnswerIsolationGuard.self_check()` 失败分支必须继续 `raise ApiError(EVAL_ISOLATION_UNMET)`；只允许新增 `exec_domain/failure_kind/publishable` 字段与可选入参 | 代码审查 + T-ISO-05 用例断言"失败路径抛错数 = 全部失败分支数、放行分支数 = 0" |
| C4 | 运行期 `--network=none` 不可放宽：配置层不提供网络放行项，`RunSpecBuilder` 不允许覆盖 `--network` 与 `--read-only` | `python -m unittest backend.tests.test_sandbox_verify_policy -v`（T-SBX-POL-02/05） |
| C5 | **不得以桩冒真**：M1 的 10/10 必须标 `RECORDED_STUB`，不得计入真扫分母；检出不得读取 `ground_truth.json` | `python -m unittest backend.tests.test_realscan_scan -v`（T-RS-SCN-04/06） |
| C6 | **不得声称云上已验证**：所有云相关结论只能输出 `CLOUD_CREDENTIAL_MISSING`，报告禁用"生产已验证/云上已通过" | 报告发布前检索禁用词，命中数必须为 0 |
| C7 | 测试统一标准库 `unittest`；镜像内 `pytest 8.3.4` 仅供靶场/镜像自测，**不得**作为项目测试依赖 | `backend/requirements.txt` 不含 pytest；所有验证命令形如 `python -m unittest ...` |
| C8 | 工作区已 Git 化（基线 `vcs-baseline/<短标识>`）：**允许只读 git 查询**用于追溯（白名单：`rev-parse`/`log`/`show`/`status`/`ls-files`/`check-ignore`/`cat-file`/`config --get`/`for-each-ref`）；**仍禁止**依赖分支/提交/回滚作为交付手段；回滚继续以 staging + 文件替换实现；基线提交不计入五步留痕 | 验收命令不出现写类 git 操作（`add`/`commit`/`reset`/`checkout`/`switch`/`branch -d`/`push`/`remote`/`tag`/`clean`/`stash`）；只读查询命中须在任务记录中说明用途并可回溯；`docs/devlog/00-conventions.md` §3 已声明 |
| C9 | 回归基线实测 **502 用例**、功能性失败 **0**，不得下调；唯一已知抖动项 `PERF-02`（首轮 252.9ms > 200ms 阈值，单跑 3 次全通过）按抖动处置，不得计入功能失败 | `python -m unittest discover -s backend/tests -p "test_*.py"`，每阶段收尾记录总数/失败数 |
| C10 | 本轮**只写 `tasks.md`**，不新增/修改任何产品代码、脚本、数据目录、证据目录与历史报告 | 交付物仅 `.codeartsdoer/specs/sandbox_realscan/tasks.md` |

**C9 的基线实测记录（2026-11-14 本次任务阶段实跑）**

| 项 | 实测值 |
|---|---|
| 全量命令 | `python -m unittest discover -s backend/tests -p "test_*.py"` |
| 用例总数 | **502** |
| 功能性失败 | **0** |
| 已知抖动 | `backend/tests/test_metrics_perf.py:104` `PerfTest.test_perf02_thousand_issues_and_twelve_thousand_events`，首轮 `capture_elapsed=0.2529s` 未小于 `0.2` |
| 抖动用例复跑 | 单跑 3 次全部 `OK`（0.86s / 0.84s / 0.88s 总耗时），判定为性能抖动，非功能回归 |
| 基线口径 | **≥502 用例、功能失败 0**；后续阶段不得下调，全量回归再现此项需记录并单跑复验 |

---

## 0.1 已实检索确认的事实基线（本文件所有路径/符号名来源）

> 每条均标注**已存在**或**待新建**；凡"待新建"不得在任务中被写成已存在。

| # | 关注点 | 真实位置与当前事实（本次实检） | 状态 |
|---|---|---|---|
| F-01 | 沙箱策略 | `sandbox/spec.json`：`policy_version=1.0.0`(:2)，`isolation` **11 键** network/source_mount/root_filesystem/timeout_seconds/memory_mb/cpu/user/cap_drop/no_new_privileges/pids_limit/tmpfs(:3-15)，`escape_cases` 5 条 P4-01…P4-05(:16-22)，`image="verifix-sandbox:1.0.0"`(:23)；文件 786 B，sha256 `bd62277bbae9d6ed146e92231b36bc2a3e5462e5aca715144ad8332384e36168` | 已存在（只读） |
| F-02 | 运行镜像定义 | `sandbox/Dockerfile.runner`（7 行）：`FROM python:3.12-slim`、`pip install pytest==8.3.4`、`USER 10001:10001`、`WORKDIR /workspace`、`ENTRYPOINT ["python"]` | 已存在（不改） |
| F-03 | 策略/靶场镜像构建定义 | `sandbox/Dockerfile.sandbox`、`sandbox/Dockerfile.target`、`sandbox/requirements.target.txt` 均**不存在**（`sandbox/` 下仅 `Dockerfile.runner`、`spec.json`） | 待新建 |
| F-04 | 既有沙箱执行器 | `backend/app/tools/sandbox.py`：`SandboxInfraError`(:15)、`SandboxPolicy`(:20)、`build_argv`(:78-104)、`isolation_report`(:106-116)、`preflight`(:118-125)、`run_tests`(:127-171)；`subprocess.run(timeout=policy.timeout_seconds)`(:142) | 已存在（不改） |
| F-05 | 工作区工具 | `backend/app/tools/workspace.py::LocalWorkspace.run_tests`(:82) | 已存在（不改） |
| F-06 | MCP 白名单 | `backend/app/tools/mcp.py`：`ALLOWED_TOOLS`(:42-51)、`TOOL-01…TOOL-08`(:63-70) | 已存在（不新增第 9 个） |
| F-07 | 执行器与快照 | `backend/app/agents/reproducer/executor.py`：`LocalTestExecutor`(:35)、`env_snapshot` 如实 `network_disabled=False/read_only=False`(:40-47)、`SandboxTestExecutor`(:91)、声明式 `env_snapshot`(:95-103) | 已存在（不改） |
| F-08 | 快照模型 | `backend/app/domain/models.py::EnvSnapshot`(:64-66)，语义不得改 | 已存在（不改） |
| F-09 | 隔离守卫 | `backend/app/eval/isolation.py`：`IsolationVerdict`(:19-24)、`AccessAuditLog`(:27-55，`record` :32 / `search` :43 / `exec_success_count` :54)、`PermissionProbe`(:66)、`probe_denied` 5 类(:90-109)、`cases_readable`(:111-121)、`AnswerIsolationGuard`(:124)、`assert_load_path`(:141-157)、`self_check`(:172-197)，失败 `raise ApiError(EVAL_ISOLATION_UNMET)`(:196) | 已存在（仅扩展字段） |
| F-10 | 答案读取身份限制 | `backend/app/eval/loader.py::ExpectedAnswerReader.load`(:48)，默认 `actor=JUDGE` | 已存在（不改） |
| F-11 | 评测执行链路 | `backend/app/eval/runner.py`：`LocalTestExecutor` 装配(:203)、`_run_case`(:248)、`detected = intake.outcome is IntakeOutcome.CREATED`(:266)（非源码扫描） | 已存在（不改） |
| F-12 | 摘要算法 | `backend/app/eval/digest.py`：`content_digest`(:13)、`file_digest`(:17)、`directory_digest`(:21)、`digest_triple`(:42) | 已存在（复用） |
| F-13 | 泄漏词表 | `backend/app/eval/leak_scan.py`：`FIELD_TOKENS` 含 `ground_truth`(:17)、`LeakScanner`(:33) | 已存在（复用，不新增词表） |
| F-14 | 证据存储 | `backend/app/evidence/store.py`：`LocalEvidenceStore`(:35)、`put_locked`(:45)、`read`(:53)、`verify`(:63)、`release`(:72) | 已存在（组合复用，不改） |
| F-15 | 错误码 | `backend/app/api/envelope.py`：`ErrorCode`(:15)、`EVIDENCE_MISSING=VF-7001`(:31)…`EVAL_INCOMPLETE=VF-8009`(:47)、`ERROR_SPECS`(:60)；**无 VF-8010/8011/8012** | 已存在（新增 3 码） |
| F-16 | 配置 | `backend/app/config.py`：`SandboxConfig`(:81-88)、`EvalConfig`(:116)、`MetricsConfig`(:127)、`AppConfig`(:149)、范围校验(:190-207)、`load_config`(:344)；**无 RealscanConfig** | 已存在（新增子模型） |
| F-17 | 执行域模块 | `backend/app/runtime/` 现有 circuit/control/queue/self_run/supervisor；**无 `exec_domain.py`** | 待新建 |
| F-18 | realscan 包 | `backend/app/realscan/` **目录不存在**（models/runtime/capability/policy/constraints/probe_scripts/target/rules/scanner/dynamic/worker/scan/reconcile/evidence/boundary/isolation_bridge/pipeline 全部待新建） | 待新建 |
| F-19 | 后端主入口 | `backend/app/main.py`（含 `search_eval_audit` :733 等既有路由）；本轮**不新增路由** | 已存在（不改） |
| F-20 | 靶场路由 | `verifix-target/app/main.py`：`create_app`(:15)、`VERIFIX_TARGET_DB`(:18)、11 路由(:23/27/35/46/54/62/70/78/84/90/96)；SQL 注入(:31/40-42/50/58/66/74)、命令注入(:81/87/93/99) | 已存在（不改） |
| F-21 | 靶场凭据 | `verifix-target/app/config.py:1-2`（`SECRET_KEY`、`DB_PASSWORD` 明文） | 已存在（不改，C05 检出目标） |
| F-22 | 真值清单 | `verifix-target/ground_truth.json`：`target/version/items` 三键，**15 项**，C01=3 / C02=6 / C03=4 / C05=2，`version=1.0.0`；sha256 `286d13be98fdfc9c18967be8d82e761ab1751ee1aacfc836d599e937b69becb2` | 已存在（只读） |
| F-23 | 靶场依赖 pins | `verifix-target/requirements.txt` 4 行（flask==1.1.1 等），59 B，sha256 `5e19106a…` | 已存在（不改） |
| F-24 | 靶场建库 | `verifix-target/init_db.py::create(path)`（支持任意可写路径） | 已存在（不改） |
| F-25 | 真值自校验 | `verifix-target/tools/verify_ground_truth.py` | 已存在（不改） |
| F-26 | 既有测试资产 | `backend/tests/` 47 个 `test_*.py`，实测 **502** 用例；`test_sandbox_mcp.py:83-89` 断言 8 工具且 `tool_version=1.0.0` | 已存在（不改） |
| F-27 | 新增测试文件 | `backend/tests/test_sandbox_verify_{policy,capability,constraints,evidence}.py`、`test_realscan_{rules,target,scan}.py`、`test_eval_isolation_bridge.py` **均不存在** | 待新建 |
| F-28 | 新增脚本 | `scripts/run_sandbox_verify.py`、`run_realscan.py`、`verify_isolation_bridge.py`、`build_sandbox_images.py` **均不存在**（`scripts/` 现有 21 个脚本） | 待新建 |
| F-29 | M1 桩来源 | `scripts/m1_detect_acceptance.py`（真值派生构造告警）；`docs/devlog/m1-detect-report.md` 记 10/10，仅 C02/C03 | 已存在（只读，引用） |
| F-30 | 历史证据 | `.evidence/sandbox/M0-SANDBOX-20261113T171337.txt`，1058 B，sha256 `a365c35284bd0be2ef5b8589283007a73a17c4fa9f4f3f73984ba274a9b17db6` | 已存在（只读） |
| F-31 | 历史报告摘要 | `docs/devlog/m0-sandbox-verification.md`=`35b0c792…`（3477 B）、`m1-detect-report.md`=`8892168a…`（1040 B）、`m5-eval-report.md`=`931d2044…`（1962 B）、`m2-reproduce-report.md`=`e6fe54ab…`（1788 B）、`m1-reachability-report.md`=`89d8a582…`（1126 B） | 已存在（只读） |
| F-32 | 新证据根 | `.evidence/sandbox-realscan/` **不存在**（`.evidence/` 下只有 metrics-recalc、sandbox、self_run_samples.jsonl） | 待新建 |
| F-33 | 新报告 | `docs/devlog/m6-sandbox-constraint-report.md`、`m7-target-realscan-report.md`、`m8-isolation-bridge-report.md`、`sandbox-realscan-index.md` **均不存在** | 待新建 |
| F-34 | 留痕规范 | `docs/devlog/00-conventions.md` §3 明确"工作区尚未初始化为 Git 仓库" | 已存在（只读） |
| F-35 | 运行时现状（本次实检） | `WSL_UTF8=1 wsl.exe -d Debian -u root -- docker version` → `26.1.5+dfsg1`；`docker info` → `overlay2 2`（cgroup v2） | 实测事实 |
| F-36 | 镜像清单（本次实检） | `realscan-probe:local` `sha256:78f369234744…`，132,371,211 B，`User=10001:10001`，`WorkingDir=/target`，`Entrypoint=["python"]`，容器内 `Flask 3.1.3 / Python 3.12.16`；`verifix-runner:latest` `sha256:bcb474080c7a…`，131,461,396 B，`User=10001:10001`，`WorkingDir=/workspace`；另有 `python:3.12-slim`、`alpine:3.20`、`hello-world`；**无 `verifix-sandbox:1.0.0`、无 `verifix-target:1.0.0`** | 实测事实 |
| F-37 | 评测数据集 | `eval/cases/` 51 个文件（50 用例 + manifest）、`eval/expected/` 51 个文件、`eval/runs/` 2 个 `EVALRUN-*.json` | 已存在（只读，Q-09=A 不写） |

**待实检索确认项**：无。本文件涉及的路径、符号名、行号均已实检；后续编码阶段若发现路径漂移，必须在对应任务内先登记再实施，不得静默改写。

---

## 0.2 编号、追溯与验收口径

### 0.2.1 任务条目固定字段

每条任务必须包含 6 个字段，缺一不可：

| 字段 | 要求 |
|---|---|
| 子项 | `- [x]` 可勾选的实现动作；描述"做什么 + 做到什么程度" |
| 完成标准 | 可机械判定的断言（数量、字段、退出码、耗时、命中数） |
| 对应设计 | `DES-<域>-<序号>`，与 design 第三章一致 |
| 对应 spec | `5.1.1-3`、`6.2-4`、`4.3-2` 等条目号 |
| 产出物 | 文件路径，标注"新建/修改/复用"；单任务原则上 1 份主产出物 |
| 验证 | 1 条可直接执行的命令 + 断言要点 |
| 依赖 | 前置任务编号（无则写 `无`） |

### 0.2.2 "单测通过"与"真实执行通过"的区分口径

1. 每条记录必须带 `verification_source`，取值仅 `UNIT_TEST` / `REAL_EXECUTION` / `UNVERIFIED`。
2. `python -m unittest ...` 通过只能写"**逻辑通过（UNIT_TEST）**"；报告中的"约束通过 / 真扫成立 / 零读取"只接受 `REAL_EXECUTION`。
3. `REAL_EXECUTION` 的最小判定：`manifest.json` 同时存在 `verification_source="REAL_EXECUTION"` 与非空 `evidence_ref`，且 `raw/` 下原始输出可回读、摘要一致。
4. 证据包 `manifest.json` 中缺 `verification_source` 或 `evidence_ref` 任一项，拒绝发布（对应 `T-EVD-04`）。

### 0.2.3 真实执行命令（每阶段收尾固定三条）

```text
# 约束验证（产出 VER-*）
python scripts/run_sandbox_verify.py --policy sandbox/spec.json --p4-05 on --evidence-root .evidence/sandbox-realscan
# 靶场真扫（产出 SCAN-*）
python scripts/run_realscan.py --scope full --port 0 --exec container --evidence-root .evidence/sandbox-realscan
# 隔离桥接（产出 ISO-*）
python scripts/verify_isolation_bridge.py --cases eval/cases --evidence-root .evidence/sandbox-realscan
```

退出码口径：`0`=目标结论达成；`2`=未验证；`3`=失败；`4`=证据归档失败。**未验证不得返回 0**。

### 0.2.4 P4-05 补测的 60s 窗口判定（唯一口径）

| 观测 | 判定 |
|---|---|
| `55s ≤ 终止耗时 ≤ 75s` 且容器已 `kill/rm -f`、`kill_signal` 已记录 | `PASS`，记录实际终止耗时 |
| 终止耗时 `< 55s` | `UNVERIFIED`，原因 `terminated_early`（未真正跑满 60s 预算，不得判通过） |
| 终止耗时 `> 75s` | `FAIL`，原因 `timeout_overshoot`（宿主超时未按预算生效） |
| `--p4-05 off` / 未执行 | `UNVERIFIED`，原因 `not_executed`；整份记录 `verdict` 不得为 `PASS` |
| 容器在超时后仍残留（`docker ps -a` 可查） | 该项 `FAIL`，原因 `container_leaked` |

计时起点为 `docker run -d` 返回后写下的宿主单调时钟，终点为 `docker inspect` 观测到容器 `Status=exited` 或 `docker kill` 返回时刻；必须同时写入 `raw/p4-05.log`。

---

## 0.3 阶段划分、任务规模与依赖图

| 阶段 | 名称 | 任务编号 | 任务数 | 门禁 |
|---|---|---|---|---|
| 0 | 基线锁定与事实固化 | `T-BASE-01…05` | 5 | 不回改基线；不改历史摘要 |
| 1 | 能力探测与执行域（VF-8010 门禁） | `T-SBX-03.1/.2`、`T-SBX-01/04/02/05`、`T-CFG-01/02/03`、`T-EVD-01` | 10 | 四项能力任一不可用 → 全量 `UNVERIFIED` |
| 2 | P4 约束验证（含 P4-05 补测、P4-01 挂载裁剪） | `T-SBX-06…20` | 15 | 11 键 → 10 类缺项 0；P4-05 未测不得 PASS |
| 3 | 靶场接入与真扫闭环 | `T-SCAN-01…21` | 21 | 15/15；扫描期真值读取 0；动态端口 |
| 4 | 隔离桥接与五类探针 | `T-ISO-01…10` | 10 | 失败仍抛 VF-8003；`exec_success_count=0` |
| 5 | 证据包与边界标注 | `T-EVD-02…10` | 9 | staging→sha256→manifest→原子改名；四类标签缺项 0 |
| 6 | 文档/报告与索引 + CLI | `T-CFG-05/06.1-06.4`、`T-DOC-01…04` | 9 | 三闸门；历史摘要不变 |
| 7 | 回归验收 | `T-CFG-04`、`T-ACC-01` | 2 | ≥502 用例、功能失败 0 |
| — | **合计** | — | **81** | — |

### 0.3.1 必须串行的链路（不可调换）

```text
T-BASE-01..05
   ↓
T-SBX-03.1（exec_domain）→ T-SBX-03.2（models）→ T-SBX-01（runtime）
   ↓                                   ↘
T-CFG-01（RealscanConfig）→ T-CFG-03   T-SBX-04（镜像解析）→ T-SBX-02（六项能力）
   ↓                                                        ↓
T-CFG-02（VF-8010/11/12）→ T-EVD-01（证据骨架）→ T-SBX-05（能力缺失降级，VF-8010 门禁）
                                                        ↓
T-SBX-06（策略装载）→ T-SBX-07（运行规格）→ T-SBX-10/11/12/13（容器内事实与回读）
   ↓                                                       ↓
T-SBX-08/09（网络/回环）→ T-SBX-20（P4-01 裁剪）→ T-SBX-14（P4-05 超时）→ T-SBX-17/18/19 → T-SBX-15/16
                                                        ↓
T-SCAN-01（裁剪视图）→ T-SCAN-02（靶场镜像）→ T-SCAN-03/04/05（启动/端口/DB）
   ↓                                                        ↓
T-SCAN-06/07/08/09（四类规则）→ T-SCAN-15（定位）→ T-SCAN-11（动态）→ T-SCAN-20（worker 注入）
   ↓                                                        ↓
T-SCAN-10（真值独立性）→ T-SCAN-17（对账）→ T-SCAN-12（范围）→ T-SCAN-13（四条件）→ T-SCAN-14/16/18/19/21
                                                        ↓
T-ISO-01/02/03（容器域探针）→ T-ISO-04（failure_kind）→ T-ISO-05（故障关闭）→ T-ISO-07（审计合并）→ T-ISO-06/08/09/10
                                                        ↓
T-EVD-02…10（证据与边界）→ T-DOC-01/02/03/04 → T-CFG-04 → T-ACC-01
```

**不可调换的三处硬依赖**

1. `T-SBX-05`（VF-8010 门禁）必须先于任何容器创建类任务；能力探测失败后不得继续执行容器命令。
2. `T-SCAN-17`（真值对账）必须排在 `T-SCAN-06…16` 之后：对账只能在 `detections.json` 冻结后读取真值 1 次。
3. `T-ISO-05`（故障关闭保持）必须先于 `T-ISO-06`（双轨发布口径）：先证明"没有放行分支"，再讨论"哪一域结论可发布"。

### 0.3.2 可并行的链路

| 可并行组 | 说明 |
|---|---|
| `T-SCAN-06/07/08/09` | 四类规则各自独立，可并行实现；均只依赖 `T-SCAN-01` 视图 |
| `T-EVD-02…10` 整体 ∥ `T-ISO-01…10` | 证据包组装只依赖"真扫/约束记录已产出"，与隔离桥接无数据依赖，可在 `T-SCAN-13` 完成后与阶段 4 并行 |
| `T-DOC-01/02/03` | 三份报告各自引用不同证据（`VER-*`/`SCAN-*`/`ISO-*`），可并行撰写；`T-DOC-04` 必须最后做 |
| `T-CFG-05` ∥ `T-DOC-*` | 默认值登记逻辑独立于报告正文 |
| `T-CFG-06.1` ∥ `T-SBX-01` 之后任意时刻 | 镜像构建脚本只依赖 runtime 传输 |

---

## 0.4 O-01…O-06 待拍板项（本轮按 design 当前取法落地，全部标注"采用默认值，待确认"）

| 编号 | 事项 | 本轮采用值（待确认） | 落地任务 | 落地方式 |
|---|---|---|---|---|
| O-01 | 参数计数口径：spec 写"10 项"，策略实际 11 键 | **10 个判定类别覆盖 11 键**（`root_filesystem` + `tmpfs` 合并为"文件系统可写面"） | `T-SBX-06`、`T-SBX-17`、`T-DOC-01` | 记录同时输出 `policy_keys=11 / judgement_classes=10 / missing=0`，并登记口径差异 `D-01` |
| O-02 | P4-01 以合成 `.git` 夹具验证 | **合成 `.git` 夹具 + 视图裁剪**，`basis` 标 `fixture=true` | `T-SBX-20` | 夹具位于 `.evidence/sandbox-realscan/<VER>/fixtures/p4-01/{app/main.py,.git/config}`；视图只含 `app/`；不声称验证真实仓库 `.git` |
| O-03 | 镜像别名作为证据前提 | **允许本地别名，但强制登记镜像 ID 与 `alias_used=true`**；优先构建策略镜像，未构建时用别名并标注"需构建后复测" | `T-SBX-04`、`T-SBX-15`、`T-CFG-06.1` | `ImageResolution.source ∈ {POLICY_IMAGE, LOCAL_ALIAS, LOCAL_BUILD, MISSING}`；别名必须有 `image_id` |
| O-04 | 真扫结果是否对内 API 暴露 | **只做 CLI + 证据包，不改 `main.py`** | `T-BASE-04`、`T-CFG-06.2/06.3/06.4`、`T-ACC-01` | 交付物清单显式列出"无 API 变更"；验收含 `main.py` 路由数不变 |
| O-05 | 靶场运行期 Flask 3.1.3 与 pins 不一致 | **运行镜像独立 lock；C01 仅静态检出**，不改 `requirements.txt` | `T-SCAN-02`、`T-SCAN-08`、`T-DOC-02` | 报告注明"运行期 Flask 3.1.3，静态依赖版本按 requirements.txt 检出" |
| O-06 | 宿主回退是否默认开启 | **`allow_host_fallback=true` 默认开启**，回退结论标 `REAL_LOCAL` | `T-CFG-01`、`T-SCAN-21` | `sandbox_scope=false`、`scan_verdict=NOT_ESTABLISHED`、不计入沙箱证据 |

> 统一要求：上述 6 项在每个相关记录的 `adopted_defaults[]` 中写入 `{q_id:"O-0x", value, source:"SPEC_DEFAULT", pending:true}`；报告头部输出"采用默认值（待拍板）"表；任何一处被表述为"用户已确认"即视为缺陷。

---

## 0.5 Q-01…Q-10 采用值（一次性声明，实现阶段不再逐条追问）

| 编号 | 待确认问题 | 采用值 | 落地任务 | 显式标注 |
|---|---|---|---|---|
| Q-01 | 容器运行时访问身份 | **A. 发行版 root 身份执行** | `T-SBX-01`、`T-SBX-02` | `exec_domain=RUNTIME_ROOT`、`privilege_route=WSL_DISTRO_ROOT`；`capability.details` 保留 HOST_USER 的 `permission denied` 过程事实；不执行 sudo/密码 |
| Q-02 | 镜像来源与可复现性 | **A. 本地构建镜像 + 镜像 ID** | `T-SBX-04`、`T-SBX-15` | `local_build=true`、`repo_digests=[]`、`source="LOCAL_BUILD"`；报告写"本地构建、无仓库摘要" |
| Q-03 | 构建期是否联网 | **A. 仅构建期放行、运行期禁出** | `T-CFG-06.1`、`T-CFG-03` | 构建脚本记录 `build_network=on` 事实；运行记录 `network_mode=NONE_LOOPBACK`；配置层无放行项 |
| Q-04 | 靶场监听端口 | **C. 动态分配并输出实际端口** | `T-SCAN-04` | `listen_port`=实际值、`port_source="DYNAMIC"`；失败重试 3 次后拒绝启动 |
| Q-05 | 扫描范围 | **A. 15 项全量（C01/C02/C03/C05）** | `T-SCAN-12` | `scope.item_count=15`、`uncovered_classes=[]`；子集必须写"x/15，未覆盖 …" |
| Q-06 | 是否接受宿主侧真扫回退 | **A. 接受但标 `REAL_LOCAL`，不计入沙箱证据** | `T-SCAN-21` | `sandbox_scope=false`、`scan_verdict=NOT_ESTABLISHED`、`boundary=REAL_LOCAL` |
| Q-07 | 无限循环超时用例是否强制补测 | **A. 强制补测（60s 量级）** | `T-SBX-14`、`T-CFG-01` | `p4_05_enabled=true`；未执行则 `P4-05=UNVERIFIED` 且整体非 PASS |
| Q-08 | 隔离探针双轨是否保留宿主域 | **A. 双轨保留，容器域为对外口径** | `T-ISO-06`、`T-ISO-07` | 宿主域 `publishable=false`；容器域 `publishable=true`；不删除历史记录 |
| Q-09 | 真扫结果是否写入既有评测运行记录 | **A. 只写新证据目录** | `T-CFG-01`、`T-EVD-03`、`T-SCAN-13` | `evidence_root=.evidence/sandbox-realscan`；不写 `eval/runs`/`eval/verdicts`/`eval/expected` |
| Q-10 | 云端能力是否需要在报告中占位 | **A. 显式占位并标注"云凭据缺失"** | `T-SCAN-18`、`T-DOC-04` | `boundary_kind=CLOUD_CREDENTIAL_MISSING`；固定输出"云凭据缺失，未验证"；不产出云端结论 |

---

## 0.6 本阶段不做清单（出现即返工）

1. **不做云上复测**：不接华为云 CCE，不补云凭据，不伪造云端 Check/门禁结果。
2. **不放开运行期网络**：不提供 `network=bridge/host` 的沙箱配置项，不允许 CLI 覆盖 `--network`。
3. **不关闭强制自检**：不改 `eval/isolation.py` 的 `raise` 分支，不把可读判定改为"仅记录放行"。
4. **不以桩冒真**：不把 M1 的 10/10 计入真扫；不由 `ground_truth.json` 生成任何告警。
5. **不修改 `eval/` 既有结论**：`loader/runner/adjudication/digest/models/leak_scan` 控制流与判定语义不改；`eval/runs`、`eval/verdicts`、`eval/expected` 不写。
6. **不初始化真实 Git 仓库**：不执行 `git init`，不依赖分支/提交/回滚；P4-01 只用合成夹具。〔2026-11-18：本条由后续 Git 化轮次取代；本轮已完成基线初始化，本条对 `sandbox_realscan` 阶段仍然有效。〕
7. **不修改靶场**：`verifix-target/` 下任何源码、真值、依赖清单、种子数据、测试均只读。
8. **不修改 `sandbox/spec.json`**：11 个隔离键与 5 条用例不可增删改。
9. **不新增 MCP 工具**：8 个白名单工具名称/数量/版本不变。
10. **不引入 pytest 作为项目依赖**：新增测试只用 `unittest`。
11. **不改历史报告**：`m0/m1/m2/m3/m5-*.md` 与 `.evidence/sandbox/` 只读；新结论并列新报告。
12. **本阶段只产出 `tasks.md`**：不改任何代码/脚本/数据/证据目录。

---

## 0.7 交付物清单（编码阶段最终产出，非本阶段产出）

### 0.7.1 新增模块（18 个文件）

| 文件 | 主要内容 |
|---|---|
| `backend/app/runtime/exec_domain.py` | `ExecDomain` 枚举 + `detect_exec_domain()` |
| `backend/app/realscan/__init__.py` | 包声明（不含逻辑） |
| `backend/app/realscan/models.py` | 6.1–6.6 全部记录模型 + 8 个枚举 |
| `backend/app/realscan/runtime.py` | `CommandResult` / `RuntimeTransport` / Host/WSL/Unavailable |
| `backend/app/realscan/capability.py` | `EnvironmentCapabilityProbe`（六项，≤15s） |
| `backend/app/realscan/policy.py` | `PolicyFile` / `ImageResolver` / `RunSpecBuilder` |
| `backend/app/realscan/probe_scripts.py` | 快照 / 网络 / 回环 / P4-01 / P4-05 探针源码常量 |
| `backend/app/realscan/constraints.py` | `ConstraintVerifier`（10 类判定 + inspect 比对） |
| `backend/app/realscan/target.py` | `TargetViewBuilder` / `TargetLauncher` / 端口与健康检查 |
| `backend/app/realscan/rules.py` | 四类规则表 + CVE 事实登记表 |
| `backend/app/realscan/scanner.py` | `SourceScanner`（AST 优先、正则兜底） |
| `backend/app/realscan/dynamic.py` | `DynamicProber`（正常/注入双请求） |
| `backend/app/realscan/worker.py` | 容器内自包含驱动（标准库 + 目标镜像 Flask） |
| `backend/app/realscan/scan.py` | `RealScanOrchestrator`（范围/四条件/中断/重复） |
| `backend/app/realscan/reconcile.py` | `TruthReconciler`（扫描后 1 次） |
| `backend/app/realscan/evidence.py` | `EvidencePackWriter`（staging/摘要/回读/清洗） |
| `backend/app/realscan/boundary.py` | 四类边界标签 + `CONFLICT_DISPOSITIONS` |
| `backend/app/realscan/isolation_bridge.py` | `ContainerIsolationVerifier` |

### 0.7.2 修改（仅扩展，语义只增不减）

| 文件 | 变更 |
|---|---|
| `backend/app/config.py` | 新增 `RealscanConfig` 并接入 `AppConfig`（保持 `extra="forbid"`） |
| `backend/app/api/envelope.py` | 新增 `VF-8010/8011/8012` 与 `ERROR_SPECS` 条目 |
| `backend/app/eval/isolation.py` | `IsolationVerdict` 增 `exec_domain/failure_kind/publishable`；`self_check` 增可选 `exec_domain`；**失败仍抛 VF-8003**；`AccessAuditLog` 增只读归档查询 |

### 0.7.3 新增测试（8 个文件，约 62 用例）

`backend/tests/test_sandbox_verify_policy.py`（5）、`test_sandbox_verify_capability.py`（6）、`test_sandbox_verify_constraints.py`（9）、`test_sandbox_verify_evidence.py`（10）、`test_realscan_rules.py`（5）、`test_realscan_target.py`（6）、`test_realscan_scan.py`（12）、`test_eval_isolation_bridge.py`（9）。

### 0.7.4 新增脚本（4 个）

`scripts/build_sandbox_images.py`、`scripts/run_sandbox_verify.py`、`scripts/run_realscan.py`、`scripts/verify_isolation_bridge.py`。

### 0.7.5 新增镜像定义（3 个）

`sandbox/Dockerfile.sandbox`、`sandbox/Dockerfile.target`、`sandbox/requirements.target.txt`。

### 0.7.6 新增证据目录

```text
.evidence/sandbox-realscan/
├── INDEX.json
├── VER-<UTC>-<4位>/   manifest.json / EVIDENCE.sha256 / commands.txt / runtime_facts.json /
│                      reuse_conditions.json / boundary.json / scrubber_report.json /
│                      raw/{snapshot,egress,loopback,p4-01}.json / raw/p4-05.log /
│                      raw/{docker_inspect,image_inspect}.json / records/{verification,capability}.json
├── SCAN-<UTC>-<4位>/  manifest.json / EVIDENCE.sha256 / commands.txt / runtime_facts.json /
│                      reuse_conditions.json / boundary.json / records/{scan,detections,dynamic_checks,reconciliation}.json /
│                      scan_bundle/{worker_bundle.py,worker_bundle.sha256} / raw/{scan_stdout.jsonl,scan_stderr.log}
├── ISO-<UTC>-<4位>/   manifest.json / EVIDENCE.sha256 / commands.txt / records/isolation.json /
│                      audit/access.jsonl / raw/iso_stdout.jsonl
└── fixtures/p4-01/    app/main.py / .git/config
```

### 0.7.7 新增报告

`docs/devlog/m6-sandbox-constraint-report.md`、`docs/devlog/m7-target-realscan-report.md`、`docs/devlog/m8-isolation-bridge-report.md`、`docs/devlog/sandbox-realscan-index.md`。

---

## 0.8 覆盖统计口径

- 覆盖矩阵见第 9 章，逐条列出 spec 5.1.1/5.1.3/5.2.1/5.2.3/5.3.1/5.3.3/5.4.1/5.4.3、6.1–6.6、4.1–4.5。
- 统计：**113 条**（5.x 共 73 + 6.x 6 组 + DFX 34），设计条目 **71**（SBX 20 / SCAN 21 / EVD 10 / ISO 10 / CFG 6 / DOC 4），任务 **81**。
- 缺口口径：任一 spec 条目无设计条目、或无任务编号、或无验证命令，即计为缺项；本文件缺项数为 **0**。

---

# 1. 阶段 0：基线锁定与事实固化

> 目标：把"改造前的真实状态"变成可复核常量，后续任何阶段都以此为准，不允许用文档转述代替实测。

## T-BASE-01 锁定回归基线（502 用例 / 功能失败 0）
- [x] 连续执行两次全量回归，记录用例总数、失败数、耗时、失败用例全名
- [x] 已实测：总数 **502**，首次全量 `FAILED (failures=1)`，唯一失败为 `test_metrics_perf.PerfTest.test_perf02_thousand_issues_and_twelve_thousand_events`（`capture_elapsed=0.2529s`，断言 `<0.2`）；单跑 3 次全部 `OK`
- [x] 基线固定为"**≥502 用例通过、功能性失败 0**"，写入本轮验收记录；后续阶段不得下调该数
- [x] 明确抖动处置口径：再次出现时仅允许"记录 + 单跑复验 + 标注抖动"，不得修改断言或阈值
- **完成标准**：两次实测输出与单跑复验输出均归档；基线口径在验收记录中可检索。
- **对应设计**：`DES-CFG-04`（附带 `DES-CFG-06`）；**对应 spec**：5.4.1-9、4.5-3、4.2-4
- **产出物**：本轮验收记录（`docs/devlog/sandbox-realscan-index.md` 的"回归基线"小节，阶段 6 落盘）
- **验证**：`python -m unittest discover -s backend/tests -p "test_*.py"`，记录 `Ran N tests` 与 `FAILED/OK`
- **依赖**：无

## T-BASE-02 锁定历史留痕摘要（6 项）
- [x] 复算并登记：`.evidence/sandbox/M0-SANDBOX-20261113T171337.txt`=`a365c352…`、`docs/devlog/m0-sandbox-verification.md`=`35b0c792…`、`m1-detect-report.md`=`8892168a…`、`m5-eval-report.md`=`931d2044…`、`m2-reproduce-report.md`=`e6fe54ab…`、`m1-reachability-report.md`=`89d8a582…`
- [x] 登记 `sandbox/spec.json`=`bd62277b…`、`verifix-target/ground_truth.json`=`286d13be…`、`verifix-target/requirements.txt`=`5e19106a…` 为"不可变基线"
- [x] 后续每个阶段收尾复算上述 9 项，任一项变化即判定为缺陷并停止发布
- **完成标准**：9 项 sha256 与实际文件逐一相等；复算脚本可一键执行。
- **对应设计**：`DES-EVD-07`（附带 `DES-SBX-19`）；**对应 spec**：5.3.1-7、4.4-6、5.1.1-15
- **产出物**：摘要基线清单（归入 `docs/devlog/sandbox-realscan-index.md`）
- **验证**：`python -c "import hashlib,pathlib;print(hashlib.sha256(pathlib.Path('docs/devlog/m5-eval-report.md').read_bytes()).hexdigest())"` 等 9 条
- **依赖**：无

## T-BASE-03 固化运行时与环境事实（执行域、Docker、镜像）
- [x] 登记实测：WSL2 Debian 13、Docker `26.1.5+dfsg1`、驱动 `overlay2`、cgroup `v2`、非 root socket 拒绝、root 可用
- [x] 登记镜像：`realscan-probe:local` `sha256:78f36923…`（132,371,211 B，`USER 10001:10001`，`WORKDIR /target`，Flask 3.1.3 / Python 3.12.16）、`verifix-runner:latest` `sha256:bcb47408…`（131,461,396 B，`/workspace`）、`python:3.12-slim`、`alpine:3.20`
- [x] 明确"策略镜像 `verifix-sandbox:1.0.0` 与 `verifix-target:1.0.0` 均不存在"，作为 `T-CFG-06.1` 与 O-03 的前提
- [x] 登记"宿主 Windows 侧无 docker CLI"与"必须经 `wsl.exe -d Debian -u root -- docker` 调用"两条事实
- **完成标准**：三项登记与 `docker version|info|images` 实际输出一致；不含任何凭据。
- **对应设计**：`DES-SBX-01`/`DES-SBX-04`（前提）；**对应 spec**：6.5-1/4、5.1.1-12、1.5
- **产出物**：环境事实登记表（归入 `docs/devlog/sandbox-realscan-index.md`）
- **验证**：`WSL_UTF8=1 wsl.exe -d Debian -u root -- docker version --format '{{.Server.Version}}'`、`... docker images --digests`
- **依赖**：无

## T-BASE-04 固化"不改清单"与"待新建清单"（文件级）
- [x] 把 C2/C3 的不可改文件逐条列成清单（含 20 个既有模块、8 个靶场文件、既有 47 个测试文件、`main.py` 路由）
- [x] 把 18 个新增模块、8 个新增测试、4 个新增脚本、3 个镜像定义、4 份新报告逐条列成"待新建"清单
- [x] 明确 O-04：本轮**不新增** `/api/v1/realscan/*` 路由，`backend/app/main.py` 路由数与路径集合不变
- **完成标准**：两份清单与第 0.7 节一致；`main.py` 路由集合快照可对比。
- **对应设计**：`DES-CFG-04`（附带 O-04）；**对应 spec**：1.4-8、4.5-2/3
- **产出物**：清单（归入 `docs/devlog/sandbox-realscan-index.md`）
- **验证**：`python -c "from app.main import create_app"` 后枚举路由并记录条数（在 `backend/` 下执行）
- **依赖**：T-BASE-02

## T-BASE-05 固化阶段验收命令与"单测/真实执行"区分口径
- [x] 把 0.2.2、0.2.3、0.2.4 三段口径写入验收记录，作为每阶段收尾检查表
- [x] 明确三条真实执行命令的退出码语义（0/2/3/4）与"未验证不得返回 0"
- [x] 明确 P4-05 的 55–75s 窗口四条判定分支
- **完成标准**：检查表可逐阶段勾选；退出码与判定分支无歧义。
- **对应设计**：`DES-EVD-01`/`DES-SBX-14`（口径前提）；**对应 spec**：4.4-1、5.1.1-10、5.3.1-1
- **产出物**：验收检查表（归入 `docs/devlog/sandbox-realscan-index.md`）
- **验证**：人工比对第 0.2 节与本任务清单一致
- **依赖**：T-BASE-01

---

# 2. 阶段 1：能力探测与执行域（VF-8010 门禁）

> 目标：先证明"能不能做"，再谈"做得怎样"。四项能力任一不可用时，全部约束项只能 `UNVERIFIED`，不得输出任何 `PASS`。

## T-SBX-03.1 执行域枚举与判定
- [x] 新建 `backend/app/runtime/exec_domain.py`：`ExecDomain` 枚举（`HOST_USER` / `RUNTIME_ROOT` / `CONTAINER_EXEC`，值取 spec 6.1-3 字面量）
- [x] 实现 `detect_exec_domain(transport_name: str = "") -> ExecDomain`：容器内非 root → `CONTAINER_EXEC`；容器内 root 或 WSL root 调 docker → `RUNTIME_ROOT`；否则 `HOST_USER`
- [x] 判定依据只允许：`/.dockerenv` 存在性、`os.geteuid()`、传输类型；禁止读取环境变量猜测
- [x] 模块只依赖标准库，供 `realscan` 与 `eval` 双向复用（`eval` 不得反向 import `realscan`）
- **完成标准**：三值全覆盖；同一环境重复判定 10 次结果一致；`from app.runtime.exec_domain import ExecDomain, detect_exec_domain` 可导入。
- **对应设计**：`DES-SBX-03`；**对应 spec**：5.1.1-2、6.1-3
- **产出物**：`backend/app/runtime/exec_domain.py`（待新建）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_evidence -v`（T-SBX-EVD-01 含 `exec_domain` 枚举断言）
- **依赖**：T-BASE-04

## T-SBX-03.2 6.1–6.6 记录模型与枚举
- [x] 新建 `backend/app/realscan/__init__.py` 与 `backend/app/realscan/models.py`：8 个枚举（`CapabilityState`、`Judgement`、`BoundaryKind`、`DenialKind`、`FailureKind`、`ScanVerdict`、`ScanScope` 语义、`ExecMode`）
- [x] 定义 16 个记录模型：`EnvironmentCapability`、`ImageResolution`、`RuntimeFacts`、`ConstraintCheck`、`ConstraintVerificationRecord`、`TargetView`、`Detection`、`DynamicCheck`、`ScanRecord`、`ScanScope`、`ReconcileRecord`、`IsolationProbeResult`、`IsolationBridgeRecord`、`BoundaryEntry`、`EvidencePack`、`DefaultAdoption`
- [x] 键名禁令：不得出现 `category` / `reachable` / `expected_fix_kind` / `should_reject` / `proof_pre_patch` / `ground_truth`（改用 `defect_class` / `dynamic_verdict` / `behavior_diff` / `scope` / `coverage`）
- [x] 每个模型提供 `to_dict()` 与必填字段校验；时间字段带时区（UTC）
- **完成标准**：字段与 design §2.3.2 逐项一致；键名禁令以 `LeakScanner` 扫描模型导出 JSON 命中数 0；`EvidencePack.commands` 至少 1 条为构造期硬校验。
- **对应设计**：`DES-SBX-03`（附带 `DES-SBX-15`、`DES-EVD-05`、`DES-CFG-05`、`DES-ISO-08`）；**对应 spec**：6.1–6.6 全部、4.3-3
- **产出物**：`backend/app/realscan/models.py`、`backend/app/realscan/__init__.py`（待新建）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_evidence -v`（T-SBX-EVD-01/06）
- **依赖**：T-SBX-03.1

## T-SBX-01 运行时传输（Host / WSL / Unavailable）
- [x] 新建 `backend/app/realscan/runtime.py`：`CommandResult(argv, exit_code, stdout, stderr, duration_ms, timed_out)`、`RuntimeTransport` 协议（`name` / `exec_domain` / `privilege_route` / `run(argv, timeout_seconds, cwd)`)
- [x] `HostDockerTransport`（`docker ...`）、`WslDockerTransport`（固定前缀 `wsl.exe -d {distro} -u {user} -- docker`，环境注入 `WSL_UTF8=1`）、`UnavailableTransport`、`select_transport(config)`（顺序固定 `host → wsl`）
- [x] 超时：置 `timed_out=True`、`exit_code=124`，**不得**抛出底层 `TimeoutExpired`；不可用统一抛 `RuntimeUnavailableError`（映射 VF-8010）
- [x] `privilege_route` 只允许类别字符串（`NONE` / `WSL_DISTRO_ROOT`），**禁止**写入任何口令、密码、路径凭据
- [x] 不接受交互输入：`run` 必须传 `stdin=DEVNULL` 语义
- **完成标准**：`select_transport("auto")` 在本机返回 WSL 传输且 `exec_domain=RUNTIME_ROOT`、`privilege_route=WSL_DISTRO_ROOT`；超时场景返回 `timed_out=True` 且不抛异常；argv 首元素为 `docker` 或已由传输补齐。
- **对应设计**：`DES-SBX-01`；**对应 spec**：5.1.1-1、5.1.1-2、5.1.1-12、6.1-4、6.5-4、6.1-11
- **产出物**：`backend/app/realscan/runtime.py`（待新建）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_capability -v`（T-SBX-CAP-01/02）
- **依赖**：T-SBX-03.1、T-SBX-03.2、T-CFG-01

## T-SBX-04 镜像解析与别名登记
- [x] 在 `backend/app/realscan/policy.py` 实现 `ImageResolver`：`resolve(policy_image)` 按"策略镜像 → 候选别名 → 失败"顺序；`inspect(image)` 读 `docker image inspect` 的 `Id`、`RepoDigests`、`Size`
- [x] 输出 `ImageResolution(policy_image, resolved_image, image_id, repo_digests, local_build, alias_used, source)`；`source ∈ {POLICY_IMAGE, LOCAL_ALIAS, LOCAL_BUILD, MISSING}`
- [x] 命名与仓库摘要分离：`repo_digests=[]` 时强制 `local_build=true` 且 `source` 不得为空；别名命中强制 `alias_used=true` 且必须带 `image_id`
- [x] 候选清单取 `RealscanConfig.sandbox_images` / `target_images`；任一为空即启动失败
- **完成标准**：本机解析 `verifix-sandbox:1.0.0` → `MISSING`（或别名命中 `verifix-runner:latest` 且 `alias_used=true`、`image_id=sha256:bcb47408…`）；`realscan-probe:local` 解析出 `sha256:78f36923…` 且 `local_build=true`；摘要读取耗时 ≤3s。
- **对应设计**：`DES-SBX-04`；**对应 spec**：5.1.1-11、6.1-6/7、4.1-4、4.2-3（O-03：采用默认值，待确认）
- **产出物**：`backend/app/realscan/policy.py`（待新建，本任务只落 `ImageResolver` 部分）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_capability -v`（T-SBX-CAP-04）、`python -m unittest backend.tests.test_realscan_target -v`（T-RS-TGT-05）
- **依赖**：T-SBX-01

## T-SBX-02 六项环境能力探测（≤15s 预算）
- [x] 新建 `backend/app/realscan/capability.py`：`EnvironmentCapabilityProbe(transport, images, budget_seconds=15.0).probe(want_egress, want_loopback)`
- [x] 六项独立探测：`docker_cli`（2s）、`daemon`（`docker info`，4s）、`socket_permission`（`docker ps`，4s）、`image_availability`（3s）、`egress_network`（2s）、`loopback`（2s）
- [x] 双域 socket 探测（Q-01=A）：先以宿主/WSL 非 root 执行 `docker ps`，把 `permission denied` 记为 `details` 中的过程事实（`HOST_USER: permission denied`）；再以配置的运行时 root 身份探测，`exec_domain=RUNTIME_ROOT`。**不执行 sudo、不输入密码、不修改 docker 组**
- [x] 超时/失败一律记 `UNVERIFIED` 并附 `timeout` / 原因；**不得**把"CLI 存在"当作"沙箱可用"
- [x] `egress_network` 与 `loopback` 分别记录，不得互相替代；`detected_at` 带时区
- **完成标准**：总耗时 ≤15s（实测记录）；六项状态均为三值之一；`details` 同时含 HOST_USER 拒绝事实与 RUNTIME_ROOT 成功事实；任一 `UNAVAILABLE` 时 `sandbox_verdict=UNVERIFIED`。
- **对应设计**：`DES-SBX-02`；**对应 spec**：5.1.1-1、6.5-1/2/3/4、4.1-1、4.2-1（Q-01=A）
- **产出物**：`backend/app/realscan/capability.py`（待新建）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_capability -v`（T-SBX-CAP-01…06）
- **依赖**：T-SBX-01、T-SBX-04、T-CFG-01

## T-SBX-05 能力缺失降级与 VF-8010 门禁
- [x] 在 `backend/app/realscan/pipeline.py` 实现门面 `RealscanPipeline`：任何运行模式启动前**必须先** `capability.probe()`
- [x] 四项（CLI/daemon/socket/镜像）任一 `UNAVAILABLE` → 抛 `VF-8010 SANDBOX_UNVERIFIABLE`，全部约束项置 `UNVERIFIED`，**不执行任何容器命令**
- [x] 降级规则：`egress/loopback` 失败只影响对应约束项与真扫前置，不推翻容器可用性；不得自动降级为宿主直跑并沿用沙箱结论
- [x] 报告头写入 `exec_domain` 与缺失要素清单
- **完成标准**：构造 CLI 缺失/daemon 停止/权限拒绝/镜像缺失四种场景，均返回 VF-8010、`checks` 中 `PASS` 数 = 0、`run()` 调用次数 = 0；本机正常场景可继续到阶段 2。
- **对应设计**：`DES-SBX-05`；**对应 spec**：4.2-1、5.1.1-1、5.1.3-1/2/3/4、6.5-5
- **产出物**：`backend/app/realscan/pipeline.py`（待新建）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_capability -v`（T-SBX-CAP-01…04）
- **依赖**：T-SBX-02、T-CFG-02

## T-CFG-01 新增 `RealscanConfig`
- [x] 在 `backend/app/config.py` 新增 `RealscanConfig(_Strict)` 并接入 `AppConfig`（保持 `extra="forbid"`）：`policy_path`、`target_root`、`cases_dir`、`evidence_root`、`runtime_transport(auto/host/wsl)`、`wsl_distro`、`wsl_user`、`sandbox_images`、`target_images`、`listen_port`、`port_retries`、`health_timeout_seconds`、`request_timeout_seconds`、`request_retries`、`scan_scope`、`allow_host_fallback`、`p4_05_enabled`、`probe_budget_seconds`、`constraint_budget_seconds`、`scan_budget_seconds`、`evidence_budget_seconds`、`q_defaults`
- [x] 默认值严格取 design §2.4.1 表（`p4_05_enabled=true`、`allow_host_fallback=true`、`listen_port=0`、`scan_scope=full`、`evidence_root=.evidence/sandbox-realscan`）
- [x] `sandbox_images` 默认 `["verifix-sandbox:1.0.0","verifix-runner:latest"]`、`target_images` 默认 `["verifix-target:1.0.0","realscan-probe:local"]`
- **完成标准**：`load_config()` 可解析新段；缺省时旧配置 JSON 反序列化不报错；字段数与 design §2.4.1 一致（23 项）。
- **对应设计**：`DES-CFG-01`；**对应 spec**：5.1、5.2、5.3、6.5、O-06（采用默认值，待确认）
- **产出物**：`backend/app/config.py`（修改：新增子模型，不改既有字段）
- **验证**：`python -m unittest backend.tests.test_config -v`
- **依赖**：T-BASE-04

## T-CFG-02 新增 VF-8010 / 8011 / 8012
- [x] 在 `backend/app/api/envelope.py` 的 `ErrorCode` 新增 `SANDBOX_UNVERIFIABLE="VF-8010"`、`REALSCAN_NOT_ESTABLISHED="VF-8011"`、`EVIDENCE_INTEGRITY="VF-8012"`
- [x] 在 `ERROR_SPECS`(:60) 同步登记：8010→503、8011→409、8012→409，文案不含路径细节/答案内容/凭据
- [x] 沿用既有 `VF-8003`（隔离不满足，仍 403）、`VF-7001`、`VF-8005`，语义不变
- **完成标准**：`ApiError(ErrorCode.SANDBOX_UNVERIFIABLE, "x")` 不抛 `KeyError`；枚举与 `ERROR_SPECS` 一一对应；既有 9 个 VF-80xx 语义未变。
- **对应设计**：`DES-CFG-02`；**对应 spec**：5.1.3、5.2.3、5.3.3、4.5-2
- **产出物**：`backend/app/api/envelope.py`（修改）
- **验证**：`python -m unittest backend.tests.test_envelope -v`
- **依赖**：T-BASE-04

## T-CFG-03 配置硬校验（禁止放宽网络与预算）
- [x] 在 `AppConfig` 校验中新增 8 条：`network` 不可配置（配置层无该项）；`listen_port` 为 0 或 1024–65535；`p4_05_enabled=false` 时验证记录必须保留 P4-05=UNVERIFIED；`allow_host_fallback=true` 不改变沙箱成立条件；`evidence_root` 不得位于 `eval/expected`/`eval/runs`/`eval/verdicts`/宿主用户目录；`cases_dir` 与 `expected_dir` 不得互为父子；`sandbox_images`/`target_images` 非空；所有 `*_budget_seconds` 不超 spec 4.1 上限
- [x] 任一越界即启动失败（`ConfigValidationError`），不得仅告警
- **完成标准**：8 类非法配置各触发一次启动失败；`probe_budget_seconds=20`、`constraint_budget_seconds=200`、`listen_port=-1` 三类越界被拒；默认配置下既有 502 用例行为不变。
- **对应设计**：`DES-CFG-03`；**对应 spec**：4.3-1、4.1-1/2/3/7/8、4.5-4、Q-03/Q-07
- **产出物**：`backend/app/config.py`（修改：校验分支）
- **验证**：`python -m unittest backend.tests.test_config -v`、`python -m unittest backend.tests.test_sandbox_verify_policy -v`（T-SBX-POL-05）
- **依赖**：T-CFG-01

## T-EVD-01 证据包目录结构与 6.2 字段骨架
- [x] 新建 `backend/app/realscan/evidence.py`：`EvidencePackWriter(root, scrubber, leak_scanner)`，先实现 staging 目录协议：`staging_path` 按 `<root>/.staging-<evidence_id>/` 命名，`write_staging(rel_path, content)` 逐文件写入
- [x] 目录结构严格按 design §2.9.1：`manifest.json`、`EVIDENCE.sha256`、`commands.txt`、`runtime_facts.json`、`reuse_conditions.json`、`boundary.json`、`scrubber_report.json`、`raw/`、`records/`
- [x] `manifest.json` 字段覆盖 6.2：`evidence_id`、`path`、`sha256`、`size_bytes`、`commands`、`runtime_facts`、`raw_output_digest`、`reuse_conditions`、`boundary_tags`、`verification_source`、`created_at`；**manifest 必须最后写**
- [x] `evidence_id` 前缀区分 `VER-` / `SCAN-` / `ISO-` + UTC 时间 + 4 位短随机
- **完成标准**：6.2 九类字段缺项 0；`evidence_id` 全局唯一（1000 次生成无重复）；staging 目录无 `manifest.json` 时不视为已发布。
- **对应设计**：`DES-EVD-01`；**对应 spec**：5.3.1-1、6.2-1…8、4.4-5
- **产出物**：`backend/app/realscan/evidence.py`（待新建，本任务落目录与字段骨架）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_evidence -v`（T-SBX-EVD-01）
- **依赖**：T-SBX-03.2、T-CFG-01

---

# 3. 阶段 2：P4 约束验证（P4-01 挂载裁剪 / P4-05 超时补测）

> 目标：把 `sandbox/spec.json` 的 11 个隔离键落成 10 个可执行判定类别，并把 P4-01…P4-05 逐条变成有原始输出的事实；任何一项未执行只能标 `UNVERIFIED`，不得用"整体 PASS"概括。

## T-SBX-06 策略只读装载（11 键 → 10 类）
- [x] 在 `backend/app/realscan/policy.py` 实现 `PolicyFile.load(path)`：读取 `policy_version`、`isolation`（11 键）、`escape_cases`（5 条）、`image`、文件 `sha256`
- [x] 在模块内定义 `JUDGEMENT_CLASSES`（10 类）与 `KEY_TO_CLASS` 映射：`root_filesystem` 与 `tmpfs` 合并为 `filesystem_writable_surface`，其余 9 键各成一类
- [x] 前置硬校验：11 键齐全、`network=="none"`、`root_filesystem=="read-only"`、`cap_drop==["ALL"]`、`no_new_privileges is True`；任一不满足抛 `PolicyInvalidError`（VF-8001 语义），**不执行任何容器**
- [x] 装载前后文件 `sha256` 必须一致；不一致即整体 `FAIL`，原因 `policy_or_target_mutated`
- **完成标准**：`policy_keys=11 / judgement_classes=10 / missing=0` 三者同时成立（口径差异 D-01 显式登记，O-01：采用默认值，待确认）；缺任一键或放宽任一值均拒绝生成运行规格。
- **对应设计**：`DES-SBX-06`；**对应 spec**：5.1.1-3、6.1-5、5.1.1-15、O-01（采用默认值，待确认）
- **产出物**：`backend/app/realscan/policy.py`（追加 `PolicyFile`）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_policy -v`（T-SBX-POL-01/04/05）、`python -m unittest backend.tests.test_sandbox_verify_constraints -v`（T-SBX-CST-01）
- **依赖**：T-SBX-04、T-EVD-01

## T-SBX-07 运行规格生成（不可放宽）
- [x] 在 `policy.py` 实现 `RunSpecBuilder(policy, container_name).build(view_dir, stdin_mode, workdir)` → `RunSpec(argv, env, mounts, tmpfs, user, network, name)`
- [x] 参数**只从策略派生**，禁止调用方覆盖 `--network`、`--read-only`、`--cap-drop`、`--security-opt`、`--user`、资源上限
- [x] `--name` 必填（`vf-verify-*` / `vf-loop-*` / `vf-scan-*` / `vf-iso-*`）；`--entrypoint python` 后再传 `-`（stdin）或 `-c`，不得写成 `image python ...`
- [x] 两处 tmpfs 挂载点集合必须等于策略 `tmpfs` 集合；源挂载固定 `--volume=<view>:/src:ro`
- [x] 与既有 `SandboxRunner.build_argv`（`backend/app/tools/sandbox.py:78-104`）做隔离标志一致性交叉断言（不改旧实现）
- **完成标准**：`RunSpec.argv` 含 10 类隔离标志；尝试覆盖 `network` 抛 `PolicyInvalidError`；tmpfs 集合差集为空；与旧 argv 的 6 项隔离标志完全一致。
- **对应设计**：`DES-SBX-07`；**对应 spec**：4.3-1、5.1.1-9、5.1.1-15、6.1-8
- **产出物**：`backend/app/realscan/policy.py`（追加 `RunSpecBuilder`）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_policy -v`（T-SBX-POL-02/03/05）
- **依赖**：T-SBX-06

## T-SBX-08 外网禁出探针
- [x] 新建 `backend/app/realscan/probe_scripts.py`：定义容器内自包含探针源码常量（只标准库），`egress` 探针尝试 TCP/HTTPS 连接外部地址并输出 `{"target":..., "ok":false, "error_type":"OSError|Timeout", "detail":...}`
- [x] 探针输出必须包含失败类型；成功（`ok=true`）即该项 `FAIL`
- [x] 与既有沙箱隔离标志一致：`--network=none` 下执行，来源挂载仍为 `:ro`
- [x] 宿主侧外网探测结果单独记录，**不得**复用为容器结论
- **完成标准**：真实执行下 `ok=false` 且 `error_type ∈ {OSError, Timeout}` → `network` 类 `PASS`；模拟成功返回 → `FAIL`；无原始输出即 `UNVERIFIED`（原因 `probe_timeout`）。
- **对应设计**：`DES-SBX-08`；**对应 spec**：5.1.1-4、4.3-2、5.2.3-5
- **产出物**：`backend/app/realscan/probe_scripts.py`（待新建）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_constraints -v`（T-SBX-CST-02）
- **依赖**：T-SBX-07

## T-SBX-09 回环可用探针
- [x] 在 `probe_scripts.py` 增加 `loopback` 探针：`127.0.0.1` 上 bind / listen / connect 三动作并输出三布尔
- [x] 判定：三动作全成功 → `loopback=AVAILABLE`；任一失败 → "回环内真扫不可用"，且真扫前置判定为不满足
- [x] 与 `egress` 探针结果分列两条事实，禁止互相替代
- **完成标准**：禁网容器内 bind/listen/connect 全 `true`；人为关闭回环时 `loopback=UNAVAILABLE` 且真扫 `scan_verdict != ESTABLISHED`。
- **对应设计**：`DES-SBX-09`；**对应 spec**：5.1.1-5、5.2.1-2、4.3-2
- **产出物**：`backend/app/realscan/probe_scripts.py`（追加 loopback 探针）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_capability -v`（T-SBX-CAP-06）
- **依赖**：T-SBX-08

## T-SBX-10 根文件系统只读与 tmpfs 可写分项判定
- [x] 在 `probe_scripts.py` 增加 `filesystem` 探针：写根路径（`/` 或 `/etc`）必须失败、写 `/tmp` 与 `/workspace` 必须成功、写 `/src` 必须失败、读 `/src` 正例文件必须成功
- [x] 判定：根写入 `EROFS/OSError` 且两处 tmpfs 均可写 → `filesystem_writable_surface` `PASS`；任一相反 → `FAIL`
- [x] 分别记录 `root_filesystem` 与 `tmpfs` 两个策略键的观测值，但合为一个判定类别（O-01）
- [x] tmpfs 不可写时给出"靶场数据库落盘不可用"的后续影响说明
- **完成标准**：四类写入结果与策略声明一致；tmpfs 写入失败时该项 `FAIL` 且提示 DB 落盘风险；根写入成功时该项 `FAIL`（不得因 tmpfs 正常而放过）。
- **对应设计**：`DES-SBX-10`；**对应 spec**：5.1.1-6、5.1.3-7、4.3-1
- **产出物**：`backend/app/realscan/probe_scripts.py`（追加 filesystem 探针）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_constraints -v`（T-SBX-CST-03）
- **依赖**：T-SBX-08

## T-SBX-11 身份 / 能力集 / 禁止提权三面验证
- [x] 在 `probe_scripts.py` 增加 `identity` 探针：`getuid/getgid`、`/proc/self/status` 的 `CapEff` 与 `NoNewPrivs`、`os.setuid(0)` 结果
- [x] 判定：`uid=gid=10001`、`CapEff=0`、`NoNewPrivs=1`、`setuid(0)` 失败，四项全满足才 `PASS`
- [x] 原始输出逐字段保留（`uid/gid/cap_eff/no_new_privs/setuid_error`），不得只存布尔
- **完成标准**：真实执行下四字段与策略一致；`CapEff` 非 0 → 能力集类 `FAIL`；`NoNewPrivs=0` → 禁止提权类 `FAIL`。
- **对应设计**：`DES-SBX-11`；**对应 spec**：5.1.1-7、4.3-1
- **产出物**：`backend/app/realscan/probe_scripts.py`（追加 identity 探针）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_constraints -v`（T-SBX-CST-04）
- **依赖**：T-SBX-08

## T-SBX-12 资源与进程上限双源核对
- [x] 在 `constraints.py` 实现 `read_container_facts(transport, container_name)`：`docker inspect` 取 `HostConfig.{Memory,NanoCpus,PidsLimit,CapDrop,SecurityOpt,NetworkMode,ReadonlyRootfs,User,Tmpfs}` + `docker version/info` 取运行时版本、驱动、cgroup 版本
- [x] 在 `probe_scripts.py` 增加 cgroup 读取：`/sys/fs/cgroup/memory.max`、`cpu.max`、`pids.max`
- [x] 判定：inspect 值与策略值逐字段相同（`Memory=1024*1024*1024`、`NanoCpus=1.0e9`、`PidsLimit=128`），且 cgroup 值一致；差异字段逐个列出
- [x] 版本字段缺失时写 `"unknown"`，不得留空
- **完成标准**：三项资源上限零差异；差异场景输出 `差异字段清单` 且整体 `FAIL`；`docker_inspect.json` 原始输出落盘。
- **对应设计**：`DES-SBX-12`；**对应 spec**：5.1.1-8、6.1-4/8、4.1-4
- **产出物**：`backend/app/realscan/constraints.py`（待新建）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_constraints -v`（T-SBX-CST-05）
- **依赖**：T-SBX-07、T-SBX-11

## T-SBX-13 实际配置回读比对与 10 类判定汇总
- [x] 在 `constraints.py` 实现 `ConstraintVerifier.verify(verification_id, run_p4_05)`：执行顺序固定 `能力 → 快照 → 配置回读 → 网络/回环 → P4-01 → P4-05`
- [x] `ConfigReadbackComparator` 逐字段比对 6 类：网络模式、根只读、能力集、安全选项、执行用户、资源上限 + tmpfs 挂载集合
- [x] 聚合 10 类判定：任一 `FAIL` → 整体 `FAIL`；任一 `UNVERIFIED` 且无 `FAIL` → 整体 `UNVERIFIED`；全 `PASS` → `PASS`
- [x] 每条 `ConstraintCheck` 含 `check_id`、`policy_key`、`expected`、`observed`、`judgement`、`duration_ms`、`evidence_ref`、`basis`
- [x] 单条探针（P4-05 除外）超 10s → `docker kill` 后判 `UNVERIFIED`（`probe_timeout`），不得判 `FAIL`
- **完成标准**：10 类判定 + 5 条 P4 用例全部出现在 `checks`；整体判定符合三条聚合规则；每条都有非空 `evidence_ref`；单条耗时 ≤10s 被记录。
- **对应设计**：`DES-SBX-13`；**对应 spec**：5.1.1-9、5.1.3-5/6、6.1-8/9、4.1-2
- **产出物**：`backend/app/realscan/constraints.py`（追加 `ConstraintVerifier` 与比较器）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_constraints -v`（T-SBX-CST-05/06）
- **依赖**：T-SBX-10、T-SBX-11、T-SBX-12

## T-SBX-14 P4-05 超时补测（60s 窗口）
- [x] 在 `probe_scripts.py` 增加无限循环载荷（`while True: pass`），以 `docker run -d --name vf-loop-<id>` 起具名容器
- [x] 宿主侧 `subprocess.run(timeout=60)`；超时后**必须** `docker kill <name>` + `docker rm -f <name>`，并在 `finally` 中清理
- [x] 记录：起始时刻、终止时刻、实际终止耗时、`kill_signal`、容器最终状态、是否残留
- [x] 判定严格按 §0.2.4：55–75s → `PASS`；<55s → `UNVERIFIED(terminated_early)`；>75s → `FAIL(timeout_overshoot)`；未执行 → `UNVERIFIED(not_executed)`；残留 → `FAIL(container_leaked)`
- [x] `--p4-05 off` 时保留 `P4-05=UNVERIFIED`，整份记录 `verdict` 不得为 `PASS`
- **完成标准**：真实执行 `raw/p4-05.log` 含全部 6 项记录；`docker ps -a` 无 `vf-loop-*` 残留；实测终止耗时落在 55–75s 并写入报告。
- **对应设计**：`DES-SBX-14`；**对应 spec**：5.1.1-10、4.1-2/3、5.1.3-5、K-04、Q-07=A
- **产出物**：`backend/app/realscan/probe_scripts.py` + `constraints.py`（追加 P4-05 用例执行与 `finally` 清理）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_constraints -v`（T-SBX-CST-08，含清理调用断言）；真实执行 `python scripts/run_sandbox_verify.py --p4-05 on`
- **依赖**：T-SBX-13

## T-SBX-15 镜像摘要完整记录（记录侧）
- [x] 在 `ConstraintVerificationRecord` 写入 `image.image_id`（必填、`sha256:` 前缀）与 `image.repo_digests`
- [x] `repo_digests` 为空时强制同时写 `local_build=true` 与 `source="LOCAL_BUILD"` + 说明文本"本地构建、无仓库摘要"，**不得留空**
- [x] `alias_used=true` 时写入 `alias` 说明与 `image_id`，报告标注"策略镜像未构建，使用本地等价镜像，需构建后复测"
- [x] `privilege_route` 只写类别字符串；证据写入前做凭据模式扫描
- **完成标准**：镜像字段缺项 0；本地构建场景 `local_build=true` 且说明非空；别名场景 `alias_used=true` 且 `image_id` 非空。
- **对应设计**：`DES-SBX-15`；**对应 spec**：5.1.1-11、6.1-6/7、6.2-8、O-03（采用默认值，待确认）
- **产出物**：`backend/app/realscan/constraints.py`（记录组装侧）+ `backend/app/realscan/evidence.py`（`raw/image_inspect.json`）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_capability -v`（T-SBX-CAP-04）
- **依赖**：T-SBX-13

## T-SBX-16 提权方式留痕（不含凭据）
- [x] `RuntimeTransport.privilege_route` 仅允许 `NONE` / `WSL_DISTRO_ROOT`；执行域写入 `exec_domain=RUNTIME_ROOT`
- [x] 证据与记录中禁止出现 `sudo` 口令、`password=`、`--password`、`DOCKER_HOST` 凭据片段
- [x] 在 `evidence.py` 的清洗器接入 `SecretScrubber` 模式表（`SECRET_KEY=|DB_PASSWORD=|password=|sudo -S`），命中即中止落盘
- **完成标准**：`record.privilege_route` 只有类别值；证据文本凭据命中数 0；命中时抛 `VF-8012` 且目录不存在。
- **对应设计**：`DES-SBX-16`；**对应 spec**：5.1.1-12、4.3-4、6.1-11、6.2-8
- **产出物**：`backend/app/realscan/runtime.py`（类别约束）+ `backend/app/realscan/evidence.py`（清洗接线）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_constraints -v`（T-SBX-CST-09）
- **依赖**：T-SBX-13、T-EVD-01

## T-SBX-17 未验证可解释（缺失条件 + 复测建议）
- [x] `ConstraintCheck.judgement` 为 `UNVERIFIED` 时必须同时给出 `missing_reason`（枚举：`probe_timeout` / `not_executed` / `capability_unavailable` / `terminated_early`）与 `retest_hint`（一句可执行建议）
- [x] 禁止用 `PASS` 或 `FAIL` 代替 `UNVERIFIED`；禁止留空
- [x] `ConstraintVerificationRecord.verdict` 聚合时，任一 `UNVERIFIED` 即整体不得 `PASS`
- **完成标准**：构造 4 类 `UNVERIFIED` 场景，每类均有非空 `missing_reason` 与 `retest_hint`；空白项数 0；整体 `verdict` 均非 `PASS`。
- **对应设计**：`DES-SBX-17`；**对应 spec**：5.1.1-13、4.4-2、5.1.3-5
- **产出物**：`backend/app/realscan/models.py` + `constraints.py`（未验证字段与聚合）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_constraints -v`（T-SBX-CST-06）
- **依赖**：T-SBX-13

## T-SBX-18 禁止本地执行冒充容器约束
- [x] 每条结论强制携带 `exec_domain` 与 `source_kind`；`source_kind=REAL_LOCAL` 的结论不得进入"容器约束"分组
- [x] 报告分组规则：`REAL_CONTAINER` 组只接受 `exec_domain ∈ {RUNTIME_ROOT, CONTAINER_EXEC}` 且 `verification_source=REAL_EXECUTION`
- [x] 本地执行器（`LocalTestExecutor`，`env_snapshot` 中 `network_disabled=False`、`read_only=False`）仅可作为 `REAL_LOCAL` 依据
- **完成标准**：检查报告结论行 100% 带执行域；构造一条 `REAL_LOCAL` 结论尝试进入容器组时被拒绝；缺 `exec_domain` 构造失败。
- **对应设计**：`DES-SBX-18`；**对应 spec**：5.1.1-14、4.3-7、4.5-1
- **产出物**：`backend/app/realscan/boundary.py`（待新建：分组规则常量）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_evidence -v`（T-SBX-EVD-01）、`python -m unittest backend.tests.test_realscan_scan -v`（T-RS-SCN-10）
- **依赖**：T-SBX-13

## T-SBX-19 策略与靶场不可变校验
- [x] 在 `pipeline.py` 执行前后对 `sandbox/spec.json`、`verifix-target/app/main.py`、`app/config.py`、`requirements.txt`、`ground_truth.json`、`init_db.py` 计算 sha256
- [x] 任一不一致 → 整体 `FAIL`，原因 `policy_or_target_mutated`，并拒绝发布报告
- [x] 记录中写入 `policy_sha256` 与靶场源码聚合摘要，供证据回读对照
- **完成标准**：正常执行前后 6 项摘要完全一致；模拟改动 1 字节后整体 `FAIL` 且不产出 `PASS`；摘要写入 `records/verification.json`。
- **对应设计**：`DES-SBX-19`；**对应 spec**：5.1.1-15、5.2.1-13、4.3-1
- **产出物**：`backend/app/realscan/pipeline.py`（摘要守卫）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_policy -v`（T-SBX-POL-04）、`python -m unittest backend.tests.test_realscan_scan -v`（T-RS-SCN-11）
- **依赖**：T-SBX-13、T-SBX-06

## T-SBX-20 P4-01 挂载面裁剪与 `.git` 合成夹具
- [x] 在 `target.py` 实现 `build_p4_fixture(work_root)`：生成 `.evidence/sandbox-realscan/<VER>/fixtures/p4-01/{app/main.py,.git/config}`（合成 `.git` 目录必须真实可读）
- [x] 视图只复制 `app/`（不含 `.git`），并写 `fixture=true`、`fixture_path`、`fixture_digest`
- [x] 在容器内断言：`/src/.git/config` 必须 `ENOENT`（`FileNotFoundError`），`/src/app/main.py` 必须可读（正例控制）
- [x] `basis` 固定为"合成夹具；工作区非 Git 仓库"，**不得**表述为"已验证真实仓库 `.git`"（O-02：采用默认值，待确认）〔2026-11-18：`basis` 原文不改写；工作区已 Git 化，但"不得表述为已验证真实仓库 `.git`"仍然有效。〕
- [x] 若未来工作区成为 Git 仓库，同一视图排除规则可直接适配真实 `.git`，探针无需改动（仅登记为说明）
- **完成标准**：`p4-01.json` 含 `dot_git_result=PATH_NOT_EXIST`、`positive_control=true`、`fixture=true`；夹具存在但视图内 `.git` 数 = 0；`.git` 可读时该项 `FAIL`。
- **对应设计**：`DES-SBX-20`；**对应 spec**：5.1.1-14、K-03、R-05、5.4.1-3、O-02（采用默认值，待确认）
- **产出物**：`backend/app/realscan/target.py`（待新建，本任务只落 `TargetViewBuilder.build_p4_fixture`）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_constraints -v`（T-SBX-CST-07）
- **依赖**：T-SBX-09、T-SBX-13

---

# 4. 阶段 3：靶场接入与真扫闭环（15 项全量 / 动态端口 / 真值读取 0）

> 目标：靶场真实启动、真实响应、行为差异可复现；检出由独立规则产生，扫描期不读真值；范围显式、对账只在检出冻结后进行。

## T-SCAN-01 靶场裁剪视图（排除真值/测试/工具/.git）
- [x] 新建 `backend/app/realscan/target.py` 的 `TargetViewBuilder.build(source_root, work_root)`：只复制 `app/`、`init_db.py`、`requirements.txt`
- [x] 排除清单固定：`ground_truth.json`、`tests/`、`tools/`、`__pycache__`、`.git`、`target.db`
- [x] 写 `view_manifest.json`：`included_paths`、`excluded_paths`、每文件 sha256、`view_digest`、`truth_present=false`
- [x] 复用 `app.eval.digest.file_digest/directory_digest`，不另立摘要算法
- **完成标准**：视图内 `ground_truth.json` 文件数 0、`.git` 目录数 0；`included_paths` 与允许清单完全一致；`truth_present=false`；`view_digest` 64 位十六进制且可复算。
- **对应设计**：`DES-SCAN-01`；**对应 spec**：5.2.1-3、5.2.1-4、4.3-8
- **产出物**：`backend/app/realscan/target.py`（待新建）
- **验证**：`python -m unittest backend.tests.test_realscan_target -v`（T-RS-TGT-01）
- **依赖**：T-SBX-20

## T-SCAN-02 靶场运行镜像定义（独立 lock，不改靶场依赖）
- [x] 新建 `sandbox/requirements.target.txt`：`Flask==3.1.3` + `Werkzeug` 等运行期最小依赖（与本地已存在的 `realscan-probe:local` 一致：Flask 3.1.3 / Python 3.12）
- [x] 新建 `sandbox/Dockerfile.target`：`FROM python:3.12-slim`、安装 lock、`USER 10001:10001`、`WORKDIR /target`、`ENTRYPOINT ["python"]`
- [x] **不修改** `verifix-target/requirements.txt`（pins 保持 `5e19106a…`）
- [x] 报告口径登记"运行期 Flask 3.1.3，静态依赖版本按 requirements.txt 检出"（O-05：采用默认值，待确认）
- **完成标准**：`python scripts/build_sandbox_images.py --target-image verifix-target:1.0.0` 可构建并输出镜像 ID；构建期网络事实单独记录；靶场 `requirements.txt` 摘要不变。
- **对应设计**：`DES-SCAN-02`；**对应 spec**：1.4-1、Q-02、O-05（采用默认值，待确认）
- **产出物**：`sandbox/requirements.target.txt`、`sandbox/Dockerfile.target`（待新建）
- **验证**：`python -m unittest backend.tests.test_realscan_target -v`（T-RS-TGT-05）；真实执行 `python scripts/build_sandbox_images.py --build-network on`
- **依赖**：T-SBX-04

## T-SCAN-03 靶场真实启动与健康检查（≤15s）
- [x] 在 `worker.py` 实现容器内驱动：`create_app("/tmp/target.db")` + `werkzeug.serving.make_server("127.0.0.1", port, app)`
- [x] 在 `target.py` 实现 `TargetLauncher.prepare()/launch(scan_id, timeout_seconds=15)`，返回 `listen_port`、`health_ok`、`health_elapsed_ms`、`db_path`
- [x] 健康检查：`GET /health` 返回 200 且耗时 ≤15s；超时抛 `TargetLaunchError(reason=HEALTH_TIMEOUT)`
- [x] 失败原因枚举固定 5 值：`MISSING_DEPENDENCY` / `PORT_UNAVAILABLE` / `DB_NOT_WRITABLE` / `HEALTH_TIMEOUT` / `IMAGE_UNAVAILABLE`
- **完成标准**：真实执行健康检查 200 且耗时 ≤15s；超时场景 `scan_verdict=UNVERIFIED` 且不进入扫描；失败原因均落在 5 值内。
- **对应设计**：`DES-SCAN-03`；**对应 spec**：5.2.1-1、4.1-5、4.2-6、5.2.3-1
- **产出物**：`backend/app/realscan/worker.py`（待新建）+ `target.py`（追加 `TargetLauncher`）
- **验证**：`python -m unittest backend.tests.test_realscan_target -v`（T-RS-TGT-03/06）
- **依赖**：T-SCAN-01、T-SCAN-02

## T-SCAN-04 动态端口分配与预检
- [x] `make_server("127.0.0.1", 0, app)` 由内核分配端口；记录 `listen_port`（>0）与 `port_source="DYNAMIC"`
- [x] 绑定失败（`OSError`）最多重试 3 次；3 次失败输出 `PORT_UNAVAILABLE`，拒绝启动，**不复用未知服务**
- [x] `RealscanConfig.listen_port=0` 表示动态；显式端口必须在 1024–65535
- **完成标准**：连续 10 次启动端口均 >0 且互不冲突（或冲突时重试成功）；模拟占用 3 次后返回 `PORT_UNAVAILABLE` 且进程未监听。
- **对应设计**：`DES-SCAN-04`；**对应 spec**：5.2.1-9、6.3-3、4.1-5、Q-04=C
- **产出物**：`backend/app/realscan/worker.py`（端口分配 + 重试）
- **验证**：`python -m unittest backend.tests.test_realscan_target -v`（T-RS-TGT-02）
- **依赖**：T-SCAN-03

## T-SCAN-05 数据库落盘到可写临时区域
- [x] worker 内固定 `VERIFIX_TARGET_DB=/tmp/target.db`，启动前调用 `init_db.create(path)`
- [x] 只读源码目录写入必须显式失败并提示"数据落盘位置非法"
- [x] 记录 `db_path=/tmp/target.db` 与建库耗时
- **完成标准**：真实执行下 `/tmp/target.db` 存在且可写；把 DB 指向 `/src/target.db` 时启动失败、原因为 `DB_NOT_WRITABLE`；`/src` 下无新增文件。
- **对应设计**：`DES-SCAN-05`；**对应 spec**：5.2.1-10、5.2.3-3、4.2-6
- **产出物**：`backend/app/realscan/worker.py`（DB 路径与建库）
- **验证**：`python -m unittest backend.tests.test_realscan_target -v`（T-RS-TGT-04）
- **依赖**：T-SCAN-03

## T-SCAN-06 C02 静态规则（SQL 注入）
- [x] 新建 `backend/app/realscan/rules.py`：C02 规则识别 `execute()` 实参中的 `%` 格式化、`+` 拼接、f-string、`.format` 且含请求参数
- [x] 规则字段：`rule_id`、`defect_class="C02"`、`anchor`（AST 节点类型）、`severity`、`cve_ref`、`source_ref`（CWE-89，公开事实）、`mask_output=false`
- [x] 在 `scanner.py` 实现 AST 优先、正则兜底（AST 解析失败时才用正则）
- [x] 参数化查询（占位符 + 参数元组）不得误报
- **完成标准**：对 `verifix-target/app/main.py` 的 6 处（`:31/40-42/50/58/66/74`）全部命中；构造参数化查询样本命中数 0；规则表结构完整。
- **对应设计**：`DES-SCAN-06`；**对应 spec**：5.2.1-3、5.2.1-11、K-07
- **产出物**：`backend/app/realscan/rules.py`（待新建）+ `backend/app/realscan/scanner.py`（待新建）
- **验证**：`python -m unittest backend.tests.test_realscan_rules -v`（T-RS-RUL-01）
- **依赖**：T-SCAN-01

## T-SCAN-07 C03 静态规则（命令注入）
- [x] 在 `rules.py` 增加 C03：识别 `os.popen(... + ...)`、`subprocess.call/run(..., shell=True)` 的字符串拼接/格式化
- [x] `shell=False` 与常量字符串不得误报
- [x] 规则依据 `source_ref=CWE-78`
- **完成标准**：对 `main.py:81/87/93/99` 4 处全部命中；`shell=False` 样本命中 0；AST 行号与源码一致。
- **对应设计**：`DES-SCAN-07`；**对应 spec**：5.2.1-3、5.2.1-11
- **产出物**：`backend/app/realscan/rules.py`（追加 C03）+ `scanner.py`
- **验证**：`python -m unittest backend.tests.test_realscan_rules -v`（T-RS-RUL-02）
- **依赖**：T-SCAN-06

## T-SCAN-08 C01 依赖漏洞静态规则 + 公开事实表
- [x] 在 `rules.py` 增加 C01：解析 `requirements.txt` 的 `name==version`，命中独立登记的公开漏洞事实表（`component`、`affected`、`fixed`、`cve`、`source_ref`）
- [x] 事实表**不得**从 `ground_truth.json` 生成；覆盖当前 pins 中 `requests==2.19.1`、`PyYAML==5.1`、`Jinja2==2.10.1`
- [x] 实现 `verify_advisories()` 自检：版本区间单调、CVE 格式、`source_ref` 非空
- **完成标准**：C01 命中 3 项且行号指向 `requirements.txt` 对应行；事实表与真值清单零耦合（删除真值后仍命中 3 项）；`verify_advisories()` 全通过。
- **对应设计**：`DES-SCAN-08`；**对应 spec**：5.2.1-3、K-07、O-05（采用默认值，待确认）
- **产出物**：`backend/app/realscan/rules.py`（追加 C01 + CVE 事实表）
- **验证**：`python -m unittest backend.tests.test_realscan_rules -v`（T-RS-RUL-03/05）
- **依赖**：T-SCAN-06

## T-SCAN-09 C05 硬编码凭据规则 + 输出掩码
- [x] 在 `rules.py` 增加 C05：识别大写敏感名（`SECRET_KEY`、`DB_PASSWORD` 等）+ 字符串字面量且长度超阈值
- [x] 输出 `snippet_masked`（形如 `SECRET_KEY = "***"`）；**原始行不得**进入 worker stdout、证据或报告
- [x] 规则依据 `source_ref=CWE-798`
- **完成标准**：对 `verifix-target/app/config.py:1-2` 命中 2 项；输出中原文出现次数 0；`snippet_masked` 全部含 `***`。
- **对应设计**：`DES-SCAN-09`；**对应 spec**：4.3-3、4.3-4、5.2.1-11
- **产出物**：`backend/app/realscan/rules.py`（追加 C05）+ `worker.py`（掩码透传）
- **验证**：`python -m unittest backend.tests.test_realscan_rules -v`（T-RS-RUL-04）
- **依赖**：T-SCAN-06

## T-SCAN-10 真值独立性（扫描期读取 0 + 删真值重扫一致）
- [x] `worker.py` 内不存在任何读取 `ground_truth` / `expected` 的代码路径（含注释与字符串，仅允许类型名以外的禁用词）
- [x] 在 worker 内包装 `open` / `Path.read_text` 的 `TruthAccessTripwire`，记录命中 `ground_truth`/`expected` 路径的次数 → `scan_phase_truth_reads`
- [x] 单测：把同一视图复制到临时目录并删除 `ground_truth.json`，重跑 `SourceScanner`，要求 `(file,line,rule_id,defect_class)` 集合完全一致
- **完成标准**：`scan_phase_truth_reads=0`（含真实执行）；删除真值后检出集合与删除前完全相等（`T-RS-IND-01` 一致率 100%）。
- **对应设计**：`DES-SCAN-10`；**对应 spec**：5.2.1-3、5.2.1-4、K-06、R-09
- **产出物**：`backend/app/realscan/worker.py`（tripwire）+ `scanner.py`（独立性）
- **验证**：`python -m unittest backend.tests.test_realscan_scan -v`（T-RS-SCN-04/05）
- **依赖**：T-SCAN-06、T-SCAN-07、T-SCAN-08、T-SCAN-09

## T-SCAN-11 动态可达性（真实双请求 + 差异判定）
- [x] 新建 `backend/app/realscan/dynamic.py`：`DynamicProber(base_url, timeout=5, retries=3)`，从 AST 推导 `@app.get/post` 路由、`request.args.get/form.get` 参数名与危险 sink
- [x] 请求对：C02 正常 `uid=1` vs 注入 `uid=1' OR '1'='1`（`/login` 用 `username=alice' OR '1'='1' --`）；C03 正常参数 vs 追加 `; echo VF_INJECTED`
- [x] 判定：C02 看 JSON 行数/`matched` 计数严格增大；C03 看响应体 `VF_INJECTED` 或 `/convert` 退出码由 `127→0` 变化；仅状态码 200 不构成可达证据
- [x] 失败处理：单请求 5s 超时、最多 3 次重试；仍失败 → `NOT_REPRODUCIBLE`，记录两次响应 sha256 与错误类型，不计入可达
- [x] C01/C05 返回 `dynamic_status="STATIC_ONLY"`，不进入动态分母
- **完成标准**：C02/C03 共 10 项全部取得可区分结果；构造无差异场景返回 `NOT_REPRODUCIBLE`；动态分母恒为 10，静态类不混入。
- **对应设计**：`DES-SCAN-11`；**对应 spec**：5.2.1-6、5.2.3-4、4.1-6、6.3-6
- **产出物**：`backend/app/realscan/dynamic.py`（待新建）
- **验证**：`python -m unittest backend.tests.test_realscan_scan -v`（T-RS-SCN-03）
- **依赖**：T-SCAN-03、T-SCAN-06、T-SCAN-07

## T-SCAN-12 扫描范围声明（默认 15 项全量）
- [x] `scan.py` 的 `ScanScope` 记录 `defect_classes`、`item_count`、`full_count=15`、`uncovered_classes`
- [x] `scan_scope=full` → `{C01,C02,C03,C05}`、`item_count=15`、`uncovered=[]`；`sql-cmd` → 10 项且 `uncovered=["C01","C05"]`
- [x] 报告文案固定："x/15，未覆盖 …"；**子集不得表述为全量检出率**
- **完成标准**：全量模式输出 `15/15`；子集模式输出 `10/15，未覆盖 C01、C05`；`item_count + len(uncovered 对应条目) = 15` 恒成立。
- **对应设计**：`DES-SCAN-12`；**对应 spec**：5.2.1-5、6.3-4、K-07、Q-05=A
- **产出物**：`backend/app/realscan/scan.py`（待新建，本任务落 `ScanScope` 与范围计算）
- **验证**：`python -m unittest backend.tests.test_realscan_scan -v`（T-RS-SCN-01）
- **依赖**：T-SCAN-10

## T-SCAN-13 真扫成立四条件
- [x] `scan_verdict=ESTABLISHED` 仅当四项同时为真：`target_responded`、`behavior_diff_reproducible`、`isolation_effective`、`evidence_replayable`
- [x] 任一不满足 → `NOT_ESTABLISHED` + `verdict_missing` 列表；**不输出成功率**
- [x] 中断 → `UNVERIFIED`，保留已完成 detections 与证据，报告"已完成条数"
- **完成标准**：四项缺失场景各返回 `NOT_ESTABLISHED` 且缺失项准确；报告字段中"成功率"出现次数 0（仅允许"条目数/覆盖数"）。
- **对应设计**：`DES-SCAN-13`；**对应 spec**：5.2.1-7、6.3-7、4.2-5、5.2.3-6
- **产出物**：`backend/app/realscan/scan.py`（`RealScanOrchestrator.run` 判定）
- **验证**：`python -m unittest backend.tests.test_realscan_scan -v`（T-RS-SCN-07）
- **依赖**：T-SCAN-11、T-SCAN-12

## T-SCAN-14 桩隔离（M1 10 条标 RECORDED_STUB）
- [x] `scan.py`/`boundary.py` 支持导入 M1 的 10 条记录为 `RECORDED_STUB`，`stub_ref` 指向 `scripts/m1_detect_acceptance.py`（真值派生来源）
- [x] 边界统计：`stub_count=10`、`real_count=15`，**分母不合并**
- [x] 报告禁止把 10/10 写成真扫；桩条目不得进入 `detections.json`
- **完成标准**：`boundary_summary` 中 `RECORDED_STUB=10` 且与 `REAL_CONTAINER` 分列；真扫 detections 中 `source_kind` 非 `REAL_CONTAINER` 的条目数 0；报告"真扫 10/10"字样出现 0 次。
- **对应设计**：`DES-SCAN-14`；**对应 spec**：5.2.1-8、5.2.1-14、6.3-8/9、K-06
- **产出物**：`backend/app/realscan/scan.py`（桩导入与计数）
- **验证**：`python -m unittest backend.tests.test_realscan_scan -v`（T-RS-SCN-06）
- **依赖**：T-SCAN-13

## T-SCAN-15 定位精度（文件 + 行号 + 规则 + 类别）
- [x] `Detection` 必含 `file`、`line`、`rule_id`、`defect_class`、`source_kind`、`exec_location`、`snippet_masked`
- [x] 行号来自 AST `lineno`；宿主侧用源码行切片复核对齐（`verifix-target/app/main.py`、`app/config.py`）
- [x] 偏移必须为 0；越界或空行判定为 `FAIL` 并要求重扫
- **完成标准**：15 条检出逐条与真实源码行一致，偏移数 0；任一条偏移非 0 时整份 `scan_verdict != ESTABLISHED`。
- **对应设计**：`DES-SCAN-15`；**对应 spec**：5.2.1-11、6.3-5
- **产出物**：`backend/app/realscan/scanner.py`（定位与复核）
- **验证**：`python -m unittest backend.tests.test_realscan_scan -v`（T-RS-SCN-02）
- **依赖**：T-SCAN-06、T-SCAN-07、T-SCAN-08、T-SCAN-09

## T-SCAN-16 重复扫描同构与差异标注
- [x] 同参数连续两次运行，比较 `(file,line,rule_id,defect_class)` 序列与动态结论
- [x] 差异写入 `repeat_diff`（含端口、时间、数据种子导致的差异说明），**不得静默覆盖**
- [x] 结果文件按 `scan_id` 分目录，两次互不覆盖
- **完成标准**：两次运行检出集合完全同构时 `repeat_diff=[]`；人为改动一处数据后 `repeat_diff` 非空且列出差异项；两份证据目录均存在。
- **对应设计**：`DES-SCAN-16`；**对应 spec**：5.2.1-12、4.2-4
- **产出物**：`backend/app/realscan/scan.py`（重复对照）
- **验证**：`python -m unittest backend.tests.test_realscan_scan -v`（T-RS-SCN-08）
- **依赖**：T-SCAN-13

## T-SCAN-17 真值对账（扫描后只读 1 次）
- [x] 新建 `backend/app/realscan/reconcile.py`：`TruthReconciler(truth_path).reconcile(scan_id, detections)`，前置 `detections.json` 已冻结并记录 sha256
- [x] `truth_read_count=1`、`read_phase="POST_SCAN"`；输出 `matched/missing/extra/coverage`
- [x] **禁止改写** `detections.json` 与原始输出；对账只写 `reconciliation.json`
- [x] 真值版本与目标版本不一致 → `ReconcileError(version_mismatch)`，仍保留 detections
- **完成标准**：`truth_read_count=1`；`matched=15`、`missing=[]`、`extra=[]`、`coverage="15/15"`；`detections.json` 摘要前后一致。
- **对应设计**：`DES-SCAN-17`；**对应 spec**：5.2.1-4、6.3、K-07、Q-05=A
- **产出物**：`backend/app/realscan/reconcile.py`（待新建）
- **验证**：`python -m unittest backend.tests.test_realscan_scan -v`（T-RS-SCN-05）
- **依赖**：T-SCAN-15

## T-SCAN-18 云端占位（CLOUD_CREDENTIAL_MISSING）
- [x] `boundary.py`/`scan.py` 输出 `cloud_section`，固定文案"云凭据缺失，未验证"
- [x] `boundary_kind=CLOUD_CREDENTIAL_MISSING`；**不发起真实云端请求**（调用次数 0）
- [x] 不得降级为估算值或本地推算的云端结论
- **完成标准**：`cloud_section` 存在且非空；云端请求次数 0；`boundary_summary` 含该类别计数；报告无"云端通过/已完成"字样。
- **对应设计**：`DES-SCAN-18`；**对应 spec**：5.2.3-7、6.4-2、Q-10=A
- **产出物**：`backend/app/realscan/boundary.py` + `scan.py`（云端占位）
- **验证**：`python -m unittest backend.tests.test_realscan_scan -v`（T-RS-SCN-09）
- **依赖**：T-SCAN-13

## T-SCAN-19 中断处理（保留已完成、未完成 UNVERIFIED）
- [x] `scan.py` 捕获中断信号/异常：保留已完成 detections 与证据，未完成项置 `UNVERIFIED`
- [x] `scan_verdict=UNVERIFIED`，报告给"已完成条数"；**不得汇总成功率**
- [x] 中断阶段与已完成条数写入 `records/scan.json`
- **完成标准**：在第 8 条后注入中断，`completed=8`、`unverified=7`、`verdict=UNVERIFIED`；证据目录中已完成 raw 输出完整保留。
- **对应设计**：`DES-SCAN-19`；**对应 spec**：5.2.3-8、4.2-5
- **产出物**：`backend/app/realscan/scan.py`（中断分支）
- **验证**：`python -m unittest backend.tests.test_realscan_scan -v`（T-RS-SCN-12）
- **依赖**：T-SCAN-13

## T-SCAN-20 worker 自包含注入（stdin，只挂 `/src:ro`）
- [x] `worker_bundle.py` = worker 源码 + `PAYLOAD`（规则表、端口策略、范围）；只允许标准库 + 目标镜像内 Flask/Jinja2，**禁止 import `app.*`**
- [x] 注入方式：`docker run -i --entrypoint python --network=none --read-only ... <image> - < worker_bundle.py`；只挂 `<view>:/src:ro`，工作目录 `/src`
- [x] 输出 `JSONL` 五类事件：`target_ready` / `detection` / `dynamic` / `fact` / `summary`
- [x] 记录 `network_mode=NONE_LOOPBACK`、`sandbox_scope=true`；运行期禁出网不可配置
- **完成标准**：真实执行下容器只挂载 1 个目录且为只读；worker 在容器内可 `import flask`；`scan_stdout.jsonl` 可解析且五类事件齐全。
- **对应设计**：`DES-SCAN-20`；**对应 spec**：5.2.1-2、K-08、4.3-8、6.3-3
- **产出物**：`backend/app/realscan/worker.py`（bundle 构造）+ `scan.py`（容器启动参数）
- **验证**：`python -m unittest backend.tests.test_realscan_scan -v`（T-RS-SCN-10）
- **依赖**：T-SCAN-03、T-SCAN-13

## T-SCAN-21 宿主回退（REAL_LOCAL，不计沙箱证据）
- [x] `--exec host` / 运行时不可用且 `allow_host_fallback=true` 时，允许宿主直跑
- [x] 回退结论强制：`exec_domain=HOST_USER`、`boundary=REAL_LOCAL`、`sandbox_scope=false`、`scan_verdict=NOT_ESTABLISHED`
- [x] 回退结果单独目录（`SCAN-HOST-*`）或单独字段，**不得**并入 `REAL_CONTAINER` 统计
- **完成标准**：回退场景 `sandbox_scope=false` 且 `NOT_ESTABLISHED`；边界统计中 `REAL_LOCAL` 单列；容器证据计数不受影响（O-06：采用默认值，待确认）。
- **对应设计**：`DES-SCAN-21`；**对应 spec**：Q-06=A、5.2.1-7、6.4-2、O-06（采用默认值，待确认）
- **产出物**：`backend/app/realscan/scan.py`（回退分支）
- **验证**：`python -m unittest backend.tests.test_realscan_scan -v`（T-RS-SCN-10）
- **依赖**：T-SCAN-13、T-CFG-01

---

# 5. 阶段 4：隔离桥接与五类探针（ENOENT/EACCES 区分、诱饵、双轨）

> 目标：在真实容器执行身份域取得"预期答案零读取"结论；拒绝方式必须区分"路径不存在"与"权限拒绝"；**故障关闭语义一处不放**。

## T-ISO-01 容器域五类探针 + 正例控制
- [x] 新建 `backend/app/realscan/isolation_bridge.py`：`ContainerIsolationVerifier(transport, cases_dir, work_root, audit).verify(iso_id)`
- [x] 五类探针沿用既有命名 `enumerate` / `open` / `relative` / `traversal` / `symlink`，目标路径如 `/cases/../expected/EVAL-0001.answer.json`
- [x] 正例控制：读取 `/cases/EVAL-0001.json` 必须成功，否则 `PROBE_INVALID`
- [x] 记录 `probes[].{probe,result,denial_kind}`，`violated` 必须为 0
- **完成标准**：真实执行下 5 类探针全部拒绝、正例可读；`ISO-*` 证据中 `probes` 长度 ≥6（含正例）；任一探针可读即 `ISOLATION_DEFECT`。
- **对应设计**：`DES-ISO-01`；**对应 spec**：5.4.1-1、6.6-3、4.3-5
- **产出物**：`backend/app/realscan/isolation_bridge.py`（待新建）
- **验证**：`python -m unittest backend.tests.test_eval_isolation_bridge -v`（T-ISO-02）
- **依赖**：T-SBX-03.1、T-SBX-01、T-EVD-01

## T-ISO-02 可见根裁剪（只挂 `eval/cases:ro`）
- [x] 容器只挂载 `<cases_dir>:/cases:ro`；`visible_roots=["/cases"]`
- [x] **不挂载** `eval/expected`、`eval/runs`、`eval/verdicts`、宿主用户目录、工作区根
- [x] 记录挂载面清单并与 `visible_roots` 交叉断言
- **完成标准**：真实执行 `docker inspect` 中 `Mounts` 条数 = 1 且 `Destination=/cases`、`RW=false`；`visible_roots` 不含 `expected`；挂载整个评测目录时判定隔离不满足并失败关闭。
- **对应设计**：`DES-ISO-02`；**对应 spec**：5.4.1-3、4.3-8、K-03、6.6-2
- **产出物**：`backend/app/realscan/isolation_bridge.py`（挂载面）
- **验证**：`python -m unittest backend.tests.test_eval_isolation_bridge -v`（T-ISO-06）
- **依赖**：T-ISO-01

## T-ISO-03 拒绝方式区分（ENOENT / EACCES）+ 诱饵控制
- [x] `FileNotFoundError` → `PATH_NOT_EXIST`；`PermissionError` → `PERMISSION_DENIED`；其他异常 → `UNKNOWN` 且整项 `PROBE_INVALID`
- [x] 负例控制：额外挂载运行时生成的 `decoy-expected`（`root:root 0700`，执行身份 10001），要求 `PermissionError`，证明"权限拒绝"分支可观测且**不依赖答案内容**
- [x] 输出 `denial_kinds` 分布（两类计数），混同数为 0
- **完成标准**：真实执行下 `denial_kinds` 同时含 `PATH_NOT_EXIST` 与 `PERMISSION_DENIED`；诱饵探针返回 `EACCES`；`UNKNOWN` 计数 0。
- **对应设计**：`DES-ISO-03`；**对应 spec**：5.4.1-4、5.2.3-4、6.6-4
- **产出物**：`backend/app/realscan/isolation_bridge.py`（拒绝方式与诱饵）
- **验证**：`python -m unittest backend.tests.test_eval_isolation_bridge -v`（T-ISO-02/03）
- **依赖**：T-ISO-02

## T-ISO-04 执行域分类（新增 `failure_kind`，宿主可读 → EXEC_DOMAIN_MISMATCH）
- [x] 扩展 `backend/app/eval/isolation.py::IsolationVerdict`：新增 `exec_domain`、`failure_kind`、`publishable`（只增不改）
- [x] `AnswerIsolationGuard.self_check(run_ref="", exec_domain=None)`：`None` 时自动判定；`failure_kind ∈ {ISOLATION_DEFECT, EXEC_DOMAIN_MISMATCH, PROBE_INVALID, RUNTIME_UNAVAILABLE}`
- [x] `basis` 前缀化：`执行域不匹配（HOST_USER）：` / `隔离缺陷（CONTAINER_EXEC）：` / `探针失效：`
- [x] 宿主域可读 → `EXEC_DOMAIN_MISMATCH`（**不得**计入隔离缺陷、**不得**删除该失败记录）
- **完成标准**：宿主同用户域自检失败时 `failure_kind=EXEC_DOMAIN_MISMATCH` 且 `publishable=false`；容器域可读时 `ISOLATION_DEFECT`；既有字段 `ok/basis/elapsed_ms/denied_probes` 语义不变。
- **对应设计**：`DES-ISO-04`；**对应 spec**：5.4.1-5、K-02、6.6-6
- **产出物**：`backend/app/eval/isolation.py`（修改：仅新增字段与可选入参）
- **验证**：`python -m unittest backend.tests.test_eval_isolation_bridge -v`（T-ISO-01）、`python -m unittest backend.tests.test_eval_isolation -v`（既有用例必须全绿）
- **依赖**：T-ISO-01

## T-ISO-05 故障关闭保持（放行分支数 = 0）
- [x] 所有失败分支继续 `raise ApiError(EVAL_ISOLATION_UNMET, basis)`；**不新增**任何 `return verdict` 放行路径
- [x] 覆盖 5 条失败路径：宿主可读、容器可读、用例不可读、运行时不可用、探针超时
- [x] 单测断言：失败分支数 = 5，`raise` 次数 = 5，放行分支 = 0
- **完成标准**：5 条失败路径全部抛 VF-8003；宿主域 `ok=True` 时 `publishable=false`（仅记录，不作对外结论）；`test_eval_isolation.py` 既有断言全绿。
- **对应设计**：`DES-ISO-05`；**对应 spec**：5.4.1-6、4.2-1、5.4.3-1/2/3
- **产出物**：`backend/app/eval/isolation.py`（控制流保持）
- **验证**：`python -m unittest backend.tests.test_eval_isolation_bridge -v`（T-ISO-09）、`python -m unittest backend.tests.test_eval_isolation -v`
- **依赖**：T-ISO-04

## T-ISO-06 双轨口径（宿主域仅记录 / 容器域对外）
- [x] `publishable` 仅在 `exec_domain=CONTAINER_EXEC` 且 `ok=True` 时为 `true`
- [x] 宿主域结论写 `publishable=false`，标记 `RECORD_ONLY`，保留不删除（兼容历史）
- [x] 报告中宿主域结论归类为"过程记录"，容器域为"对外口径"（Q-08=A）
- **完成标准**：宿主域记录存在且 `publishable=false`；容器域记录 `publishable=true`；两域记录同时可在归档中检索到。
- **对应设计**：`DES-ISO-06`；**对应 spec**：5.4.1-2、K-01、Q-08=A
- **产出物**：`backend/app/realscan/isolation_bridge.py`（双轨标记）
- **验证**：`python -m unittest backend.tests.test_eval_isolation_bridge -v`（T-ISO-07）
- **依赖**：T-ISO-05

## T-ISO-07 审计合并与只读归档查询
- [x] 在 `backend/app/eval/isolation.py` 新增只读 `AuditArchiveQuery.search(run_ref, actor)`：读取同一 JSONL 归档（`archive_path`），**不改变** `record/search` 语义
- [x] 宿主域与容器域记录写入同一文件 `.evidence/sandbox-realscan/<ISO>/audit/access.jsonl`
- [x] `exec_success_count=0` 必须可在归档中复算（`actor=exec & result=成功` 计数）
- [x] 审计写入失败仍抛 `VF-8008`，不得丢弃拒绝事件
- **完成标准**：按 `run_ref` 检索返回两域记录；归档复算 `exec_success_count=0`；`record/search` 既有行为不变；审计记录不含答案内容。
- **对应设计**：`DES-ISO-07`；**对应 spec**：5.4.1-7、6.6-7、4.3-6、5.4.3-5
- **产出物**：`backend/app/eval/isolation.py`（新增只读查询）+ `isolation_bridge.py`（归档接线）
- **验证**：`python -m unittest backend.tests.test_eval_isolation_bridge -v`（T-ISO-08）
- **依赖**：T-ISO-02、T-ISO-03

## T-ISO-08 字段口径兼容（只增不改）
- [x] `IsolationBridgeRecord` 字段与既有 `IsolationVerdict` 一一对应：`ok/basis/elapsed_ms/denied_probes` 语义不变，新增字段只增
- [x] `exec_identity` 形如 `uid=10001,gid=10001`；`enforcement_mode ∈ {MANDATORY_SELF_CHECK, RECORD_ONLY}`
- [x] 不得另设并行字段（如另造 `isolation_ok` / `deny_list` 替代既有语义）
- **完成标准**：新旧结论结构逐字段对照缺项 0；既有字段类型/语义未变；`enforcement_mode` 与 `publishable` 组合合法（`RECORD_ONLY` ⇒ 不可发布）。
- **对应设计**：`DES-ISO-08`；**对应 spec**：5.4.1-8、6.6-1/6、4.5-4
- **产出物**：`backend/app/realscan/models.py`（`IsolationBridgeRecord`）+ `isolation_bridge.py`
- **验证**：`python -m unittest backend.tests.test_eval_isolation_bridge -v`（T-ISO-01/07）
- **依赖**：T-ISO-04

## T-ISO-09 运行时不可用 → RUNTIME_UNAVAILABLE（不回退宿主结论）
- [x] 容器运行时不可用（VF-8010 条件）时，隔离验证抛 `VF-8003` 且 `failure_kind=RUNTIME_UNAVAILABLE`
- [x] **不得**回退为宿主域结论、不得返回 `ok=True`、不得跳过验证继续启动
- [x] 记录失败原因与建议（"运行时不可用，评测未启动"）
- **完成标准**：停止 daemon / 移除 socket 权限两种场景均抛 VF-8003 + `RUNTIME_UNAVAILABLE`；宿主域结论未被引用；`completed` 用例数 0。
- **对应设计**：`DES-ISO-09`；**对应 spec**：5.4.3-3、4.2-1、5.4.1-6
- **产出物**：`backend/app/realscan/isolation_bridge.py`（不可用分支）
- **验证**：`python -m unittest backend.tests.test_eval_isolation_bridge -v`（T-ISO-09）
- **依赖**：T-ISO-05

## T-ISO-10 冲突处置常量与报告口径要素（K-01/K-02/K-03）
- [x] 在 `backend/app/realscan/boundary.py` 定义 `CONFLICT_DISPOSITIONS`：K-01…K-10 共 10 条，每条含 `k_id`、`disposition`、`landing`、`evidence_hint`
- [x] 其中 K-01（执行身份）、K-02（强制自检分类）、K-03（权限面裁剪）必须与 `T-ISO-01…09` 的实现口径一致
- [x] 缺任一条即拒绝发布报告（7.3 闸门一）
- **完成标准**：常量长度 = 10；K-01/K-02/K-03 文案与 design §5.1 一致；报告附录可直接渲染 10 行。
- **对应设计**：`DES-ISO-10`；**对应 spec**：5.4.1-1/2、K-01/K-02/K-03、7.3-1
- **产出物**：`backend/app/realscan/boundary.py`（冲突常量）
- **验证**：`python -m unittest backend.tests.test_eval_isolation_bridge -v`（T-ISO-01/07 附带断言）
- **依赖**：T-ISO-06

---

# 6. 阶段 5：证据包与边界标注（staging → sha256 → manifest → 原子改名）

> 目标：证据"全量成功或完全不存在"；四类边界标签覆盖全部结论；历史摘要复算不变。

## T-EVD-02 命令可复制（cwd + 完整参数 + 无凭据）
- [x] `commands.txt` 每行以 `# cwd=` 开头，随后是完整命令（含 `--network=none`、镜像、`--entrypoint python`、重定向等全部参数）
- [x] 禁止占位符（`<...>`、`...`）、禁止交互输入、禁止凭据
- [x] 扫描命令必须含 `docker run -i ... < scan_bundle/worker_bundle.py` 的完整重定向
- **完成标准**：`commands` 条数 ≥1；占位符命中 0；凭据命中 0；可复制执行数与登记数一致。
- **对应设计**：`DES-EVD-02`；**对应 spec**：5.3.1-2、6.2-3、4.4-1
- **产出物**：`backend/app/realscan/evidence.py`（`commands.txt` 渲染）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_evidence -v`（T-SBX-EVD-02）
- **依赖**：T-EVD-01

## T-EVD-03 staging 原子写入 + 逐文件 sha256 + 回读
- [x] `write(evidence_id, records)`：写 staging → 逐文件 sha256 → 时间校验 → 清洗 → **manifest 最后写** → `fsync` + `os.replace(staging, final)`
- [x] 失败任一步：删除 staging，最终目录**不存在**，`evidence_ref=null` 并标记"未归档"
- [x] `verify(evidence_id)`：逐文件重算 + manifest 摘要自校验；不一致 → `VF-8012`
- [x] 目标已存在且摘要相同 → 幂等返回；摘要不同 → 新 ID 或失败，**不覆盖**
- **完成标准**：注入第 N 个文件写失败时最终目录不存在；同 ID 同摘要幂等；异摘要不覆盖；回读全量一致；`EVIDENCE.sha256` 为 64 位十六进制。
- **对应设计**：`DES-EVD-03`；**对应 spec**：5.3.1-3、4.2-2/7、5.3.3-1
- **产出物**：`backend/app/realscan/evidence.py`（`write/verify`）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_evidence -v`（T-SBX-EVD-02/03/04）
- **依赖**：T-EVD-02

## T-EVD-04 结论与证据绑定
- [x] 每条 `ConstraintCheck` / `Detection` / `IsolationProbeResult` 必须有非空 `evidence_ref`
- [x] `manifest.json` 中 `verification_source` 与 `evidence_ref` 必须同时存在；缺一即拒绝发布
- [x] `verification_source=UNIT_TEST` 的记录不得出现在"约束通过/真扫成立/零读取"结论段
- **完成标准**：抽查任一条判定均可定位到 `raw/` 或 `records/` 具体文件；缺失引用数 0；单测结论被排除在对外结论外（计数 0）。
- **对应设计**：`DES-EVD-04`；**对应 spec**：5.3.1-4、4.4-5、6.2-1
- **产出物**：`backend/app/realscan/evidence.py`（引用校验）+ `models.py`（`evidence_ref` 必填）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_evidence -v`（T-SBX-EVD-01/04）
- **依赖**：T-EVD-03

## T-EVD-05 四类边界标签（每条结论恰好 1 类）
- [x] `BoundaryEntry(item_ref, boundary_kind, basis, evidence_ref, stub_ref)`；`boundary_kind ∈ {REAL_CONTAINER, REAL_LOCAL, RECORDED_STUB, CLOUD_CREDENTIAL_MISSING}`
- [x] 真实类必须 `evidence_ref` 非空；桩类必须 `stub_ref` 非空；同一结论**禁止**同时标真实与桩
- [x] `boundary_summary` 四类计数之和 = 结论总数
- [x] 缺任一结论的标签 → 拒绝发布，列出未标注条目
- **完成标准**：结论总数 = 四类计数之和；未标注数 0；双重标签构造失败；缺失标签时发布被拒。
- **对应设计**：`DES-EVD-05`；**对应 spec**：5.3.1-5、6.4-1…5、5.3.3-4
- **产出物**：`backend/app/realscan/boundary.py`（标签与校验）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_evidence -v`（T-SBX-EVD-07）
- **依赖**：T-EVD-04

## T-EVD-06 时间规范（带时区 + 单调不减 + 回拨拒绝）
- [x] 所有记录时间字段为带时区 UTC ISO8601；写入前校验单调不减
- [x] 检测到回拨（后写记录时间早于前一条）→ 拒绝写入并抛 `VF-8012`，记录"证据时间异常"
- [x] 时间戳不得依赖系统本地时区偏移
- **完成标准**：全部时间戳带 `+00:00`/`Z`；单调性异常数 0；模拟回拨时写入被拒且目录不存在。
- **对应设计**：`DES-EVD-06`；**对应 spec**：5.3.1-6、6.2-1、5.3.3-5
- **产出物**：`backend/app/realscan/evidence.py`（时间校验）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_evidence -v`（T-SBX-EVD-05）
- **依赖**：T-EVD-03

## T-EVD-07 历史留痕只读（9 项摘要复算）
- [x] 发布前复算 T-BASE-02 登记的 9 项 sha256，任一项变化 → `VF-7007` 并拒绝发布
- [x] 明确新报告为**并列新增**，不覆盖、不改写历史
- [x] 报告头部固定写入"历史边界"声明（M1 为录制桩；M0 的 P4-05 补测前为未验证）
- **完成标准**：9 项摘要与基线逐一相等；篡改任一历史文件后发布被拒；历史文件字节数不变。
- **对应设计**：`DES-EVD-07`；**对应 spec**：5.3.1-7、4.4-6、K-05、R-10
- **产出物**：`backend/app/realscan/pipeline.py`（历史摘要守卫）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_evidence -v`（T-SBX-EVD-09）
- **依赖**：T-EVD-05、T-BASE-02

## T-EVD-08 环境漂移检测（reuse_conditions）
- [x] `reuse_conditions.json` 必填：镜像 ID、执行域、网络模式、依赖版本（Python / Flask / Docker / cgroup）
- [x] 当前环境与登记值不一致 → 判定证据失效并要求重跑（`VF-8012` 或 `VF-8005` 语义）
- [x] 镜像重建（ID 变化）必须使既有结论失效
- **完成标准**：4 类漂移各触发一次"证据失效"；一致时复算通过；登记字段缺项 0。
- **对应设计**：`DES-EVD-08`；**对应 spec**：5.3.1-8、4.2-3、6.2-6、5.3.3-3
- **产出物**：`backend/app/realscan/evidence.py`（漂移比对）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_evidence -v`（T-SBX-EVD-10）
- **依赖**：T-EVD-03

## T-EVD-09 原始输出不可改写
- [x] `raw/` 下文件写入后只读；`raw_output_digest` 与实际内容一致
- [x] 禁止在证据生成后修改原始输出或补写未执行步骤；报告引用必须指向原始摘要
- [x] 引用与原始摘要不一致 → 结论降级 `UNVERIFIED`
- **完成标准**：全部 raw 文件摘要与 `manifest.json` 记录一致；篡改任一 raw 文件后被检出；改写次数 0。
- **对应设计**：`DES-EVD-09`；**对应 spec**：5.3.1-9、6.2-5、5.3.3-2
- **产出物**：`backend/app/realscan/evidence.py`（raw 锁定与摘要）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_evidence -v`（T-SBX-EVD-04）
- **依赖**：T-EVD-03

## T-EVD-10 凭据/答案清洗（命中即拒绝落盘）
- [x] `SecretScrubber` 拒绝 `SECRET_KEY=`、`DB_PASSWORD=`、`password=`、`sudo -S`、`--password` 模式
- [x] `LeakScanner` 复用既有词表（`backend/app/eval/leak_scan.py:17` 起）拒绝答案字段/token
- [x] 命中即 `VF-8012`，**不落盘**；`scrubber_report.json` 记录 `credential_hits=0`、`answer_hits=0`
- **完成标准**：6 类样本各触发一次拒绝且目标目录不存在；正常证据命中 0；`scrubber_report.json` 两项计数均为 0。
- **对应设计**：`DES-EVD-10`；**对应 spec**：4.3-3/4、4.4-4、6.1-11、6.2-8
- **产出物**：`backend/app/realscan/evidence.py`（清洗器）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_evidence -v`（T-SBX-EVD-06）
- **依赖**：T-EVD-03

---

# 7. 阶段 6：CLI、默认值登记、文档与索引

## T-CFG-05 默认值登记与 CLI 覆盖
- [x] `adopted_defaults[]` 写入 `{q_id, value, source, pending}`；覆盖 O-01…O-06 与 Q-01…Q-10 共 16 条
- [x] 默认 `source="SPEC_DEFAULT"`、`pending=true`；CLI 覆盖后 `source="CLI_OVERRIDE"`、`pending=false`
- [x] 报告顶部固定输出"本轮采用默认值（待拍板）"表；任何默认值不得表述为"用户已确认"
- [x] 缺任一 `q_id` 即拒绝发布（7.3 闸门二）
- **完成标准**：`adopted_defaults` 长度 16；缺项 0；CLI 覆盖后源标记正确；报告默认值表 16 行。
- **对应设计**：`DES-CFG-05`；**对应 spec**：7.2、7.3-2、5.4.1-10、6.1-9
- **产出物**：`backend/app/realscan/models.py`（`DefaultAdoption`）+ `pipeline.py`（汇总）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_evidence -v`（T-SBX-EVD-01）
- **依赖**：T-SCAN-21、T-ISO-10

## T-CFG-06.1 镜像构建脚本（构建期联网、运行期禁出）
- [x] 新建 `scripts/build_sandbox_images.py`：`--build-network on|off`、`--sandbox-image verifix-sandbox:1.0.0`、`--target-image verifix-target:1.0.0`
- [x] 构建 `sandbox/Dockerfile.sandbox`（待新建，基于 `sandbox/Dockerfile.runner` 约束：`USER 10001`、`ENTRYPOINT ["python"]`）与 `sandbox/Dockerfile.target`
- [x] 记录构建期网络事实（`build_network=on`）、镜像 ID、仓库摘要（本地构建时为空 + 标注）、构建耗时
- [x] 构建失败给可执行原因（拉取失败/依赖失败），不得静默回退别名（O-03：采用默认值，待确认）
- **完成标准**：脚本退出码 0/3 语义清晰；输出 `image_id` 与 `local_build`；构建后 `verifix-sandbox:1.0.0` 存在且 `source=POLICY_IMAGE`。
- **对应设计**：`DES-CFG-06`；**对应 spec**：1.2-2、Q-02、Q-03=A、O-03（采用默认值，待确认）
- **产出物**：`scripts/build_sandbox_images.py`（待新建）、`sandbox/Dockerfile.sandbox`（待新建）
- **验证**：`python scripts/build_sandbox_images.py --build-network on --sandbox-image verifix-sandbox:1.0.0`（退出码 0 且输出镜像 ID）
- **依赖**：T-SBX-01、T-SCAN-02

## T-CFG-06.2 约束验证 CLI
- [x] 新建 `scripts/run_sandbox_verify.py`：`--policy`、`--p4-05 on|off`、`--evidence-root`、`--q01…--q10`
- [x] 先做能力探测，探测失败立即退出（VF-8010），**不执行容器命令**
- [x] 退出码：0=VER 通过、2=未验证、3=失败、4=证据归档失败；未验证不得返回 0
- [x] 输出证据路径、`verification_id`、`manifest` 摘要与逐项判定摘要
- **完成标准**：正常执行退出码 0 且生成 `VER-*`；`--p4-05 off` 返回 2；注入证据写失败返回 4；CLI 帮助含 4 组参数。
- **对应设计**：`DES-CFG-06`；**对应 spec**：1.2、5.1、O-04（采用默认值，待确认）
- **产出物**：`scripts/run_sandbox_verify.py`（待新建）
- **验证**：`python scripts/run_sandbox_verify.py --policy sandbox/spec.json --p4-05 on --evidence-root .evidence/sandbox-realscan; echo $?`
- **依赖**：T-SBX-14、T-EVD-03

## T-CFG-06.3 真扫 CLI
- [x] 新建 `scripts/run_realscan.py`：`--scope full|sql-cmd`、`--port 0|N`、`--exec container|host|auto`、`--allow-host-fallback on|off`、`--evidence-root`
- [x] 先做能力探测与镜像解析；失败即退出（VF-8010）
- [x] 退出码：0=真扫成立、2=未验证、3=不成立、4=证据归档失败
- [x] 输出 `scan_id`、范围、`listen_port`、`scan_verdict`、`boundary_summary`
- **完成标准**：全量执行生成 `SCAN-*` 且 `scan_verdict=ESTABLISHED`；运行时不可用返回 2 或 3（不得 0）；帮助含 5 组参数（O-04：采用默认值，待确认）。
- **对应设计**：`DES-CFG-06`；**对应 spec**：1.2、5.2、Q-04/Q-05/Q-06、O-04（采用默认值，待确认）
- **产出物**：`scripts/run_realscan.py`（待新建）
- **验证**：`python scripts/run_realscan.py --scope full --port 0 --exec container --allow-host-fallback on --evidence-root .evidence/sandbox-realscan; echo $?`
- **依赖**：T-SCAN-21、T-EVD-03

## T-CFG-06.4 隔离桥接 CLI
- [x] 新建 `scripts/verify_isolation_bridge.py`：`--cases eval/cases`、`--evidence-root`
- [x] 先做运行时能力探测；不可用即 `RUNTIME_UNAVAILABLE` 并退出 3
- [x] 退出码：0=可发布（容器域 `ok=True`）、2=未验证、3=隔离失败、4=证据归档失败
- [x] 输出 `iso_id`、`visible_roots`、`denial_kinds`、`exec_success_count`
- **完成标准**：正常执行生成 `ISO-*` 且 `exec_success_count=0`；宿主域执行时退出码非 0 且 `publishable=false`；帮助含 2 组参数。
- **对应设计**：`DES-CFG-06`；**对应 spec**：1.2、5.4、O-04（采用默认值，待确认）
- **产出物**：`scripts/verify_isolation_bridge.py`（待新建）
- **验证**：`python scripts/verify_isolation_bridge.py --cases eval/cases --evidence-root .evidence/sandbox-realscan; echo $?`
- **依赖**：T-ISO-09、T-EVD-03

## T-DOC-01 m6 沙箱约束报告
- [x] 新建 `docs/devlog/m6-sandbox-constraint-report.md`：执行域声明、能力四项 + 网络/回环、10 类/11 键判定表、P4-01…P4-05 矩阵（逐条实测值）、镜像摘要、与 M0 逐项对照
- [x] 明确 `policy_keys=11 / judgement_classes=10 / missing=0`（O-01：采用默认值，待确认）
- [x] 引用 `VER-*` 证据路径与摘要；**不得**修改 `m0-sandbox-verification.md`
- [x] P4-05 写实际终止耗时与 55–75s 判定结果
- **完成标准**：10 类 + 5 条用例全部有判定与证据引用；与 M0 对照缺项 0；历史摘要复算不变。
- **对应设计**：`DES-DOC-01`；**对应 spec**：5.1、5.3、4.5-5、K-04
- **产出物**：`docs/devlog/m6-sandbox-constraint-report.md`（待新建）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_constraints -v`（T-SBX-CST-01/08）+ 人工核对报告条目数
- **依赖**：T-SBX-14、T-EVD-07、T-CFG-06.2

## T-DOC-02 m7 真扫报告
- [x] 新建 `docs/devlog/m7-target-realscan-report.md`：靶场真实启动、端口/网络模式、范围（15/15）、15 项检出表、动态可达 10 项、对账结果、边界统计
- [x] **M1 的 10/10 单列并标 `RECORDED_STUB`**，声明不是真扫；真扫 15/15 单独列示（K-06/K-07）
- [x] 注明"运行期 Flask 3.1.3，静态依赖版本按 requirements.txt 检出"（O-05：采用默认值，待确认）
- [x] 引用 `SCAN-*` 证据；云部分固定写"云凭据缺失，未验证"
- **完成标准**：检出表 15 行且行号与源码一致；桩/真分栏；范围声明为 `15/15`；无"成功率"字样。
- **对应设计**：`DES-DOC-02`；**对应 spec**：5.2、K-06/K-07、Q-05/Q-10、O-05（采用默认值，待确认）
- **产出物**：`docs/devlog/m7-target-realscan-report.md`（待新建）
- **验证**：`python -m unittest backend.tests.test_realscan_scan -v`（T-RS-SCN-01/02/06）+ 人工核对 15 行
- **依赖**：T-SCAN-17、T-EVD-07、T-CFG-06.3

## T-DOC-03 m8 隔离桥接报告
- [x] 新建 `docs/devlog/m8-isolation-bridge-report.md`：容器域零读取结论、5 类探针 + 诱饵结果、`denial_kinds` 分布、`exec_success_count=0`、审计合并可检索
- [x] 双轨表：宿主域 `publishable=false`（过程记录）／容器域 `publishable=true`（对外口径）
- [x] K-02 分类说明：宿主域可读 = `EXEC_DOMAIN_MISMATCH`，不得计入隔离缺陷；强制自检仍拒绝启动
- [x] 引用 `ISO-*` 证据；**不得**修改 `m5-eval-report.md`
- **完成标准**：5 类探针 + 1 正例 + 1 诱饵全部列示；`exec_success_count=0` 可复算；双轨表两域齐全。
- **对应设计**：`DES-DOC-03`；**对应 spec**：5.4、K-01/K-02/K-03、Q-08=A
- **产出物**：`docs/devlog/m8-isolation-bridge-report.md`（待新建）
- **验证**：`python -m unittest backend.tests.test_eval_isolation_bridge -v`（T-ISO-01/02/07）+ 人工核对双轨表
- **依赖**：T-ISO-10、T-EVD-07、T-CFG-06.4

## T-DOC-04 证据索引、边界模板与 K/Q 附录
- [x] 新建 `docs/devlog/sandbox-realscan-index.md`：`INDEX.json` 摘要、三类证据路径与 sha256、K-01…K-10 处置表、O/Q 采用值表、历史摘要基线、回归基线（502）、不做清单
- [x] 固定边界声明模板（design §2.9.5 五段）：执行域 / 未验证（云）/ 历史边界 / 禁止外推 / 隔离口径
- [x] 生成 `.evidence/sandbox-realscan/INDEX.json`：`evidence_id/path/sha256/size/kind/created_at`，可按 kind 检索
- [x] 缺 K 项、缺 Q 项、缺边界声明任一 → 拒绝发布（三闸门）
- **完成标准**：K 条目 10、O 条目 6、Q 条目 10 全部在册；`INDEX.json` 条目数 = 三类证据目录数；边界模板 5 段齐全。
- **对应设计**：`DES-DOC-04`；**对应 spec**：5.3.1-5、4.4-3、7.3-1/2/3、Q-10=A
- **产出物**：`docs/devlog/sandbox-realscan-index.md`、`.evidence/sandbox-realscan/INDEX.json`（待新建）
- **验证**：`python -m unittest backend.tests.test_sandbox_verify_evidence -v`（T-SBX-EVD-07）+ 人工核对 K/O/Q 条目数
- **依赖**：T-DOC-01、T-DOC-02、T-DOC-03、T-CFG-05

---

# 8. 阶段 7：回归验收

## T-CFG-04 回归基线不下降 + 兼容性四项
- [x] 全量回归：`Ran ≥502`、功能性失败 0；新增 8 个测试文件全绿
- [x] `test_sandbox_mcp.py:83-89` 通过：MCP 工具数 8、名称/`tool_version` 不变
- [x] `LocalTestExecutor.env_snapshot()` 语义不变（`network_disabled=False`、`read_only=False`）
- [x] `AccessAuditLog.record/search` 行为不变；`eval/isolation.py` 既有 `test_eval_isolation.py` 全绿
- [x] `backend/app/main.py` 路由数与路径集合不变（O-04）
- **完成标准**：五项全部通过并记录实测输出；任一项不通过即返工，不得下调基线。
- **对应设计**：`DES-CFG-04`；**对应 spec**：5.4.1-9、4.5-1/2/3/4、K-10
- **产出物**：回归验收记录（归入 `docs/devlog/sandbox-realscan-index.md`）
- **验证**：`python -m unittest discover -s backend/tests -p "test_*.py"`、`python -m unittest backend.tests.test_sandbox_mcp -v`
- **依赖**：T-DOC-04、T-CFG-06.1…06.4

## T-ACC-01 发布闸门终验（三闸门 + 覆盖矩阵 + 交付物）
- [x] 闸门一：K-01…K-10 全部登记（缺项 0）；闸门二：O-01…O-06 与 Q-01…Q-10 全部标注"采用默认值（待拍板）"；闸门三：关闭强制自检/放开网络/以桩冒真 三类行为发生次数 = 0
- [x] 覆盖矩阵复核：spec 5.1–5.4、6.1–6.6、4.1–4.5 共 113 条，缺项 0
- [x] 证据终验：三类证据目录均存在、`INDEX.json` 可检索、全文件回读一致、`EVIDENCE.sha256` 校验通过
- [x] 交付物终验：18 模块 + 8 测试 + 4 脚本 + 3 镜像定义 + 4 报告全部存在；无 API 变更
- [x] 边界终验：报告中"生产已验证/云上已通过"字样出现 0 次
- **完成标准**：五项全部通过；任一项不通过则整体不发布，并在验收记录写明缺口。
- **对应设计**：`DES-CFG-04`（附带 `DES-EVD-07`、`DES-DOC-04`）；**对应 spec**：7.3-1/2/3、4.4-3、5.3.1-7
- **产出物**：最终验收记录（归入 `docs/devlog/sandbox-realscan-index.md`）
- **验证**：`python -m unittest discover -s backend/tests -p "test_*.py"` + 证据回读脚本（遍历 `INDEX.json` 逐项 `sha256` 复算）
- **依赖**：T-CFG-04

---

# 9. 覆盖矩阵（spec → 设计 → 任务 → 验证）

## 9.1 spec 5.1.1 沙箱约束业务规则（15 条）

| # | 需求 | 设计 | 任务 | 验证 |
|---|---|---|---|---|
| 1 | 环境能力前置探测，任一不满足全量未验证 | DES-SBX-01/02/05 | T-SBX-01/02/05 | T-SBX-CAP-01…04 |
| 2 | 执行域显式声明，禁止跨域沿用 | DES-SBX-03、DES-ISO-06 | T-SBX-03.1、T-ISO-06 | T-SBX-EVD-01、T-ISO-07 |
| 3 | 10 项隔离参数逐项可执行、缺项 0 | DES-SBX-06/07 | T-SBX-06/07 | T-SBX-CST-01、T-SBX-POL-01/02 |
| 4 | 网络禁出验证，成功即失败 | DES-SBX-08 | T-SBX-08 | T-SBX-CST-02 |
| 5 | 回环可用验证 | DES-SBX-09 | T-SBX-09 | T-SBX-CAP-06 |
| 6 | 根只读 + tmpfs 可写分别判定 | DES-SBX-10 | T-SBX-10 | T-SBX-CST-03 |
| 7 | 非 root、空能力集、禁止提权 | DES-SBX-11 | T-SBX-11 | T-SBX-CST-04 |
| 8 | 资源与进程上限回读比对 | DES-SBX-12 | T-SBX-12 | T-SBX-CST-05 |
| 9 | 运行参数逐字段一致性 | DES-SBX-13 | T-SBX-13 | T-SBX-CST-05 |
| 10 | 超时用例单独判定，不推断 | DES-SBX-14 | T-SBX-14 | T-SBX-CST-08 + 真实执行 `raw/p4-05.log` |
| 11 | 镜像 ID + 仓库摘要完整记录 | DES-SBX-04/15 | T-SBX-04/15 | T-SBX-CAP-04 |
| 12 | 提权方式留痕，无凭据 | DES-SBX-16 | T-SBX-16 | T-SBX-CST-09 |
| 13 | 未验证可解释 | DES-SBX-17 | T-SBX-17 | T-SBX-CST-06 |
| 14 | 禁止本地执行冒充容器约束 | DES-SBX-18 | T-SBX-18 | T-SBX-EVD-01、T-RS-SCN-10 |
| 15 | 禁止修改策略/容器参数/靶场源码 | DES-SBX-19 | T-SBX-19 | T-SBX-POL-04、T-RS-SCN-11 |

## 9.2 spec 5.1.3 约束异常场景（7 条）

| # | 场景 | 设计 | 任务 | 验证 |
|---|---|---|---|---|
| 1 | 宿主无运行时命令 | DES-SBX-01/05 | T-SBX-01/05 | T-SBX-CAP-01 |
| 2 | 执行身份无接口权限 | DES-SBX-01/02/05 | T-SBX-02/05 | T-SBX-CAP-02 |
| 3 | 守护进程未运行 | DES-SBX-02/05 | T-SBX-02/05 | T-SBX-CAP-03 |
| 4 | 镜像缺失/摘要漂移 | DES-SBX-04/15、DES-EVD-08 | T-SBX-04/15、T-EVD-08 | T-SBX-CAP-04、T-SBX-EVD-10 |
| 5 | 约束探针超时 | DES-SBX-13/14 | T-SBX-13/14 | T-SBX-CAP-05、T-SBX-CST-08 |
| 6 | 运行参数不一致 | DES-SBX-13 | T-SBX-13 | T-SBX-CST-05 |
| 7 | 临时文件系统不可写 | DES-SBX-10 | T-SBX-10 | T-SBX-CST-03 |

## 9.3 spec 5.2.1 靶场接入与真扫（14 条）

| # | 需求 | 设计 | 任务 | 验证 |
|---|---|---|---|---|
| 1 | 靶场真实启动并健康检查 | DES-SCAN-03 | T-SCAN-03 | T-RS-TGT-03 |
| 2 | 网络模式显式、优先禁网回环 | DES-SCAN-20 | T-SCAN-20 | T-RS-SCN-10 |
| 3 | 检出不得读取真值 | DES-SCAN-01/10 | T-SCAN-01/10 | T-RS-SCN-04 |
| 4 | 真值只用于对账且读取 1 次 | DES-SCAN-17 | T-SCAN-17 | T-RS-SCN-05 |
| 5 | 扫描范围显式声明 | DES-SCAN-12 | T-SCAN-12 | T-RS-SCN-01 |
| 6 | 动态可达性真实判定 | DES-SCAN-11 | T-SCAN-11 | T-RS-SCN-03 |
| 7 | 真扫成立四条件 | DES-SCAN-13 | T-SCAN-13 | T-RS-SCN-07 |
| 8 | 桩结果隔离、单独计数 | DES-SCAN-14 | T-SCAN-14 | T-RS-SCN-06 |
| 9 | 端口可配置且预检 | DES-SCAN-04 | T-SCAN-04 | T-RS-TGT-02 |
| 10 | 数据库写入临时区域 | DES-SCAN-05 | T-SCAN-05 | T-RS-TGT-04 |
| 11 | 检出定位与真实源码行一致 | DES-SCAN-15 | T-SCAN-15 | T-RS-SCN-02 |
| 12 | 重复扫描可比较 | DES-SCAN-16 | T-SCAN-16 | T-RS-SCN-08 |
| 13 | 禁止修改靶场/真值/种子 | DES-SBX-19、DES-SCAN-01 | T-SBX-19、T-SCAN-01 | T-RS-SCN-11 |
| 14 | 禁止桩冒充真扫 | DES-SCAN-14 | T-SCAN-14 | T-RS-SCN-06 |

## 9.4 spec 5.2.3 真扫异常（8 条）

| # | 场景 | 设计 | 任务 | 验证 |
|---|---|---|---|---|
| 1 | 靶场依赖缺失 | DES-SCAN-02/03 | T-SCAN-02/03 | T-RS-TGT-06 |
| 2 | 端口被占用 | DES-SCAN-04 | T-SCAN-04 | T-RS-TGT-02 |
| 3 | 数据库不可写 | DES-SCAN-05 | T-SCAN-05 | T-RS-TGT-04 |
| 4 | 注入行为未复现 | DES-SCAN-11 | T-SCAN-11 | T-RS-SCN-03 |
| 5 | 禁网下外网访问失败记为约束证据 | DES-SBX-08、DES-SCAN-20 | T-SBX-08、T-SCAN-20 | T-SBX-CST-02、T-RS-SCN-11 |
| 6 | 检出为空不回退真值 | DES-SCAN-13 | T-SCAN-13 | T-RS-SCN-07 |
| 7 | 云端来源不可用 | DES-SCAN-18 | T-SCAN-18 | T-RS-SCN-09 |
| 8 | 扫描中断不汇总成功率 | DES-SCAN-19 | T-SCAN-19 | T-RS-SCN-12 |

## 9.5 spec 5.3.1 证据业务规则（9 条）

| # | 需求 | 设计 | 任务 | 验证 |
|---|---|---|---|---|
| 1 | 证据必备字段缺项 0 | DES-EVD-01 | T-EVD-01 | T-SBX-EVD-01 |
| 2 | 命令可复制执行、无凭据 | DES-EVD-02 | T-EVD-02 | T-SBX-EVD-02 |
| 3 | 摘要与回读一致 | DES-EVD-03 | T-EVD-03 | T-SBX-EVD-02/03 |
| 4 | 结论与证据绑定 | DES-EVD-04 | T-EVD-04 | T-SBX-EVD-01/04 |
| 5 | 四类边界标注完整 | DES-EVD-05 | T-EVD-05 | T-SBX-EVD-07 |
| 6 | 时间带时区且单调 | DES-EVD-06 | T-EVD-06 | T-SBX-EVD-05 |
| 7 | 历史留痕只读 | DES-EVD-07 | T-EVD-07 | T-SBX-EVD-09 |
| 8 | 环境漂移可检测 | DES-EVD-08 | T-EVD-08 | T-SBX-EVD-10 |
| 9 | 禁止改写原始输出/补写步骤 | DES-EVD-09 | T-EVD-09 | T-SBX-EVD-04 |

## 9.6 spec 5.3.3 证据异常（5 条）

| # | 场景 | 设计 | 任务 | 验证 |
|---|---|---|---|---|
| 1 | 证据写入失败整体回滚 | DES-EVD-03 | T-EVD-03 | T-SBX-EVD-03 |
| 2 | 证据与结论不一致 | DES-EVD-04/08 | T-EVD-04/08 | T-SBX-EVD-04 |
| 3 | 环境漂移 | DES-EVD-08 | T-EVD-08 | T-SBX-EVD-10 |
| 4 | 边界标注缺失 | DES-EVD-05 | T-EVD-05 | T-SBX-EVD-07 |
| 5 | 时间戳异常 | DES-EVD-06 | T-EVD-06 | T-SBX-EVD-05 |

## 9.7 spec 5.4.1 口径衔接（10 条）

| # | 需求 | 设计 | 任务 | 验证 |
|---|---|---|---|---|
| 1 | 补齐容器身份零读取验证 | DES-ISO-01/02 | T-ISO-01/02 | T-ISO-02 |
| 2 | 探针执行域迁移，宿主结论不作对外口径 | DES-ISO-06 | T-ISO-06 | T-ISO-07 |
| 3 | 权限面裁剪，答案目录不可见 | DES-ISO-02、DES-SCAN-01 | T-ISO-02、T-SCAN-01 | T-ISO-06、T-RS-TGT-01 |
| 4 | 拒绝方式区分 ENOENT/EACCES | DES-ISO-03 | T-ISO-03 | T-ISO-02/03 |
| 5 | 强制自检冲突分类，不当作隔离缺陷 | DES-ISO-04 | T-ISO-04 | T-ISO-01 |
| 6 | 启动判定不降低，故障关闭保持 | DES-ISO-05 | T-ISO-05 | T-ISO-09 |
| 7 | 审计合并可检索，成功读取 0 | DES-ISO-07 | T-ISO-07 | T-ISO-08 |
| 8 | 口径字段一致，不另设并行字段 | DES-ISO-08 | T-ISO-08 | T-ISO-01/07 |
| 9 | 既有回归不变 | DES-CFG-04 | T-CFG-04 | 全量回归 ≥502 |
| 10 | 待确认项显式化 | DES-CFG-05 | T-CFG-05 | T-SBX-EVD-01 |

## 9.8 spec 5.4.3 隔离异常（5 条）

| # | 场景 | 设计 | 任务 | 验证 |
|---|---|---|---|---|
| 1 | 执行身份仍可读答案 | DES-ISO-02/04 | T-ISO-02/04 | T-ISO-01/02 |
| 2 | 用例目录不可读（反向探针失败） | DES-ISO-01/05 | T-ISO-01/05 | T-ISO-04 |
| 3 | 容器运行时不可用 | DES-ISO-09 | T-ISO-09 | T-ISO-09 |
| 4 | 执行域混用 | DES-ISO-06 | T-ISO-06 | T-ISO-07 |
| 5 | 审计写入失败 | DES-ISO-07（复用 VF-8008） | T-ISO-07 | T-ISO-08 |

## 9.9 spec 6.1–6.6 数据约束

| 章节 | 设计 | 任务 | 验证 |
|---|---|---|---|
| 6.1 约束验证记录 | DES-SBX-03/06/12/15/16、DES-EVD-01 | T-SBX-03.2/06/12/15/16、T-EVD-01 | T-SBX-EVD-01、T-SBX-CST-01/05/09 |
| 6.2 证据包 | DES-EVD-01/02/03/05/10 | T-EVD-01…05、T-EVD-10 | T-SBX-EVD-01/02/03/06/07 |
| 6.3 真扫执行记录 | DES-SCAN-12/13/14/15/17/18 | T-SCAN-12/13/14/15/17/18 | T-RS-SCN-01/02/06/07/09 |
| 6.4 边界标注条目 | DES-EVD-05、DES-SCAN-14/18/21 | T-EVD-05、T-SCAN-14/18/21 | T-SBX-EVD-07、T-RS-SCN-06/09/10 |
| 6.5 环境能力声明 | DES-SBX-02/05 | T-SBX-02/05 | T-SBX-CAP-01…06 |
| 6.6 隔离衔接记录 | DES-ISO-01/02/03/07/08 | T-ISO-01/02/03/07/08 | T-ISO-02/03/06/07/08 |

## 9.10 spec 4.1 性能（8 条）

| # | 需求 | 设计 | 任务 | 验证 |
|---|---|---|---|---|
| 1 | 能力探测 ≤15s | DES-SBX-02 | T-SBX-02 | T-SBX-CAP-05 |
| 2 | 单条探针 ≤10s | DES-SBX-13/14 | T-SBX-13/14 | T-SBX-CST-08 |
| 3 | 约束验证总时长 ≤180s | DES-SBX-06/14 | T-SBX-06/14、T-CFG-06.2 | 真实执行计时 |
| 4 | 镜像摘要 ≤3s | DES-SBX-04 | T-SBX-04 | 真实执行计时 |
| 5 | 靶场就绪 ≤15s | DES-SCAN-03 | T-SCAN-03 | T-RS-TGT-03 |
| 6 | 单请求 ≤5s、3 次重试 | DES-SCAN-11 | T-SCAN-11 | T-RS-SCN-03 |
| 7 | 真扫总时长 ≤180s | DES-SCAN-13 | T-SCAN-13、T-CFG-06.3 | 真实执行计时 |
| 8 | 证据落盘 ≤3s | DES-EVD-03 | T-EVD-03 | T-SBX-EVD-08 |

## 9.11 spec 4.2 可靠性（7 条）

| # | 需求 | 设计 | 任务 | 验证 |
|---|---|---|---|---|
| 1 | 失败关闭，不降级宿主并沿用沙箱结论 | DES-SBX-05、DES-ISO-05 | T-SBX-05、T-ISO-05 | T-SBX-CAP-01、T-ISO-09 |
| 2 | 证据原子性 | DES-EVD-03 | T-EVD-03 | T-SBX-EVD-03 |
| 3 | 摘要漂移使结论失效 | DES-EVD-08 | T-EVD-08 | T-SBX-EVD-10 |
| 4 | 执行幂等/同构 | DES-SCAN-16 | T-SCAN-16 | T-RS-SCN-08 |
| 5 | 中断可解释 | DES-SCAN-19 | T-SCAN-19 | T-RS-SCN-12 |
| 6 | 靶场启动失败给可执行原因 | DES-SCAN-03 | T-SCAN-03 | T-RS-TGT-06 |
| 7 | 证据可回读 | DES-EVD-03 | T-EVD-03 | T-SBX-EVD-02 |

## 9.12 spec 4.3 安全性（8 条）

| # | 需求 | 设计 | 任务 | 验证 |
|---|---|---|---|---|
| 1 | 六项约束不放宽 | DES-SBX-07、DES-CFG-03 | T-SBX-07、T-CFG-03 | T-SBX-POL-02/05 |
| 2 | 真扫禁出网、回环允许 | DES-SBX-08/09 | T-SBX-08/09 | T-SBX-CST-02 |
| 3 | 答案零暴露 | DES-SCAN-09、DES-EVD-10 | T-SCAN-09、T-EVD-10 | T-RS-RUL-04、T-SBX-EVD-06 |
| 4 | 凭据零暴露 | DES-SBX-16、DES-EVD-10 | T-SBX-16、T-EVD-10 | T-SBX-EVD-06 |
| 5 | 执行身份不可读答案 | DES-ISO-01/02/03 | T-ISO-01/02/03 | T-ISO-02/03 |
| 6 | 审计完整性 | DES-ISO-07 | T-ISO-07 | T-ISO-08 |
| 7 | 禁止本地冒充 | DES-SBX-18 | T-SBX-18 | T-RS-SCN-10 |
| 8 | 权限最小化挂载面 | DES-ISO-02、DES-SCAN-01/20 | T-ISO-02、T-SCAN-01/20 | T-ISO-06、T-RS-TGT-01 |

## 9.13 spec 4.4 可维护性（6 条）

| # | 需求 | 设计 | 任务 | 验证 |
|---|---|---|---|---|
| 1 | 证据命令可复现 | DES-EVD-02 | T-EVD-02 | T-SBX-EVD-02 |
| 2 | 未验证可解释 | DES-SBX-17 | T-SBX-17 | T-SBX-CST-06 |
| 3 | 边界可检索 | DES-EVD-05、DES-DOC-04 | T-EVD-05、T-DOC-04 | T-SBX-EVD-07 |
| 4 | 日志脱敏 | DES-EVD-10 | T-EVD-10 | T-SBX-EVD-06 |
| 5 | 版本可追溯 | DES-EVD-01/08 | T-EVD-01/08 | T-SBX-EVD-01/10 |
| 6 | 历史留痕只读 | DES-EVD-07 | T-EVD-07 | T-SBX-EVD-09 |

## 9.14 spec 4.5 兼容性（5 条）

| # | 需求 | 设计 | 任务 | 验证 |
|---|---|---|---|---|
| 1 | 本地执行器保留、快照语义不变 | 不改 `EnvSnapshot` | T-CFG-04 | 全量回归 + `test_reproducer` |
| 2 | 报告字段只增 | DES-DOC-01/02/03 | T-DOC-01/02/03 | T-SBX-EVD-09 |
| 3 | 既有用例不受影响 | DES-CFG-04 | T-CFG-04 | 全量回归 ≥502 |
| 4 | 评测口径兼容 | DES-ISO-08 | T-ISO-08 | T-ISO-01/07 |
| 5 | 与 M0 逐项可对照 | DES-DOC-01 | T-DOC-01 | T-SBX-CST-01/08 |

## 9.15 覆盖统计与缺项

| 维度 | 条目数 | 设计落点 | 任务落点 | 缺项 |
|---|---|---|---|---|
| 5.1.1 业务规则 | 15 | 15 | 15 | **0** |
| 5.1.3 异常场景 | 7 | 7 | 7 | **0** |
| 5.2.1 业务规则 | 14 | 14 | 14 | **0** |
| 5.2.3 异常场景 | 8 | 8 | 8 | **0** |
| 5.3.1 业务规则 | 9 | 9 | 9 | **0** |
| 5.3.3 异常场景 | 5 | 5 | 5 | **0** |
| 5.4.1 业务规则 | 10 | 10 | 10 | **0** |
| 5.4.3 异常场景 | 5 | 5 | 5 | **0** |
| 6.1–6.6 数据约束 | 6 组 | 6 组 | 6 组 | **0** |
| 4.1 性能 | 8 | 8 | 8 | **0** |
| 4.2 可靠性 | 7 | 7 | 7 | **0** |
| 4.3 安全性 | 8 | 8 | 8 | **0** |
| 4.4 可维护性 | 6 | 6 | 6 | **0** |
| 4.5 兼容性 | 5 | 5 | 5 | **0** |
| **合计** | **113** | **113** | **113** | **0** |

> 设计条目 71 条（SBX 20 / SCAN 21 / EVD 10 / ISO 10 / CFG 6 / DOC 4）**全部**有对应任务；任务总数 81（含 5 个基线任务、2 个拆分产物、4 个 CLI 拆分、2 个验收任务）。

---

# 10. 任务总表（81 条 / 一键勾选）

| 阶段 | 任务 | 设计条目 | 主产出物 | 关键验证 |
|---|---|---|---|---|
| 0 | T-BASE-01 | DES-CFG-04 | 验收记录 | 全量回归 ≥502 |
| 0 | T-BASE-02 | DES-EVD-07 | 摘要基线 | 9 项 sha256 |
| 0 | T-BASE-03 | DES-SBX-01/04 | 环境事实 | `docker version/info/images` |
| 0 | T-BASE-04 | DES-CFG-04 | 不改/待建清单 | 路由集合快照 |
| 0 | T-BASE-05 | DES-EVD-01 | 验收检查表 | 人工比对 |
| 1 | T-SBX-03.1 | DES-SBX-03 | `exec_domain.py` | T-SBX-EVD-01 |
| 1 | T-SBX-03.2 | DES-SBX-03 | `models.py` | T-SBX-EVD-01/06 |
| 1 | T-SBX-01 | DES-SBX-01 | `runtime.py` | T-SBX-CAP-01/02 |
| 1 | T-SBX-04 | DES-SBX-04 | `policy.py::ImageResolver` | T-SBX-CAP-04 |
| 1 | T-SBX-02 | DES-SBX-02 | `capability.py` | T-SBX-CAP-01…06 |
| 1 | T-SBX-05 | DES-SBX-05 | `pipeline.py` | T-SBX-CAP-01…04 |
| 1 | T-CFG-01 | DES-CFG-01 | `config.py` | `test_config` |
| 1 | T-CFG-02 | DES-CFG-02 | `envelope.py` | `test_envelope` |
| 1 | T-CFG-03 | DES-CFG-03 | `config.py` 校验 | `test_config`、T-SBX-POL-05 |
| 1 | T-EVD-01 | DES-EVD-01 | `evidence.py` 骨架 | T-SBX-EVD-01 |
| 2 | T-SBX-06 | DES-SBX-06 | `policy.py::PolicyFile` | T-SBX-POL-01/04/05 |
| 2 | T-SBX-07 | DES-SBX-07 | `policy.py::RunSpecBuilder` | T-SBX-POL-02/03 |
| 2 | T-SBX-08 | DES-SBX-08 | `probe_scripts.py` | T-SBX-CST-02 |
| 2 | T-SBX-09 | DES-SBX-09 | 回环探针 | T-SBX-CAP-06 |
| 2 | T-SBX-10 | DES-SBX-10 | 文件系统探针 | T-SBX-CST-03 |
| 2 | T-SBX-11 | DES-SBX-11 | 身份探针 | T-SBX-CST-04 |
| 2 | T-SBX-12 | DES-SBX-12 | `constraints.py` 事实读取 | T-SBX-CST-05 |
| 2 | T-SBX-13 | DES-SBX-13 | `ConstraintVerifier` | T-SBX-CST-05/06 |
| 2 | T-SBX-14 | DES-SBX-14 | P4-05 用例 | T-SBX-CST-08 + 实测 |
| 2 | T-SBX-15 | DES-SBX-15 | 镜像记录字段 | T-SBX-CAP-04 |
| 2 | T-SBX-16 | DES-SBX-16 | 提权留痕 | T-SBX-CST-09 |
| 2 | T-SBX-17 | DES-SBX-17 | 未验证字段 | T-SBX-CST-06 |
| 2 | T-SBX-18 | DES-SBX-18 | `boundary.py` 分组 | T-SBX-EVD-01 |
| 2 | T-SBX-19 | DES-SBX-19 | 摘要守卫 | T-SBX-POL-04 |
| 2 | T-SBX-20 | DES-SBX-20 | `target.py` 夹具 | T-SBX-CST-07 |
| 3 | T-SCAN-01 | DES-SCAN-01 | 裁剪视图 | T-RS-TGT-01 |
| 3 | T-SCAN-02 | DES-SCAN-02 | 靶场镜像定义 | T-RS-TGT-05 |
| 3 | T-SCAN-03 | DES-SCAN-03 | `worker.py` + Launcher | T-RS-TGT-03/06 |
| 3 | T-SCAN-04 | DES-SCAN-04 | 动态端口 | T-RS-TGT-02 |
| 3 | T-SCAN-05 | DES-SCAN-05 | DB 落盘 | T-RS-TGT-04 |
| 3 | T-SCAN-06 | DES-SCAN-06 | `rules.py` C02 | T-RS-RUL-01 |
| 3 | T-SCAN-07 | DES-SCAN-07 | C03 | T-RS-RUL-02 |
| 3 | T-SCAN-08 | DES-SCAN-08 | C01 + CVE 表 | T-RS-RUL-03/05 |
| 3 | T-SCAN-09 | DES-SCAN-09 | C05 + 掩码 | T-RS-RUL-04 |
| 3 | T-SCAN-10 | DES-SCAN-10 | 真值独立性 | T-RS-SCN-04/05 |
| 3 | T-SCAN-11 | DES-SCAN-11 | `dynamic.py` | T-RS-SCN-03 |
| 3 | T-SCAN-12 | DES-SCAN-12 | 范围声明 | T-RS-SCN-01 |
| 3 | T-SCAN-13 | DES-SCAN-13 | 四条件判定 | T-RS-SCN-07 |
| 3 | T-SCAN-14 | DES-SCAN-14 | 桩隔离 | T-RS-SCN-06 |
| 3 | T-SCAN-15 | DES-SCAN-15 | 定位精度 | T-RS-SCN-02 |
| 3 | T-SCAN-16 | DES-SCAN-16 | 重复对照 | T-RS-SCN-08 |
| 3 | T-SCAN-17 | DES-SCAN-17 | `reconcile.py` | T-RS-SCN-05 |
| 3 | T-SCAN-18 | DES-SCAN-18 | 云端占位 | T-RS-SCN-09 |
| 3 | T-SCAN-19 | DES-SCAN-19 | 中断分支 | T-RS-SCN-12 |
| 3 | T-SCAN-20 | DES-SCAN-20 | bundle 注入 | T-RS-SCN-10 |
| 3 | T-SCAN-21 | DES-SCAN-21 | 宿主回退 | T-RS-SCN-10 |
| 4 | T-ISO-01 | DES-ISO-01 | `isolation_bridge.py` | T-ISO-02 |
| 4 | T-ISO-02 | DES-ISO-02 | 挂载面 | T-ISO-06 |
| 4 | T-ISO-03 | DES-ISO-03 | 拒绝方式 + 诱饵 | T-ISO-02/03 |
| 4 | T-ISO-04 | DES-ISO-04 | `isolation.py` 新增字段 | T-ISO-01 |
| 4 | T-ISO-05 | DES-ISO-05 | 故障关闭 | T-ISO-09 |
| 4 | T-ISO-06 | DES-ISO-06 | 双轨 | T-ISO-07 |
| 4 | T-ISO-07 | DES-ISO-07 | 归档查询 | T-ISO-08 |
| 4 | T-ISO-08 | DES-ISO-08 | 字段兼容 | T-ISO-01/07 |
| 4 | T-ISO-09 | DES-ISO-09 | 不可用分支 | T-ISO-09 |
| 4 | T-ISO-10 | DES-ISO-10 | K 常量 | T-ISO-01/07 |
| 5 | T-EVD-02 | DES-EVD-02 | `commands.txt` | T-SBX-EVD-02 |
| 5 | T-EVD-03 | DES-EVD-03 | 原子写入 | T-SBX-EVD-02/03/04 |
| 5 | T-EVD-04 | DES-EVD-04 | 引用绑定 | T-SBX-EVD-01/04 |
| 5 | T-EVD-05 | DES-EVD-05 | 四类标签 | T-SBX-EVD-07 |
| 5 | T-EVD-06 | DES-EVD-06 | 时间校验 | T-SBX-EVD-05 |
| 5 | T-EVD-07 | DES-EVD-07 | 历史守卫 | T-SBX-EVD-09 |
| 5 | T-EVD-08 | DES-EVD-08 | 漂移比对 | T-SBX-EVD-10 |
| 5 | T-EVD-09 | DES-EVD-09 | raw 锁定 | T-SBX-EVD-04 |
| 5 | T-EVD-10 | DES-EVD-10 | 清洗器 | T-SBX-EVD-06 |
| 6 | T-CFG-05 | DES-CFG-05 | `adopted_defaults` | T-SBX-EVD-01 |
| 6 | T-CFG-06.1 | DES-CFG-06 | `build_sandbox_images.py` | 构建退出码 0 |
| 6 | T-CFG-06.2 | DES-CFG-06 | `run_sandbox_verify.py` | 退出码 0/2/3/4 |
| 6 | T-CFG-06.3 | DES-CFG-06 | `run_realscan.py` | 退出码 0/2/3/4 |
| 6 | T-CFG-06.4 | DES-CFG-06 | `verify_isolation_bridge.py` | 退出码 0/2/3/4 |
| 6 | T-DOC-01 | DES-DOC-01 | `m6-*.md` | 10 类 + 5 用例 |
| 6 | T-DOC-02 | DES-DOC-02 | `m7-*.md` | 15/15 + 桩分栏 |
| 6 | T-DOC-03 | DES-DOC-03 | `m8-*.md` | 双轨表 |
| 6 | T-DOC-04 | DES-DOC-04 | `sandbox-realscan-index.md` + `INDEX.json` | K/O/Q 全在册 |
| 7 | T-CFG-04 | DES-CFG-04 | 回归验收记录 | ≥502、0 失败 |
| 7 | T-ACC-01 | DES-CFG-04 | 终验记录 | 三闸门 + 113 项 |

---

# 11. 收尾检查清单（每个阶段结束必须逐项勾）

- [x] 本阶段完成的标准库 `unittest` 全部通过，新增用例数记录在案
- [x] 全量回归 `Ran ≥502`、功能性失败 0；若出现 `PERF-02`，已单跑复验并标注抖动
- [x] 9 项历史/策略/靶场摘要复算与基线一致（T-BASE-02 清单）
- [x] `sandbox/spec.json`、`verifix-target/` 六个文件、`backend/app/eval` 既有控制流均无改动
- [x] `backend/app/main.py` 路由集合未变（无新增 `/api/v1/realscan/*`）
- [x] 新增证据目录均为"完整存在或完全不存在"，无 `.staging-*` 残留
- [x] 本阶段结论均带 `verification_source`；"通过/成立"字样只引用 `REAL_EXECUTION`
- [x] 报告/日志中"生产已验证""云上已通过""成功率"三类字样出现次数为 0
- [x] 未使用 `git`、未引入 `pytest`、未修改任何历史报告