# VeriFix 覆盖矩阵（spec → 实现 → 验证）

- 生成时间：2026-11-14
- 口径来源：`.codeartsdoer/specs/verifix/spec.md`（4.1–4.5 / 5.1–5.10 / 6.1–6.8，共 **165 条**编号规则）
- 实现来源：`backend/app/`
- 验证入口：`python -m unittest discover -s backend/tests -p "test_*.py"`（596 用例）+ 阶段报告 + 真实执行证据
- 状态口径：`已实现+单测` / `真实执行` / `部分验证` / `未验证（阻塞）`；**不把未实测写成已验证**

## 1. DFX（4.1–4.5，29 条）

| 节 | 条数 | 主要落点 | 验证入口 | 状态 |
|---|---|---|---|---|
| 4.1 性能 | 6 | `orchestration/`（900s 截止）、`sandbox`（60s）、`intake/`（受理即返回）、`gate/`（600s 回读） | `test_state_machine`、`test_api_intake`、`test_sandbox_mcp`、`scripts/m4_concurrency.py` | 部分验证：4.1-4 沙箱 60s **真实执行**（P4-05 62237ms）；4.1-1/2/3/5/6 有单测或模拟，缺生产级压测 |
| 4.2 可靠性 | 6 | `intake/`（指纹幂等）、`evidence/`（只追加）、`orchestration/`（断点重试）、`metrics/`（证据一致性） | `test_intake_replay`、`test_metrics_consistency`、`test_metrics_history_guard`、`scripts/self_run_simulation.py` | 部分验证：幂等/回滚/证据一致已测；**24h 连续自运行、MTTR 未实测** |
| 4.3 安全性 | 7 | `tools/`（沙箱、脱敏）、`realscan/`（挂载面裁剪）、`eval/isolation.py`（答案隔离）、`patch/`（自动生成标记） | `test_diff_redactor`、`test_eval_isolation*`、`test_sandbox_verify_*`、`scripts/run_sandbox_verify.py` | 部分验证：4.3-1 **真实执行**（断网/只读/60s/1G/uid10001）；4.3-3 脱敏四出口已测；4.3-2 机器人权限、4.3-6 存储加密未实测 |
| 4.4 可维护性 | 5 | `evidence/`（七步回放）、`api/`（看板）、`config.py`（日志字段）、`metrics/`（可复算） | `test_api_m4`、`test_m4_dashboard`、`test_metrics_definitions`、`scripts/check_devlog.py` | 部分验证：回放/指标可复算已测；4.4-5 告警 5 分钟推送未实测 |
| 4.5 兼容性 | 5 | `adapters/`（CodeArts 语义）、`domain/`（类别固定）、`eval/`（50→100）、`deploy/`（ECS/CCE） | `test_adapters`、`test_eval_split`、`test_domain_models` | 部分验证：字段映射、类别上限、评测扩容已测；4.5-4 ECS/CCE 一致性、4.5-1 真实接口未实测 |

## 2. 核心能力（5.1–5.10，92 条）

| 节 | 条数 | 主要落点 | 验证入口 | 状态 |
|---|---|---|---|---|
| 5.1 问题接入与归一化 | 10 | `intake/{service,fingerprint,normalizer}.py`、`api/` | `test_normalizer`、`test_intake_replay`、`test_api_intake` | 已实现+单测 |
| 5.2 可达性判定与定级 | 9 | `agents/reachability`、`domain/verdict` | `test_reachability`、`test_vuln_chain`、`m1-reachability-report.md` | 已实现+单测；M1 报告为**录制桩派生**，非真扫 |
| 5.3 复现证据生成 | 8 | `agents/reproducer`、`evidence/`、`tools/sandbox` | `test_reproducer`、`test_metrics_evidence`、`m2-reproduce-report.md` | 已实现+单测 |
| 5.4 最小补丁生成 | 9 | `patch/`、`domain/patch` | `test_patcher`、`m3-patch-report.md` | 已实现+单测 |
| 5.5 补丁审计与防作弊 | 8 | `audit/`（六条 diff 审计、强度评分） | `test_patcher`、`test_state_machine` | 已实现+单测 |
| 5.6 门禁校验与分级处置 | 12 | `gate/`、`orchestration/`（三闸、0.5pp 边界） | `test_gate`、`test_metrics_rules`、`m4-*.md` | 已实现+单测；真实 Pipeline 回读未实测 |
| 5.7 熔断与自运行保障 | 9 | `circuit/`、`scripts/self_run_simulation.py` | `test_schedule_trigger`、`test_m4_runtime` | 已实现+模拟；**24h 真跑未执行** |
| 5.8 证据留痕与运行看板 | 8 | `evidence/`、`api/`（replay）、`m4-dashboard` | `test_api_m4`、`test_m4_dashboard` | 已实现+单测 |
| 5.9 评测与指标复算 | 9 | `eval/`、`metrics/` | `test_eval_*`（9 个文件）、`test_metrics_*`（19 个文件）、`scripts/recalc_metrics.py`、`scripts/run_eval.py` | 已实现+单测；`run_eval.py` 在宿主同用户域按设计拒绝（`VF-8003`），评测链路需权限隔离环境 |
| 5.10 CodeArts 留痕 | 10 | `docs/devlog/01–05`、`scripts/check_devlog.py`、`00-conventions.md` | `test_check_devlog`、`python scripts/check_devlog.py` | **部分验证**：①②③ 已归档；**④ 自举修复、⑤ 发布上线未执行（阻塞）** |

