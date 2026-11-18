# 01 · 需求理解留痕

- 记录时间：2026-11-11
- 阶段：M0 地基（赛题 1：CodeArts 五步留痕第 ① 步）
- 对应提交前缀：`[step-1/requirement]`
- 状态：已归档（需求已冻结，见 `00-conventions.md` §3）

## 1. 需求来源

| 文档 | 路径 | 用途 |
|---|---|---|
| 方案（赛题 1 口径） | `deliverables/CodeArts方案.md`（v2.1） | 产品定位、CodeArts 集成语义、指标定义 |
| 需求规格 | `.codeartsdoer/specs/verifix/spec.md` | 10 个能力域、DFX 红线、领域对象约束 |
| 实现方案 | `.codeartsdoer/specs/verifix/design.md` | 六层架构、状态机、接口清单、数据不变式 |
| 任务规划 | `.codeartsdoer/specs/verifix/tasks.md` | 15 主任务 / 71 子任务 |
| 归档副本 | `docs/devlog/specs/` | 三份文档的冻结快照，供组委会核对时间序列 |

## 2. 需求确认过程摘要

本阶段关键分歧与用户拍板结论：

| 编号 | 分歧 | 结论 |
|---|---|---|
| D1 | 赛题口径 | 采用赛题 1（CodeArts 五步留痕）；`总方案.md` 为赛题 2 口径，冲突时以 `CodeArts方案.md` 为准 |
| D2 | 交付范围 | Python 单语言 × C01 依赖 CVE / C02 SQL 注入 / C03 命令注入 / C05 硬编码凭据；12 类仅作能力地图上限 |
| D3 | L0 目标分支 | 自动合并只允许 `release/auto`，任何级别永不自动并入 `main` |
| D4 | 依赖数据源 | OSV 主 + CNVD 兜底，区间冲突取更严并保留来源标记 |
| D5 | 演示靶场 | 自建 Flask 靶场 `verifix-target`（10 注入点 / 3 依赖 CVE / 2 硬编码密钥）+ 1 个开源历史 CVE 复核 |
| D6 | 产品名 / 模型选型 | T1 仅配置与文案可改；T5 通过 Provider 插件替换，编排与提示词结构不依赖具体模型 |

## 3. 模块清单（M0 落地）

| 层 | 模块 | 代码位置 | 状态 |
|---|---|---|---|
| 配置 | 加载即校验（冻结项、阶段超时、沙箱上限） | `backend/app/config.py` | 完成 |
| 领域 | 12 类领域对象 + 11 个枚举 + 不变式 | `backend/app/domain/` | 完成 |
| 编排 | 17 主迁移 + 3 辅助迁移、900s 截止、并发与重试 | `backend/app/orchestration/` | 完成 |
| 接入 | 人工提交、指纹幂等、Run 七步初始化 | `backend/app/intake/` | 完成 |
| 证据 | 只追加事件链、运行回放 | `backend/app/repo/`、`backend/app/evidence/` | 完成 |
| 工具 | 沙箱执行器、8 个 MCP 白名单工具、Diff 解析、脱敏 | `backend/app/tools/` | 完成 |
| API | 统一信封、18 个错误码、healthz / meta / run 回放 | `backend/app/api/`、`backend/app/main.py` | 完成 |
| 靶场 | Flask 靶场 + ground_truth 校验 | `verifix-target/` | 完成 |
| 自检 | 空转闭环 | `scripts/smoke_m0.py` | 完成 |

## 4. 接口草案（M0 已冻结部分）

| 接口 | 方法 | 语义 |
|---|---|---|
| `/healthz` | GET | 存活检查 |
| `/api/v1/meta` | GET | 产品名、分支命名空间、发布分支、时限、并发、模型 Provider |
| `/api/v1/issues` | POST | 人工提交修复任务（受理即返回，幂等） |
| `/api/v1/runs/{run_id}` | GET | 运行实例详情 |
| `/api/v1/runs/{run_id}/events` | GET | 运行事件序列 |
| `/api/v1/runs/{run_id}/replay` | GET | 七步时间线回放 |

## 5. 验证记录

| 检查 | 命令 | 结果 |
|---|---|---|
| 后端单元测试 | `python -m unittest discover -s backend/tests` | 94 项通过 |
| 靶场测试 | `python -m unittest discover -s verifix-target/tests` | 7 项通过 |
| ground_truth 对账 | `python verifix-target/tools/verify_ground_truth.py` | 通过 |
| M0 空转 | `python scripts/smoke_m0.py` | RECEIVED → TRIAGING → SUSPECTED → L2，事件链完整，缺失步骤显式标注 |