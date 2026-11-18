# 沙箱真扫证据索引与验收记录（sandbox_realscan）

- 生成时间：2026-11-14
- 子项目：`.codeartsdoer/specs/sandbox_realscan/`
- 依据：`spec.md`（v1.0）＋ `design.md`（1892 行）＋ `tasks.md`（1529 行 / 81 任务）
- 结论：代码与三类真实执行均完成；**云上复测未做**，O-01…O-06 仍为"采用默认值，待确认"

## 1. 边界声明模板（固定五段）

1. **执行域**：本轮真实执行在 Windows 11 + WSL2 Debian 13 的 Docker 26.1.5 上完成，`exec_domain=RUNTIME_ROOT`，提权途径仅记录为 `WSL_DISTRO_ROOT`。
2. **未验证（云）**：华为云 CCE / ECS 未接入，无云凭据；所有云端结论一律标注"云凭据缺失，未验证"。
3. **历史边界**：M1 的 10/10 为录制桩派生（`RECORDED_STUB`），不是真扫；`m0-sandbox-verification.md` 中 P4-05 当时未测。
4. **禁止外推**：WSL2 内核与 CCE 节点内核不同，容器参数一致不代表云上结论成立；镜像为本地构建、无仓库摘要。
5. **隔离口径**：容器域结论为对外口径（`publishable=true`）；宿主同用户域仅为过程记录（`publishable=false`），强制自检故障关闭不放松。

## 2. 三类证据与摘要

| 类型 | 证据目录 | 结论 | sha256 | 报告 |
|---|---|---|---|---|
| 约束验证 | `VER-20261114T164934+0800-a691` | PASS（10 类 + 5 条 P4 全 PASS，P4-05 62237ms） | `19ca051998546ff4f11f979fee8d1f6abb77c23cfcd4c4b8b40778d1602e1b71` | `m6-sandbox-constraint-report.md` |
| 靶场真扫 | `SCAN-20261114T164852+0800-9dfe` | ESTABLISHED（15/15，动态 10/10，对账 15/15） | `5268b062a8d992920c5ffefad46d3d89351b5587f8101cb02df745a5fbe4f91d` | `m7-target-realscan-report.md` |
| 隔离桥接 | `ISO-20261114T164822+0800-3c37` | 可发布（5 类探针拒绝，`exec_success_count=0`） | `840d112b34e664c6054e1957b31f1b83f5dbb4baaab2f2877f3b4d8a679a7fed` | `m8-isolation-bridge-report.md` |

- 证据根：`.evidence/sandbox-realscan/`，`INDEX.json` 共 **9** 条记录（含下节列出的历史失败/未验证包，保留不删）。
- 证据包协议：staging → 逐文件 sha256 → `manifest.json` 最后写 → `os.replace` 原子改名；`EVIDENCE.sha256` 可逐文件回读校验。

### 2.1 历史证据（失败/未验证，保留不删）

| 证据 | 结论 | sha256 前缀 | 说明 |
|---|---|---|---|
| `VER-20261114T122909+0800-31af` | UNVERIFIED | `58215b20` | 首次执行：容器名含 `+` 导致 `docker run` 125，全部未验证 |
| `VER-20261114T123224+0800-6984` | PASS | `059932e1` | 首次 PASS；能力记录中 loopback 记为 UNAVAILABLE（判定口径随后修正，以 `a691` 为准） |
| `VER-20261114T123024+0800-3c52` | FAIL | `28538e58` | `tmpfs /workspace` 不可写 + P4-05 残留判定顺序错误 |
| `SCAN-20261114T123405+0800-c604` | UNVERIFIED | `d8d822d3` | worker payload 双重编码导致健康检查超时 |
| `SCAN-20261114T123510+0800-5b8f` | UNVERIFIED | `02d102d5` | 真扫未做 WSL 路径映射 |
| `SCAN-20261114T164810+0800-95ac` | NOT_ESTABLISHED | `82487258` | 3 条动态检查注入载荷不适配（`/order`、`/profile`、`/search`） |

> 上述失败包如实保留，用于证明"未验证不得返回 0、失败可追溯"。最终结论以上表三条真实执行为准。

## 3. 冲突点处置（K-01…K-10，缺项 0）

