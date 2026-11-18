# M11 核心判定模块覆盖率报告（行覆盖替代口径）

- 生成时间：2026-11-14
- 工具：`scripts/measure_coverage.py`（标准库 `sys.settrace` + `dis.findlinestarts`）
- 口径：**行覆盖率**；`coverage.py` 不可用（PyPI 镜像源不可达），分支覆盖率**未度量**
- 阈值：80%（tasks §13.1）
- 结论：**未达标**（总计 54.5%），缺口记为 G-11，13.1 不勾选

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