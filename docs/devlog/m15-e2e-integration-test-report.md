# M15 §13.2 端到端集成测试报告（五入口 → 处置全链路）

- 执行时间：2026-11-22
- 目标：`docs/devlog/specs/tasks.md` §13.2「编写端到端集成测试」
- 测试文件：`backend/tests/test_e2e_pipeline.py`
- 结论：**本机可验证部分完成；整项仍为未勾选**，真实进程 kill + 持久化 store 的跨进程续跑依赖 RDS/Redis，未验证前不宣称通过。

---

## 1. §13.2 完成标准逐条对账

| 完成标准 | 本轮状态 | 证据 |
|---|---|---|
| 五入口 → 处置全链路 | **已完成** | `test_manual_entry_reaches_l1_disposition_with_full_evidence`：API 入口受理 → 可达性判定 → 红态复现 → 补丁生成 → 六条审计 → 三闸 → L1 处置 → 处置视图 API |
| 重复 Webhook 重放不产生重复分支/PR/计数 | **已完成** | `test_webhook_replay_after_disposition_has_no_duplicate_side_effects`：连续两次同签名重放，issues / branches / PR / merged / disposition 历史 / 事件链长度 / outbox 全部不变 |
| 中断后从 Outbox 重放，状态不回退 | **部分完成（进程内）** | `test_resume_after_interruption_keeps_status_and_evidence`：PROVEN 处中断 → 重新装配组件 + Outbox 重放 → 状态、Proof、事件链长度不变，且状态机拒绝 T1 回退；真实进程 kill 未验证 |
| 证据不丢 | **已完成（进程内）** | Proof 的 `proof_id` / `fingerprint` / 序列化内容前后一致；事件链 `verify_chain` 为真；处置证据缺失时 API 返回 `VF-7001`（`test_disposition_api_rejects_unresolvable_run_evidence`） |

未完成项（阻塞不变）：`m12 §3` 第 10 项「真实 kill 续跑」需 RDS/Redis 持久化与进程级重启，本机内存 store 无法验证，因此 §13.2 不勾选。

---

## 2. 新增用例（5 个，全部追加在既有 `FiveEntryPipelineTest` 末尾）

| 用例 | 验证行为 | 关键断言 |
|---|---|---|
| `test_manual_entry_reaches_l1_disposition_with_full_evidence` | 五入口 → L1 处置全链路 | 中间态 `REACHABLE` / `PROVEN`；`patch_outcome=PATCHED`；`gate_outcome=L1`；终态 `DISPOSED_L1`；`repo.branches={verifix/<id>}`、PR source/target 正确；`verify_chain`；6 类步骤 DONE；gate attempt `PASSED` + 红绿配对 + 回归零失败；处置视图 `conclusion_trusted=true` |
| `test_webhook_replay_after_disposition_has_no_duplicate_side_effects` | 重复 Webhook 重放 | 两次响应 data 完全一致；重放前后 8 维快照（issues/branches/PR/merged/dispositions/events/status/pending）逐项相等；终态仍为 `DISPOSED_L1` |
| `test_resume_after_interruption_keeps_status_and_evidence` | 中断 → 重启 → 续跑 | 重放 Outbox 后状态不变；Proof 序列化内容一致；事件链长度不变；`T1` 回放被状态机以 `illegal source state` 拒绝；续跑后达成 `DISPOSED_L1`，分支仅一份 |
| `test_disposition_api_rejects_unresolvable_run_evidence` | 证据引用不可解析 | `runs/...` 证据缺失时 API 返回 HTTP 500 + `VF-7001` + “证据缺失”；恢复为可解析引用后返回 200 且 `evidence_ok/conclusion_trusted` 为真 |
| `test_main_branch_push_is_skipped_without_creating_issue` | `main` 推送不触发自动修复 | 202 + `skipped=true` + `issue_id=null` + reason 含 `main`；issues 与 outbox 无新增 |

断言均为行为级：返回状态、错误码、事件链完整性、副作用计数、证据一致性，未使用“仅非空”“常量无关”类弱断言。