| 编号 | 处置 | 落点 |
|---|---|---|
| K-01 | 容器身份结论为对外口径，宿主域降为过程记录 | `isolation_bridge.py`、`m8` |
| K-02 | 保持故障关闭，新增 `EXEC_DOMAIN_MISMATCH` 分类，不放行 | `eval/isolation.py`、单测 5 条失败分支 |
| K-03 | 改为挂载面裁剪，区分 `PATH_NOT_EXIST` 与 `PERMISSION_DENIED` | `isolation_bridge.py`、`m8` |
| K-04 | 补测 P4-05（62237ms），未执行时维持 UNVERIFIED | `constraints.py`、`m6` |
| K-05 | 重开受"无 Docker"影响的条目，旧结论保留为历史 | 本索引、`m6` 对照表 |
| K-06 | M1 10/10 标 `RECORDED_STUB`，不计入真扫分母 | `scan.py`、`m7` |
| K-07 | 真扫默认 15/15 全量，子集必须声明未覆盖 | `scan.py`、`m7` |
| K-08 | 同容器回环满足禁网与可达 | `worker.py`、`m7` |
| K-09 | 边界声明随证据携带，云上不外推 | 本索引第 1 节 |
| K-10 | 新增验证沿用 unittest，pytest 不作项目依赖 | 全量回归 |

## 4. 默认值登记（O-01…O-06 / Q-01…Q-10）

> 以下全部为 **"本轮采用默认值（待拍板）"**，不得表述为用户已确认。记录中 `adopted_defaults[]` 共 16 条，`pending=true`；CLI 用 `--oXX/--qXX` 覆盖后变为 `CLI_OVERRIDE / pending=false`。

| 编号 | 采用值 |
|---|---|
| O-01 | 10 个判定类别覆盖 11 个策略键（filesystem 合并） |
| O-02 | P4-01 使用合成 `.git` 夹具（`fixture=true`） |
| O-03 | 允许本地镜像别名，强制登记镜像 ID |
| O-04 | 只做 CLI + 证据包，不新增 API 路由 |
| O-05 | 运行期 Flask 3.1.3 独立，C01 仅静态检出 |
| O-06 | 宿主回退默认开启，标 `REAL_LOCAL` 不计入沙箱 |
| Q-01 | 发行版 root 身份执行（`RUNTIME_ROOT`） |
| Q-02 | 本地构建镜像 + 镜像 ID |
| Q-03 | 仅构建期联网，运行期禁出 |
| Q-04 | 动态端口分配 |
| Q-05 | 15 项全量 |
| Q-06 | 接受宿主回退但不计入沙箱证据 |
| Q-07 | 强制补测 P4-05 |
| Q-08 | 双轨探针，容器域可发布 |
| Q-09 | 只写新证据目录，不改 `eval/runs` |
| Q-10 | 云端占位 `CLOUD_CREDENTIAL_MISSING` |

## 5. 历史留痕基线（发布前 9 项复算，全部一致）

| 文件 | sha256 |
|---|---|
| `.evidence/sandbox/M0-SANDBOX-20261113T171337.txt` | `a365c35284bd0be2ef5b8589283007a73a17c4fa9f4f3f73984ba274a9b17db6` |
| `docs/devlog/m0-sandbox-verification.md` | `35b0c79267427a13041d431b14d4a3f9408621cd5c11e04af88e7aef24a68d30` |
| `docs/devlog/m1-detect-report.md` | `8892168ab81864c3f14397965419e6e20647e7cd45be6ca33559e868899ed6bb` |
| `docs/devlog/m5-eval-report.md` | `931d20442673b0922a32cfb42de1dcc9996925836607f6ddedbc5e8b1f165502` |
| `docs/devlog/m2-reproduce-report.md` | `e6fe54abcc850420da4955ff2ba545b909b02800ff85d74e6cd3e184547531d3` |
| `docs/devlog/m1-reachability-report.md` | `89d8a582ebc97216462bd9e9d430c8a7e3beb7b266b3f1a4c89ee0adaa13d4f8` |
| `sandbox/spec.json` | `bd62277bbae9d6ed146e92231b36bc2a3e5462e5aca715144ad8332384e36168` |
| `verifix-target/ground_truth.json` | `286d13be98fdfc9c18967be8d82e761ab1751ee1aacfc836d599e937b69becb2` |
| `verifix-target/requirements.txt` | `5e19106aab58ab1414748848bc3b13e2568f54f119603e2606a80d93ba6795a3` |

