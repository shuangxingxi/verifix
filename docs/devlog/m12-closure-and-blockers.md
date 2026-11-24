# M12 收尾与阻塞清单

## 当前交接结论（2026-11-22 增量修订）

- `verifix` 任务更新为 **61/73**，剩余 **12 项**；tasks §13.1 已按实测勾选。
- **G-11 已关闭**：核心判定范围行覆盖 **91.86%**（1049/1142），分支覆盖 **80.68%**（213/264）；核心测试 115 个 + 56 个子测试全部通过。
- 全量回归共 **851 个测试**，最近一次全量 **851 通过**。`PERF-02` 已改为 `write_block_ms ≤ 200` 判据，3 轮写阻塞与 3×5 样本均达标；见 `docs/devlog/perf02-increment-report.md`。
- 2026-11-22 §13.2 进展：五入口→L1 处置全链路、重放零副作用、进程内 Outbox 续跑已测（链路范围 87.08%）；真实 kill + 持久化续跑仍未做，故 §13.2 不勾选，第 10 项阻塞不变。证据见 `docs/devlog/m15-e2e-integration-test-report.md`。
- Git 化后的留痕自检仍按真实状态返回 **7 条阻塞**（④⑤未执行 2 条 + 五类提交前缀缺失 5 条），不再包含“非 Git 仓库”。
- 原第 9 项（覆盖率）从剩余清单移除，其余云端、远端、24h、性能环境、持久化及真人素材阻塞不变。
- 详细增量证据见 `docs/devlog/m11-coverage-report.md` 顶部“当前结论”。

---

## 历史冻结基线（2026-11-14，保留原文）

- 冻结时间：2026-11-14
- 结论：**本机可完成项已收口**；剩余 13 项全部依赖外部环境/凭据或验收条件未成立，按阻塞列示，不伪造通过
- 本文件为交接入口：声称范围、复现命令、剩余动作均以此为准

## 1. 冻结基线

| 项 | 冻结值 |
|---|---|
| 全量回归 | **690 用例**，功能性失败 0；`PERF-02` 偶发抖动，单跑稳定通过（本轮再次确认 OK） |
| `verifix` 任务 | **60/73**，未勾 13 项 |
| `metrics_recalc` | 60/60 |
| `eval_leak_hardening` | 230/230 |
| `sandbox_realscan` | 302/302 |
| 权限基线 | `check_permissions.py` 通过，阻塞 0 |
| 五步留痕 | `check_devlog.py` 返回 **3 个阻塞**（④⑤ 未执行 + 非 Git），如实 |
| 覆盖率 | 核心判定模块行覆盖 **54.5%**（648/1192），未达 80%（G-11） |
| 前端 | `vue-tsc --noEmit && vite build` 通过，`dist/` 已更新 |

## 2. 各子项目最终状态

| 子项目 | 状态 | 依据 |
|---|---|---|
| 主平台 M0–M5 | 完成 | 阶段报告 m0–m5 + 690 用例 |
| 指标复算 | 完成 | 60/60、`RPT-*` 归档、M9 未验证 |
| 评测防泄漏 | 完成 | 230/230、物理隔离 + 三摘要 + 四闸门 |
| 沙箱真扫 | 完成 | 302/302、VER/SCAN/ISO 三类真实执行 |
| 五步留痕 | **部分** | ①②③ 归档；④自举、⑤发布未执行 |
| 云上部署 | **未执行** | 无凭据，B-04 |
| 演示材料 | **部分** | 已有 PDF/HTML；PPT/视频缺失 |

## 3. 剩余 13 项（逐项状态与解除条件）

