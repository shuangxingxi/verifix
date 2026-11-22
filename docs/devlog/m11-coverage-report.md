# M11 核心判定模块覆盖率报告

## 当前结论（2026-11-22 增量复测）

- 工具：`.venv/Scripts/python.exe -m coverage run --branch`（coverage.py）
- 口径：分别报告**行覆盖率**与**分支覆盖率**；不把 `coverage report` 的“语句 + 分支”综合值当成分支覆盖率
- 范围：`orchestration/`、`agents/gatekeeper/`、`agents/critic/`、`agents/patcher/`
- 核心测试：**115 个测试 + 56 个子测试，0 失败、0 错误**
- 行覆盖率：**91.86%**（1049/1142）
- 分支覆盖率：**80.68%**（213/264）
- 结论：**达到 tasks §13.1 的 80% 门槛，G-11 关闭**

关键模块：

| 模块 | 行覆盖 | 分支覆盖 | 结论 |
|---|---:|---:|---|
| `orchestration/state_machine.py` | 100%（178/178） | 100%（12/12） | 达标 |
| `agents/critic/service.py` | 100%（143/143） | 100%（38/38） | 达标 |
| 核心判定范围总计 | **91.86%**（1049/1142） | **80.68%**（213/264） | **达标** |

本轮新增 11 个测试：

- 状态机异常到 API 错误的完整上下文转换、审计拒绝后补丁缺失的 fail-closed 路径。
- 审计输入证据缺失、IO 允许/拒绝边界、未转绿、回归失败、扫描配置篡改、缺失回归文件。
- 门禁 L2/L3 分流、告警事件、回滚记录、非门禁状态拒绝及不开 PR 的负向副作用。

断言覆盖返回状态、错误码、完整错误消息、事件/处置记录、调用参数和负向副作用。另修正 Git 化后已过期的留痕测试预期，不再断言“非 Git 仓库”，并保留 7 条真实阻塞的校验。

13.1 收口时全量回归执行 804 个测试，除当时既有 `PERF-02` 计时抖动外其余 803 个通过；该历史口径已由同日 PERF-02 修复关闭。当前全量为 **851/851 通过**，见 `docs/devlog/perf02-increment-report.md`。

复现：

```bash
.venv/Scripts/python.exe -m coverage run --branch --rcfile=NUL -m pytest \
  backend/tests/test_state_machine.py backend/tests/test_gate.py \
  backend/tests/test_patcher.py backend/tests/test_repo_and_service.py \
  backend/tests/test_guards.py backend/tests/test_state_machine_paths.py \
  backend/tests/test_patcher_gateway.py -q --tb=short --timeout=15
.venv/Scripts/python.exe -m coverage report --rcfile=NUL -m \
  backend/app/orchestration/*.py backend/app/agents/gatekeeper/*.py \
  backend/app/agents/critic/*.py backend/app/agents/patcher/*.py
python -m unittest discover -s backend/tests -p "test_*.py"
python -m unittest backend.tests.test_metrics_perf.PerfTest.test_perf02_thousand_issues_and_twelve_thousand_events -v
```

> 注意：`coverage json` 的总计包含测试过程中导入的其他模块；上述核心指标仅聚合本节“范围”列出的目录。旧 `scripts/measure_coverage.py` 在模块导入后才启动追踪，产生的是保守下界，不再用于关闭 G-11。

---

## 历史基线（2026-11-14，保留原文）

- 工具：`scripts/measure_coverage.py`（标准库 `sys.settrace` + `dis.findlinestarts`）
- 当时口径：**行覆盖率**；`coverage.py` 不可用，分支覆盖率未度量
- 当时结论：**未达标**（总计 54.5%），缺口记为 G-11，13.1 不勾选

## 1. 为什么要替代口径

`pip install coverage` 返回 `No matching distribution found for coverage`，无法通过 PyPI 获取。为不阻塞度量，使用标准库实现：

- `sys.settrace` 只记录被测目录内的 `line` 事件；
- `dis.findlinestarts` 递归提取可执行行（含嵌套 code object）；
- 覆盖率 = 已执行行 / 可执行行。

**与 `coverage --branch` 的差异**：不统计条件跳转是否双分支都走过，只证明"该行被执行过"。因此本报告不能声称"分支覆盖率达标"，只能作为行覆盖证据。

## 2. 实测结果

| 模块 | 覆盖 | 已执行/可执行 |
|---|---|---|
| `agents/critic/service.py` | 61.6% | 125/203 |
| `agents/gatekeeper/service.py` | 53.3% | 153/287 |
| `agents/patcher/gateway.py` | **49.6%** | 63/127 |
| `agents/patcher/guard.py` | 52.0% | 38/73 |
| `agents/patcher/service.py` | 42.5% | 80/188 |
| `agents/patcher/templates.py` | 69.2% | 173/250 |
| `orchestration/guards.py` | **60.5%** | 49/81 |
| `orchestration/service.py` | 61.0% | 47/77 |
| `orchestration/state_machine.py` | **45.6%** | 104/228 |
| **总计** | **54.5%** | 651/1192 |

- 测试运行：**104 条**（状态机 / 门禁 / 补丁 / Repo / 守卫 / 全路径 / 模型网关），0 失败 0 错误。
- 本轮新增 `test_guards.py` 13 条（`guards.py` 24.7% → 60.5%）、`test_state_machine_paths.py` 12 条（`state_machine.py` 40.4% → 45.6%）、`test_patcher_gateway.py` 13 条（`gateway.py` 37.0% → 49.6%）。
- **口径说明**：分母包含 dataclass/Protocol/类型定义行，这些行不产生执行事件，会系统性拉低行覆盖率；因此 54.5% 是保守下界。

## 3. 缺口（G-11）

| 文件 | 覆盖 | 主要未覆盖区域 |
|---|---|---|
| `orchestration/state_machine.py` | 40.4% | T3/T4/T5/T8/T8B/T9/T10/T11/T12/T13/T17/T18 的成对成功/拒绝路径、部分守卫的二级条件 |
| `agents/patcher/gateway.py` | 37.0% | Provider 超时/重试、输出解析失败、契约校验分支 |
| `agents/patcher/service.py` | 42.5% | 补丁生成失败、重试、降级路径 |
| `agents/gatekeeper/service.py` | 53.3% | L2 降级、回滚失败、分支删除失败等异常路径 |
| `orchestration/service.py` | 61.0% | 事件映射的次要分支 |

## 4. 下一步补测清单

1. `state_machine`：对 18 条主迁移逐条补"成功 + 前置缺失"两组用例（预计覆盖 30+ 行）。
2. `patcher/gateway`：注入超时 Provider、返回非法 JSON、返回多补丁，验证拒绝与重试。
3. `patcher/service`：补丁生成失败、二次重试、自动生成标记缺失。
4. `gatekeeper/service`：L2 降级、回滚删除失败、Pipeline 不可用。
5. 若后续 PyPI 可达，改用 `coverage --branch` 复测，以分支口径重新判定 80%。

## 5. 复现

```text
python scripts/measure_coverage.py
python scripts/measure_coverage.py --json
```

退出码：0=达标（≥80%）、2=未达标。