---

## 3. 执行验证（工具输出）

```bash
.venv/Scripts/python.exe -m pytest backend/tests/test_e2e_pipeline.py -q --tb=short --timeout=60
# 10 passed, 1 warning in 4.61s
```

全量回归：

```bash
.venv/Scripts/python.exe -m unittest discover -s backend/tests -p "test_*.py"
# Ran 809 tests in 54.533s
# OK
# PERF-02 1100 issues / 12000 events capture: 197.0ms（通过，未改断言）
```

用例数由 804 增至 809（新增 5 个）。

---

## 4. 覆盖率（coverage.py，分支模式）

命令：

```bash
.venv/Scripts/python.exe -m coverage run --branch --rcfile=NUL -m pytest \
  backend/tests/test_e2e_pipeline.py backend/tests/test_metrics_e2e.py \
  backend/tests/test_state_machine.py backend/tests/test_state_machine_paths.py \
  backend/tests/test_gate.py backend/tests/test_patcher.py backend/tests/test_patcher_gateway.py \
  backend/tests/test_repo_and_service.py backend/tests/test_guards.py \
  backend/tests/test_reproducer.py backend/tests/test_intake_replay.py \
  -q --tb=short --timeout=60
# 152 passed, 56 subtests passed

.venv/Scripts/python.exe -m coverage report --rcfile=NUL -m --precision=2 \
  backend/app/orchestration/*.py backend/app/agents/critic/service.py \
  backend/app/agents/gatekeeper/service.py backend/app/agents/patcher/service.py \
  backend/app/agents/patcher/guard.py backend/app/agents/reproducer/service.py \
  backend/app/intake/service.py backend/app/intake/triggers.py \
  backend/app/intake/schedule.py backend/app/dashboard/evidence_view.py \
  backend/app/tracing/service.py
```

| 模块 | 覆盖率 |
|---|---:|
| `orchestration/state_machine.py` | 100.00% |
| `orchestration/guards.py` | 100.00% |
| `orchestration/service.py` | 85.25% |
| `agents/critic/service.py` | 100.00% |
| `agents/gatekeeper/service.py` | 94.32% |
| `agents/reproducer/service.py` | 83.12% |
| `agents/patcher/guard.py` | 90.48% |
| `intake/service.py` | 100.00% |
| `intake/schedule.py` | 95.56% |
| `intake/triggers.py` | 81.42% |
| `dashboard/evidence_view.py` | 83.67%（本轮由 67.35% 提升） |
| **链路范围合计** | **87.08%**（1318 语句 / 230 分支） |

低于 80% 的两个文件不属本轮新增行为：

- `agents/patcher/service.py` 65.03%：缺口集中在模型降级网关与生成失败分支（`180-212`、`224-235`），需 `ModelGateway` 桩另行补测；
- `tracing/service.py` 65.24%：缺口集中在判定超时、可疑降级、人工复核分支（`236-257`、`270-292`、`312-340`），属 §13.1 之外的可达性专项。

本轮未修改这两处生产代码，也未通过放宽断言的方式抬高覆盖率。

---

## 5. 遗留与建议

1. **真实 kill 续跑**：需 RDS/Redis 持久化 `outbox`、`run`、`event chain`，再以子进程 `SIGKILL` + 重启驱动；在完成前 §13.2 保持未勾选。
2. **补丁降级链路**：为 `ModelGateway` 增加预算超限/输出拒绝/语法错误三类桩，可把 `agents/patcher/service.py` 提到 ≥80%。
3. **可达性专项**：`tracing/service.py` 的超时与复核分支建议独立补测，避免与端到端链路耦合。

---

## 6. 一句话

> 五入口到 L1 处置的链路、重放幂等与进程内 Outbox 续跑已由 10 个端到端用例锁定，链路范围覆盖 87.08%；唯一没有兑现的是“真实进程 kill 后跨进程续跑”，因此 §13.2 记进展、不记完成。