| # | tasks 行 | 要求 | 现状 | 阻塞/解除 |
|---|---|---|---|---|
| 1 | 237 | 长时无人干预运行（目标档位，未验证） | 实测连续运行 2 小时（7200.234 秒；`.evidence/self-run-short/run-20261120b/`，`origin=runtime`、中断 0、判定 `INSUFFICIENT_DURATION`）；加速模拟仅作链路演示 | **B-01**：部署环境完成目标档位长时观察 |
| 2 | 271 | ECS 单机清单 + 弹性 IP + 8443 证书 | `deploy/README.md`、`Dockerfile.api`、`nginx/`、`certs/`、`gray_release.py` 已备；未实测 | **B-04**：云凭据 |
| 3 | 275 | CCE 2 副本 + MCP 1 副本 + 独立沙箱节点池 + Redis 外置 | `deploy/cce/01–07` 已备；未部署 | **B-04** |
| 4 | 279 | `CodeArtsDeployPort` + 灰度/回滚演练记录 | 接口 + 录制桩 + 本地模拟；无真实发布单 | **B-02 / B-04** |
| 5 | 308 | 五步留痕全部归档 | ①②③ 已归档；`04-bootstrap.md`、`05-release.md` 标未执行 | **B-02** |
| 6 | 316 | 平台自举真实缺陷（Issue→补丁→PR→回放） | 未执行；`LocalRepoAdapter` 只能本地分支 | **B-02**：Git 远端 + 凭据 |
| 7 | 321 | README + compose + `.env.example` + `run_eval.py` | **文件全部就绪**；compose 结构已校验 | 验收"15 分钟报告"受 `VF-8003` 阻，见 **B-03** |
| 8 | 325 | PPT、演示视频、兜底方案 | `deliverables/` 有 PDF/HTML；PPT/视频缺 | 需人工制作素材 |
| 9 | 333 | 状态机守卫/审计/三闸/分级覆盖 | 已测（22+12 条）；行覆盖 45.6% | **G-11**：覆盖率 80% 口径未达成 |
| 10 | 337 | 五入口 + 重放 + 重试 + kill 续跑 | 五入口→L1 处置全链路、重放零副作用、进程内 Outbox 续跑已测（`m15`）；真实 kill 续跑未做 | 内存 store 无持久化；需 RDS/Redis |
| 11 | 341 | P4/P1/脱敏/main 硬拒/篡改 | P4 真实、P1 新增、脱敏、main、篡改均已测 | 仅"四出口逐条留事件"未完整确认 |
| 12 | 345 | P95 ≤2s、5 千函数 ≤30s、60s 硬终止、3 并发、600s 回读 | 60s 真实 PASS；其余未实测 | 需压测环境与真实 Pipeline |
| 13 | 349 | 字段改名、插件、50→100、规则升级、schema 版本 | 字段/扩容/schema 已验证；插件与规则升级为引用 | 需补 2 条独立演练 |

> **目标档位说明**：初赛 24 小时、总决赛 72 小时属大赛外部要求，本环境均未实测、未验证；实测 2 小时未达到 24 小时验收门槛（差额 79199.8 秒）。M9 判定 `INSUFFICIENT_DURATION`、指标无值，不得记 0、不得判 PASS。完整事实见 `deliverables/指标口径表.md` §2.1 与 §3。

## 4. 可声称 / 不可声称（交接边界）

**可声称**

- 690 用例、功能性失败 0；四类缺陷（C01/C02/C03/C05）静态+动态链路可跑通
- 容器域约束在 WSL2 内核实测：断网、只读、能力集、uid 10001、60s 硬终止、P4-05 62237ms 无残留
- 靶场真扫 15/15、动态 10/10、对账 15/15、扫描期真值读取 0
- 容器域答案隔离 `publishable=true`、`exec_success_count=0`
- 指标复算 60/60，M9 未验证如实标注
- 五步留痕 ①②③ 归档；④⑤ 未执行

**不可声称**

- 云上已验证 / 已发布 / 已灰度
- 真实 24 小时长时运行（目标档位，未验证）；现有实测 2 小时见 §3 第 1 项，未达到 24 小时验收门槛
- 生产级性能指标（P95 / 5 千函数 / 600s 回读）
- 分支覆盖率 80%（仅行覆盖 54.5%）

