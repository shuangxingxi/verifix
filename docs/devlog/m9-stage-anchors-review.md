# M9 阶段验收锚点复核记录（design 2.6）

- 生成时间：2026-11-14
- 依据：`.codeartsdoer/specs/verifix/tasks.md` §15.4、`.codeartsdoer/specs/verifix/design.md` §2.6
- 结论：**四个锚点达标，两个锚点部分达标**；未达标项已列为阻塞并在此明示（符合 §15.4 完成标准）

## 1. 锚点总表

| 锚点 | 验收要求 | 可复现证据 | 结果 | 状态 |
|---|---|---|---|---|
| M0 空转可回放 | 七步链路可跑通、事件链可校验 | 2026-11-14 重跑 `python scripts/smoke_m0.py`：`chain_valid=True`，事件 `INGEST→VERDICT→DISPOSITION`，Outbox `triage:ISS-25ad58581048`；`docs/devlog/m0-sandbox-verification.md` 结论 PASS | PASS | 达标 |
| M1 检出 ≥8/10 且判定有路径 | 检出 ≥8/10；可达判定与人工标注一致 | `docs/devlog/m1-detect-report.md` 检出 **10/10**；`m1-reachability-report.md` 一致 **10/10** | PASS（10/10、10/10） | 达标 |
| M2 ≥6/10 造红 | 复现测试在补丁前失败 | `docs/devlog/m2-reproduce-report.md` 造红 **10/10** | PASS（10/10） | 达标 |
| M3 ≥4/6 一次修好且回滚正确 | 一次修复通过；回滚幂等 | `docs/devlog/m3-patch-report.md` 通过 10/10；`m3-e2e-report.md` 一次修好 **10/10**；回滚由 `test_state_machine` 覆盖 | PASS（10/10） | 达标 |
| M4 五入口 + 24h 自运行 + 看板齐全 | 五入口全链路、24h 真实自运行、看板可用 | 五入口：`m4-demo-report.md` 5/5 + 2026-11-14 `test_e2e_pipeline` 5 条；看板：`/api/v1/dashboard/summary` + `test_m4_dashboard`；24h：`m4-self-run-report.md` 为**受控时钟加速模拟**，报告自述"不能替代 8.5 验收证据" | **部分达标** | 阻塞 B-01 |
| M5 50 条评测与五步留痕完整 | 50 条评测报告；五步留痕齐备 | 评测：`m5-eval-report.md`（`EVALRUN-27714aeffb`，50 条）；五步：①②③ 已归档，④`04-bootstrap.md`、⑤`05-release.md` 标"未执行（阻塞）" | **部分达标** | 阻塞 B-02 |

## 2. 证据口径说明

1. **M1 的 10/10 为录制桩派生**（`RECORDED_STUB`），不是真实扫描；真实扫描结论在 `m7-target-realscan-report.md`（15/15），两者分母不合并。
2. **M3 的执行后端**为 `local-dev`；M0 已于 2026-11-13 在容器域补测（网络/只读/能力集/60s），但 M3 的端到端仍未在容器内重跑，属"部分证据"。
3. **M4 的 24h** 目前只有加速模拟（60 次心跳、中断计数验证），**不是**真实 24 小时观察。
4. **M5 的评测链路**：`run_eval.py` 在宿主同用户域按设计抛 `VF-8003`（答案隔离自检），需 Linux 原生路径 + 独立属主 + `700` 才能复跑；现有 `m5-eval-report.md` 为历史只读结论。
5. 云上部署未执行（无凭据），本表不包含云侧锚点。

## 3. 阻塞项（明示，不计入达标）

| 编号 | 阻塞项 | 影响锚点 | 解除条件 |
|---|---|---|---|
| B-01 | 真实 24h 无人干预连续运行 | M4 | 部署环境连续运行 ≥24h，产出心跳采样、Issue 吞吐与告警记录 |
| B-02 | 五步留痕 ④ 自举修复、⑤ 发布上线 | M5 | Git 远端 + CodeArts 凭据；产出 Issue→补丁→PR 与发布/回滚演练记录 |
| B-03 | 评测链路在权限隔离环境复跑 | M5 | Linux 原生文件系统 + 独立属主 + `expected` 700 |
| B-04 | ECS 8443 / CCE 2 副本 + Redis 外置 | 部署锚点（未在本表计分） | 云凭据 |

## 4. 复核命令

```text
python scripts/smoke_m0.py
python -m unittest discover -s backend/tests -p "test_*.py"
python scripts/check_devlog.py
python scripts/check_permissions.py
```

- 全量回归基线：**641 用例，功能性失败 0**（`PERF-02` 偶发抖动，单跑稳定）。
- `check_devlog.py` 当前如实返回阻塞（04/05 未执行 + 非 Git），未通过文案绕过。

## 5. 结论

- 达到"六锚点各有可复现记录"的形式要求：M0–M3 达标，M4/M5 部分达标且阻塞项逐条列明。
- 不把加速模拟写成真实 24h，不把录制桩派生写成真扫，不把未接入云的状态写成已部署。
- 后续若解除 B-01/B-02/B-03，本表可原地升级为全部达标，无需重开需求或设计。