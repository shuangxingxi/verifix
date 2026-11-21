# M12 收尾与阻塞清单（基线冻结）

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
| 1 | 237 | 24h 无人干预连续运行 | 真实短跑 2h（`.evidence/self-run-short/run-20261120b/`，`origin=runtime`、中断 0、判定 `INSUFFICIENT_DURATION`）；加速模拟仅作链路演示 | **B-01**：部署环境连续 ≥24h |
| 2 | 271 | ECS 单机清单 + 弹性 IP + 8443 证书 | `deploy/README.md`、`Dockerfile.api`、`nginx/`、`certs/`、`gray_release.py` 已备；未实测 | **B-04**：云凭据 |
| 3 | 275 | CCE 2 副本 + MCP 1 副本 + 独立沙箱节点池 + Redis 外置 | `deploy/cce/01–07` 已备；未部署 | **B-04** |
| 4 | 279 | `CodeArtsDeployPort` + 灰度/回滚演练记录 | 接口 + 录制桩 + 本地模拟；无真实发布单 | **B-02 / B-04** |
| 5 | 308 | 五步留痕全部归档 | ①②③ 已归档；`04-bootstrap.md`、`05-release.md` 标未执行 | **B-02** |
| 6 | 316 | 平台自举真实缺陷（Issue→补丁→PR→回放） | 未执行；`LocalRepoAdapter` 只能本地分支 | **B-02**：Git 远端 + 凭据 |
| 7 | 321 | README + compose + `.env.example` + `run_eval.py` | **文件全部就绪**；compose 结构已校验 | 验收"15 分钟报告"受 `VF-8003` 阻，见 **B-03** |
| 8 | 325 | PPT、演示视频、兜底方案 | `deliverables/` 有 PDF/HTML；PPT/视频缺 | 需人工制作素材 |
| 9 | 333 | 状态机守卫/审计/三闸/分级覆盖 | 已测（22+12 条）；行覆盖 45.6% | **G-11**：覆盖率 80% 口径未达成 |
| 10 | 337 | 五入口 + 重放 + 重试 + kill 续跑 | 前四项已测；真实 kill 续跑未做 | 内存 store 无持久化；需 RDS/Redis |
| 11 | 341 | P4/P1/脱敏/main 硬拒/篡改 | P4 真实、P1 新增、脱敏、main、篡改均已测 | 仅"四出口逐条留事件"未完整确认 |
| 12 | 345 | P95 ≤2s、5 千函数 ≤30s、60s 硬终止、3 并发、600s 回读 | 60s 真实 PASS；其余未实测 | 需压测环境与真实 Pipeline |
| 13 | 349 | 字段改名、插件、50→100、规则升级、schema 版本 | 字段/扩容/schema 已验证；插件与规则升级为引用 | 需补 2 条独立演练 |

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
- 真实 24h 连续运行（现有仅为 2h 真实短跑，不足 24h）
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
4. **24h 观察**：在部署环境连续运行 → 解锁 1
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
| m11 | 覆盖率报告（54.5%，G-11） |
| m12 | 本收尾文档 |

## 8. 结论

- 代码、测试、证据、报告形成闭环，基线冻结；未完成项均有编号、原因与解除条件。
- 后续只需按第 6 节顺序补环境，不需要重开需求或设计；若口径调整（如覆盖率算法），需在 `m11` 与 `m12` 同步修订并重跑全量回归。