# M10 关键路径代码审查与设计一致性核对

- 审查时间：2026-11-14
- 依据：`.codeartsdoer/specs/verifix/tasks.md` §15.2、`.codeartsdoer/specs/verifix/design.md` §2.1–2.3
- 结论：**审查意见逐条闭环**（2 项已修并加回归，2 项为有书面理由的设计选择）

## 1. 审查范围

| 关键路径 | 文件 | design 对照 |
|---|---|---|
| 状态机与迁移守卫 | `orchestration/state_machine.py`、`orchestration/guards.py` | §2.1 状态机、18 主迁移 + 3 辅助 |
| 闸位判定 | `agents/gatekeeper/service.py`、`domain/models.py::GateResult` | §2.2 三闸与分级处置 |
| 审计规则 | `audit/`、`patch/` | §2.2 六条 diff 审计与强度评分 |
| Repo 权限校验 | `adapters/repo.py` | §2.3 分支命名空间与 `main` 禁写 |
| 脱敏器 | `tools/redactor.py`、`realscan/evidence.py::EvidenceScrubber` | §2.3 凭据四出口 |

## 2. 检查点与结论

| 编号 | 检查点 | 结论 |
|---|---|---|
| C-01 | 18 主迁移 + T0/T5/T8B 辅助迁移均有目标状态与守卫 | 一致；`test_state_machine` 覆盖跳过、无判定、无证据、超限、弱改写、后门、闸位失败等拒绝路径 |
| C-02 | 闸位三条件：`outcome=PASSED`、`red_green_paired`、`regression_zero_fail`、`rescan_new_alerts=0` | 一致；`test_gate` 覆盖 |
| C-03 | 覆盖率容忍 0.5pp | **偏离已修（I-02）**：原先硬编码在状态机，现改为 `TransitionContext.coverage_tolerance_pp`，由 `GatekeeperService` 从 `config.metrics.coverage_delta_tolerance_pp` 注入 |
| C-04 | 门禁回读超时 600s 判失败 | **口径偏差已修（I-01）**：配置默认 540s、上限 600s；`adapters/pipeline.py` 中未使用的 `GATE_READBACK_SECONDS=600` 常量已删除，避免双口径 |
| C-05 | 六条 diff 审计 + 强度评分 + 自动生成标记 | 一致；`test_patcher` 覆盖超限/夹带注释/弱改写/标记缺失 |
| C-06 | `main` 永不写入、自动合并仅 `release/auto`、机器人仅 `verifix/*` 与 `release/*` | 一致；`check_permissions.py` 动态验证 + `test_final_constraints` 固化 |
| C-07 | 脱敏四出口（日志、事件、证据、通知） | **双脱敏器并存**，见 I-03；分工明确且有测试 |
| C-08 | 运行截止 900s | 一致；`guards.RunDeadlineGuard` 编排期强制，`runtime/self_run.check_deadline` 自运行采样，语义均为到达即超时，见 I-04 |

## 3. 问题清单与闭环

### I-01 门禁回读“双口径”与死常量（已修）

- 现象：`config.stage.gate_readback_seconds` 默认 540、上限校验 600；`adapters/pipeline.py` 另有 `GATE_READBACK_SECONDS = 600` 且无任何引用。
- 影响：读者可能误以为回读超时固定 600s，或误用该常量；实际超时由配置决定。
- 处置：删除未使用常量；口径统一为“默认 540s、上限 600s，超出即判失败”，配置层校验已存在。
- 验证：`test_config` 覆盖 600 接受、>600 拒绝。

### I-02 覆盖率容忍硬编码（已修）

- 现象：`state_machine._gate_passed` 使用字面量 `-0.5`，而指标规则 `m5/m6` 读取 `config.metrics.coverage_delta_tolerance_pp`。
- 影响：配置把容忍调为 0.3 时，指标侧与状态机侧判定不一致，可能出现“指标判失败、状态机放行”。
- 处置：`TransitionContext` 新增 `coverage_tolerance_pp`（默认 0.5），`GatekeeperService` 统一注入配置值；新增边界测试（容忍 0.3 时 `-0.3` 通过、`-0.31` 拒绝）。
- 验证：`test_state_machine::test_gate_coverage_tolerance_is_configurable` + 既有 `-0.5/-0.51` 边界。

### I-03 两个脱敏器语义不同（设计选择，书面说明）

- 现象：`SecretRedactor` 含 `generic_secret_literal`（32+ hex 视为凭据）；`EvidenceScrubber` 不含该规则，但含 `secret_key_assignment` 等上下文规则。
- 理由：证据包必须记录 sha256，通用 hex 规则会把摘要误判为凭据并拒绝落盘；日志/传输侧则应更严格。
- 分工：日志与事件出口用 `SecretRedactor`；证据落盘用 `EvidenceScrubber`，并另有 `scrubber_report.json` 记录命中计数。
- 影响：证据包中若出现“裸凭据”仍会被上下文规则拦截；不含上下文的 64 位随机串不会被误杀。

### I-04 截止时间双实现（设计选择，书面说明）

- 现象：`RunDeadlineGuard`（编排强制）与 `self_run.check_deadline`（自运行采样）各自计算剩余时间。
- 理由：前者用于拒绝迁移，后者用于监控采样；两者均为“到达截止即超时”，常量同为 900s。
- 影响：无行为分叉；后续若调整截止时间需同时改 `config.run.deadline_seconds` 与自运行采样口径（已在审查记录中标注）。

## 4. 验证

```text
python -m unittest backend.tests.test_state_machine backend.tests.test_gate backend.tests.test_repo_and_service backend.tests.test_patcher
python -m unittest discover -s backend/tests -p "test_*.py"
python scripts/check_permissions.py
```

- 关键路径测试：66 条通过
- 全量回归：**642 用例全部通过**
- `check_permissions.py`：阻塞 0

## 5. 结论

- 关键路径与 design §2.1–2.3 一致；两处真实偏离已修复并加回归。
- 两处设计选择已书面说明理由与影响，不需要改实现。
- 本轮未发现“守卫形同虚设”或“审计未真正解析输入”的问题；拒绝路径均有正反例探针。