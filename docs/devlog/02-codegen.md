# 02 · 代码生成留痕

- 记录时间：2026-11-11
- 最后更新：2026-11-14
- 阶段：赛题 1 CodeArts 五步留痕第 ② 步
- 对应提交前缀：`[step-2/codegen]`
- 状态：已归档（回溯整理，附产物摘要；**非当时提交**）

> 说明：本工作区**尚未初始化为 Git 仓库**（见 `docs/devlog/00-conventions.md` §3）。按该节约定，五步留痕先以 `docs/devlog/` 文件与产物摘要留存；仓库初始化后需按 `[step-2/codegen]` 前缀补建提交序列。因此本章**不声称**"当时已提交"，只提供可复算的代码产物清单与摘要，供组委会核对。

## 1. 代码生成范围（按真实开发顺序）

| 阶段 | 时间 | 生成内容 | 产物位置 |
|---|---|---|---|
| M0 地基 | 2026-11-11 | 配置加载即校验、12 类领域对象、状态机 17 主 + 3 辅助迁移、证据链、API 信封、靶场 | `backend/app/`、`verifix-target/` |
| M1–M3 | 2026-11-11 | 可达性判定（多入口择优）、复现造红、最小补丁与六条 diff 审计 | `backend/app/agents/`、`backend/app/patch/` |
| M4–M5 | 2026-11-11 | 五入口、并发、看板回放、50 条评测与报告 | `backend/app/api/`、`scripts/` |
| 指标复算 | 2026-11-12 | 只增不改的尝试历史、快照复算、6 个复算 API、`recalc_metrics.py` | `backend/app/metrics/`、`scripts/recalc_metrics.py` |
| 评测集防泄漏 | 2026-11-13 | `cases`/`expected` 物理隔离、三摘要绑定、执行与裁决分离、四道故障关闭闸门 | `backend/app/eval/`、`eval/cases/`、`eval/expected/` |
| 沙箱真扫 | 2026-11-14 | 双执行域、六项能力门禁、约束验证、靶场真扫、隔离桥接、证据包 | `backend/app/realscan/`、`backend/app/runtime/`、`scripts/run_*.py` |

## 2. 产物规模（2026-11-14 实测）

| 项 | 数量 |
|---|---|
| 后端 Python 文件 | 188 |
| 后端测试文件 | 54（全量 589 用例） |
| 脚本 | 23 |
| 新子项目模块 | 19（`backend/app/realscan/` 18 + `backend/app/runtime/exec_domain.py` 1） |

## 3. 关键文件摘要（sha256 前 16 位，可复算）

| 文件 | 字节数 | sha256 前缀 |
|---|---|---|
| `backend/app/config.py` | 21133 | `61f860c45433335f` |
| `backend/app/main.py` | 34598 | `5b003b34c6dd9596` |
| `backend/app/orchestration/state_machine.py` | 14355 | `5823cf0f3f451974` |
| `backend/app/realscan/models.py` | 16032 | `9c0938107701d730` |
| `backend/app/realscan/scan.py` | 14738 | `45627a504f7ffd11` |
| `verifix-target/app/main.py` | 3361 | `a89709af1aa86c5c` |
| `sandbox/spec.json` | 786 | `bd62277bbae9d6ed` |
| `deploy/docker-compose.yml` | 1080 | `7bb7b087b8ffce0a` |

> 复算命令：`python -c "import hashlib,pathlib;print(hashlib.sha256(pathlib.Path('<file>').read_bytes()).hexdigest()[:16])"`

## 4. 代码生成约束（已遵守）

1. AI 生成代码不引入未声明依赖；新增模块全部使用标准库 + 既有依赖（`pydantic`、`fastapi`、`Flask`）。
2. 每次生成后执行全量回归；2026-11-14 基线为 `≥589 用例、功能性失败 0`（`PERF-02` 单次抖动单独复跑并书面注明）。
3. 未修改靶场源码与真值（`verifix-target/ground_truth.json` sha256 `286d13be…` 未变）。
4. 未修改历史留痕（9 项基线摘要全部一致）。

## 5. 缺口（阻塞，不视为完成）

| 项 | 说明 |
|---|---|
| 提交序列 | 仓库未初始化 Git，`[step-2/codegen]` 提交不存在；`scripts/check_devlog.py` 会列为全局阻塞 |
| 对话记录 PDF | 尚未导出归档与 OBS 同步 |

## 6. 自检

```text
python scripts/check_devlog.py
```

当前预期：本章通过存在性 / 时间 / 前缀正文检查；全局仍因"非 Git 仓库"阻塞（如实输出，不判通过）。