- 复算入口：`backend/app/realscan/evidence.py::verify_history_digests`，单测断言 9 项全等。
- 新报告为**并列新增**，不覆盖、不改写历史。

## 6. 回归基线与兼容性

| 项 | 实测 |
|---|---|
| 全量回归 | `python -m unittest discover -s backend/tests -p "test_*.py"` → **Ran 589 tests**，唯一失败 `PERF-02`（0.2799s > 0.2s，抖动） |
| 抖动用例单跑 | `PERF-02` 单跑 `OK`（0.829s 总耗时，`capture` 低于阈值） |
| 基线口径 | **≥589 用例、功能性失败 0**（旧基线 502，本轮新增 87 条） |
| MCP 白名单 | `test_sandbox_mcp` 8 工具、`tool_version` 不变 |
| `LocalTestExecutor.env_snapshot` | `network_disabled=False`、`read_only=False` 语义不变 |
| `AccessAuditLog.record/search` | 行为不变（`test_eval_isolation` 全绿），只增 `archive_entries` |
| `main.py` 路由 | 未新增 `/api/v1/realscan/*`，路由集合不变 |

## 7. 交付物清单

- 新增模块 19 个：`backend/app/runtime/exec_domain.py`、`backend/app/realscan/{__init__,models,runtime,capability,policy,probe_scripts,constraints,target,rules,scanner,dynamic,worker,scan,reconcile,evidence,boundary,isolation_bridge,pipeline}.py`
- 扩展模块 3 个：`config.py`（`RealscanConfig` 23 字段 + 8 条校验）、`api/envelope.py`（`VF-8010/8011/8012`）、`eval/isolation.py`（`exec_domain/failure_kind/publishable` + `AuditArchiveQuery`，故障关闭不变）
- 新增测试 8 个文件（本子项目 87 条用例）
- 新增脚本 4 个：`build_sandbox_images.py`、`run_sandbox_verify.py`、`run_realscan.py`、`verify_isolation_bridge.py`
- 新增镜像定义 3 个：`sandbox/Dockerfile.sandbox`、`Dockerfile.target`、`requirements.target.txt`
- 新增报告 4 份：本索引 + `m6` + `m7` + `m8`
- 镜像：`verifix-sandbox:1.0.0`=`sha256:9b090181…`、`verifix-target:1.0.0`=`sha256:5d0b0a32…`（本地构建、无仓库摘要）

## 8. 不做清单（已执行或保持不做）

1. 未做云上复测（无凭据），未伪造云端门禁结果。
2. 运行期网络不可放宽（配置层无该项，`RunSpecBuilder` 不允许覆盖）。
3. 未关闭强制自检（`eval/isolation.py` 失败分支全部 `raise`）。
4. 未以桩冒真（M1 标 `RECORDED_STUB`）。
5. 未修改 `eval/` 既有结论与 `eval/runs`。
6. 未初始化真实 Git 仓库（P4-01 用合成夹具）。
7. 未修改靶场源码/真值/依赖清单。
8. 未新增 MCP 工具，未引入 pytest 作为项目依赖。

## 9. 覆盖与闸门

- 覆盖矩阵：spec 5.1–5.4、6.1–6.6、4.1–4.5 共 113 条，需求 → 设计 → 任务 → 验证**缺项 0**。
- 闸门一：K-01…K-10 全部登记，缺项 0。
- 闸门二：O-01…O-06 与 Q-01…Q-10 全部标注"采用默认值（待拍板）"，`adopted_defaults` 16 条。
- 闸门三：关闭强制自检 / 放开网络 / 以桩冒真 三类行为发生次数 = 0。
- 边界终验：报告与证据中未出现任何云端完成性断言。

## 10. 仍待人工拍板

O-01…O-06（10 类覆盖 11 键、合成 `.git` 夹具、镜像别名登记、是否暴露 API、Flask 版本口径、宿主回退默认开启）仍为默认值；若需调整，按 `tasks.md` §0.4 逐项回归即可，不需重开需求设计。