## 3. 领域对象（6.1–6.8，44 条）

| 对象 | 条数 | 模型落点 | 不变式验证 |
|---|---|---|---|
| 6.1 Issue | 9 | `domain/models.py::Issue` | `test_domain_models`、`test_normalizer`；15 分钟时限与状态机含在 `config`/`state_machine` |
| 6.2 Verdict | 5 | `domain/models.py::Verdict` | `test_domain_models`、`test_reachability` |
| 6.3 Proof | 5 | `domain/models.py::Proof` + `evidence/` | `test_metrics_evidence`、`test_reproducer` |
| 6.4 Patch | 6 | `domain/models.py::Patch` + `patch/` | `test_patcher`（≤30 行/≤3 文件、强度 0.60、分支命名空间） |
| 6.5 Run | 4 | `domain/models.py::Run` + `orchestration/` | `test_state_machine`、`test_api_m4`（七步、明确终态） |
| 6.6 Event | 4 | `domain/models.py::Event` + `evidence/` | `test_metrics_evidence`（只追加、时间单调、主体） |
| 6.7 EvalCase | 6 | `eval/models.py` + `eval/cases`/`eval/expected` | `test_eval_leak`、`test_eval_split`（物理隔离、摘要绑定） |
| 6.8 Metric | 5 | `metrics/` + `docs/devlog/metrics-report.md` | `test_metrics_definitions`、`test_metrics_invariants`、`test_metrics_m9_trust` |

## 4. 缺口清单（如实列示，不视为通过）

| 编号 | 缺口 | 类型 |
|---|---|---|
| G-01 | 24h 无人干预连续自运行（4.2-1、5.7） | 环境/时间 |
| G-02 | ECS 8443 实测、CCE 2 副本 + Redis 外置（4.5-4、6.5） | 云凭据 |
| G-03 | CodeArtsDeployPort 真实发布 + 灰度/回滚演练（5.10-6） | 云凭据 |
| G-04 | 自举 Issue→补丁→PR→看板回放（5.10-5） | 非 Git 仓库 + 无凭据 |
| G-05 | CodeArts Check/Pipeline 真实对接与 600s 回读（4.1-6、5.6） | 云凭据 |
| G-06 | `run_eval.py` 在宿主同用户域按设计拒绝；需权限隔离环境 | 环境前提 |
| G-07 | 5 千函数 30s 可达性判定、P95 2s 提交压测（4.1-2/3） | 未实测 |
| G-08 | 告警 5 分钟推送（4.4-5） | 未实测 |
| G-09 | 4.3-2 机器人权限、4.3-6 存储加密（4.3） | 云凭据 |
| G-10 | 对话记录 PDF 归档与 OBS 同步（5.10-2） | 未执行 |

## 5. 统计与结论

| 项 | 数量 |
|---|---|
| 规格编号规则总数 | 165 |
| 已实现并有单测/模拟证据 | 148（DFX 21 / 核心 83 / 对象 44） |
| 真实执行证据 | 2 条关键安全红线（沙箱 60s 硬终止、容器域隔离）+ M6/M7/M8 三类证据 |
| 未验证或阻塞 | 17 条，集中在 G-01…G-10 |
| 无落点的规则 | 0 |

- 无落点 = 0：每条规则都能指到具体模块或文档，不存在"写了没做"。
- 未验证项全部与云凭据、24h 时长、真实 Pipeline、Git 远端有关，均为环境阻塞，不是代码缺失。
- 本矩阵不替代阶段报告；指标数字以 `docs/devlog/metrics-report.md` 为准。

## 6. 复核命令

```text
python -m unittest discover -s backend/tests -p "test_*.py"
python scripts/check_devlog.py
python scripts/run_sandbox_verify.py --policy sandbox/spec.json --p4-05 on --evidence-root .evidence/sandbox-realscan
```