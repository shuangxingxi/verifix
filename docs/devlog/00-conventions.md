# 开发留痕提交规范

本规范用于满足赛题 1「需求理解 → 代码生成 → 项目构建 → 问题修复 → 部署上线」五步留痕要求。留痕从 D1 开始，不允许事后补造。

## 1. 提交前缀

| 步骤 | 前缀 | 对应产物 |
|---|---|---|
| ① 需求理解 | `[step-1/requirement]` | `docs/devlog/01-requirement.md`、接口草案 |
| ② 代码生成 | `[step-2/codegen]` | 带时间戳的实现提交 |
| ③ 项目构建 | `[step-3/build]` | 构建日志、产物 digest |
| ④ 问题修复 | `[step-4/bootstrap]` | VeriFix 自举 Issue → 补丁 → PR |
| ⑤ 部署上线 | `[step-5/release]` | 发布单、灰度与回滚演练 |

示例：

```text
[step-2/codegen] 实现状态机 17 条主迁移与运行期守护
[step-3/build] 构建 pytest + docker 镜像并记录 digest
```

## 2. 硬性要求

1. 每个步骤至少一条可检索提交，前缀与步骤严格对应。
2. 提交信息带 Issue 标识（如有）：`[step-4/bootstrap] fix ISS-xxxx boundary condition`。
3. 提交作者必须为真实使用代码智能体的成员，禁止脚本批量伪造提交时间。
4. `docs/devlog/` 下记录与提交时间序列必须单调递增；脚本 `scripts/check_devlog.py` 负责校验。
5. 代码智能体对话记录导出为 PDF 归档到 `docs/devlog/`，并同步至 OBS。
6. 基线提交（`[vcs-baseline]`）不归属任何步骤，不计入步骤提交计数；步骤提交要求自基线提交之后生效。

## 3. 当前仓库状态

### 3.1 版本控制基线

工作区已于 2026-11-18 初始化为 Git 仓库：分支 `main`，唯一基线提交标识 `vcs-baseline/<短标识>`（短标识取提交 SHA 前 12 位；具体值以 `docs/devlog/vcs-baseline.md` 摘要段引用的 `.evidence/git-baseline/baseline-meta.json` 为准），入库与排除计数、追溯清单摘要（`manifest_digest`）以 `docs/devlog/vcs-baseline.md` 摘要段为准。

### 3.2 前版本控制期留痕

前版本控制期（D1 留痕起至基线提交前）的历史事实：工作区尚未初始化为 Git 仓库，五步留痕先以 `docs/devlog/` 文件与归档副本留存；仓库初始化后按本规范补建提交序列，并保持文件时间早于首个实现提交。该区间内证据的产生时间以文件记录时间与归档副本为准，禁止以提交时间推断证据产生时间。

### 3.3 自基线起的提交要求

自基线提交起，后续变更须新增提交；基线提交豁免步骤前缀，不计入任何步骤的提交计数。

## 4. 指标口径索引（2026-11-12 起）

主流程指标复算（M1–M9）的口径以 `docs/devlog/metrics-report.md` 与归档 `docs/devlog/metrics/RPT-*.md|json` 为准：

| 指标 | 证据源 | 口径要点 |
|---|---|---|
| M1 / M3 | 已完成评测运行结果 | 评测通道口径，正例+边界体检出；摘要不符即拒绝 |
| M2 | 评测运行结果 | 评测运行未提供显式漏洞检出字段时记 `SOURCE_MISSING`，不本地推导 |
| M4 | `ReproductionAttempt` + `Proof` + `Verdict` | 最新复现尝试为准；`REPRO_FAILED` 计入分母；无尝试的旧数据按 legacy 计数 |
| M5 | `PatchAttempt`(首次) + `GateAttempt` + 处置历史 | 只认首次补丁尝试；无法唯一识别 → 剔除，全量无法识别 → `FIRST_ATTEMPT_EVIDENCE_MISSING` |
| M6 | `GateResult` + `GateAttempt` | 采集源由 v1 的 Pipeline 日志更正；覆盖率容忍默认 0.5pp |
| M7 | `Alert.observed_at` + `Disposition.ready_at` | 禁止用 `decided_at` 估算；时钟回退与缺时区记剔除 |
| M8 | `Disposition` + `GateAttempt` | 分母含未处置 Issue；与 M5 计数单位不可互换 |
| M9 | 自运行采样 JSONL | 心跳超时 + 30s 容许偏差；无采样 `SOURCE_MISSING` |

固定 8 个不可计算原因码：`SOURCE_MISSING` / `DENOMINATOR_EMPTY` / `EVIDENCE_MISSING` / `EVIDENCE_INCONSISTENT` / `COVERAGE_INSUFFICIENT` / `DEFINITION_UNREGISTERED` / `WINDOW_NOT_CLOSED` / `FIRST_ATTEMPT_EVIDENCE_MISSING`。不可计算必须无值，禁止填 0 或估算；剔除比例超过 10% 记 `COVERAGE_INSUFFICIENT`。

历史留痕 `docs/devlog/m5-eval-report.md` 保持只读，不再覆写；新的主流程报告写入 `docs/devlog/metrics-report.md` 并按版本归档。