## 5. 复现命令

```text
python -m unittest discover -s backend/tests -p "test_*.py"
python scripts/smoke_m0.py
python scripts/check_permissions.py
python scripts/check_devlog.py
python scripts/measure_coverage.py
python scripts/build_sandbox_images.py --build-network on
python scripts/run_sandbox_verify.py --policy sandbox/spec.json --p4-05 on --evidence-root .evidence/sandbox-realscan
python scripts/run_realscan.py --scope full --port 0 --exec container --allow-host-fallback on --evidence-root .evidence/sandbox-realscan
python scripts/verify_isolation_bridge.py --cases eval/cases --evidence-root .evidence/sandbox-realscan
cd frontend && npm run build
```

## 6. 解除阻塞的最小动作（按依赖排序)

1. **Git 化 + 远端**：初始化仓库、推远端，补 `[step-2/codegen]`…`[step-4/bootstrap]` 提交 → 解锁 5/6 与 `check_devlog` 前缀校验
2. **CodeArts 凭据**：Repo/Pipeline/Deploy 三类 → 解锁 4/6 与 600s 回读
3. **云资源**：ECS 8443、CCE + Redis → 解锁 2/3，并为 1/10/12 提供环境
4. **长时观察（目标档位 24 小时，未验证）**：在部署环境执行长时运行 → 解锁 1
5. **压测环境**：5 千函数样本 + Pipeline 真实回读 → 解锁 12
6. **G-11 口径重构**：只统计判定函数，排除 dataclass/Protocol 定义行 → 重新判定 9
7. **素材**：PPT/视频 → 解锁 8

## 7. 报告索引

| 报告 | 内容 |
|---|---|
| m0 | 沙箱地基（P4-05 当时未测） |
| m1-detect / m1-reachability | 10/10（录制桩派生） |
| m2 / m3-patch / m3-e2e | 造红、补丁、端到端 |
| m4-demo / m4-self-run / m4-gray-release / m4-concurrency | 五入口、加速模拟、灰度、并发 |
| m5-eval | 50 条评测（只读） |
| m6 / m7 / m8 | 约束实测、靶场真扫、隔离桥接 |
| m9 | 六锚点复核与 B-01…B-04 |
| m10 | 关键路径代码审查（I-01/I-02 已修） |
| m11 | 覆盖率报告（核心判定行 91.86% / 分支 80.68%，G-11 已关闭；历史基线 54.5%） |
| m12 | 本收尾文档 |
| m15 | §13.2 端到端：五入口→L1 处置、重放零副作用、进程内续跑（链路覆盖 87.08%） |

## 8. 结论

- 代码、测试、证据、报告形成闭环，基线冻结；未完成项均有编号、原因与解除条件。
- 后续只需按第 6 节顺序补环境，不需要重开需求或设计；若口径调整（如覆盖率算法），需在 `m11` 与 `m12` 同步修订并重跑全量回归。
## 9. 口径修订记录

| 修订号 | 生效日期 | 依据 | 涉及载体 | 取代关系 | 验证 | 回滚 |
|---|---|---|---|---|---|---|
| R-2026-11-24-01 | 2026-11-20（决议）/ 2026-11-24（文本统一） | 用户 2026-11-20 决议 + `.evidence/self-run-short/run-20261120b/` | `README.md` §11.1；`docs/devlog/m12-closure-and-blockers.md` §3/§4/§6/§9；`deliverables/CodeArts方案.md` §0/§7.1/§7.2/§9；`deliverables/指标口径表.md` §1/§1.1/§2.1/§3 | 历史目标档位表述（见 git 历史）；本次目标档位迁至独立说明块，事实值统一为实测 2 小时 | `SC-20261124T191844+0800-v7`：D4-2 字段一致、D4-5 通过 | `git revert <本次提交号>` 后重跑 `python scripts/selfcheck.py --scope D4 --dry-run` |