# VeriFix · CodeArts 修复闭环验证平台

VeriFix 面向赛题 1「需求理解 → 代码生成 → 项目构建 → 问题修复 → 部署上线」五步留痕，
把「告警可达性判定 → 复现造红 → 最小补丁 → 六条 diff 审计 → 三闸判定 → 灰度发布」做成可回放的状态机，
并用评测集持续校验"检出是否可信、补丁是否一次修好、指标是否可复算"。

- 施工口径以赛题 1（`deliverables/CodeArts方案.md`）为准；`总方案.md` 为赛题 2 口径，冲突时以赛题 1 为准。
- 当前交付形态：Python 3.12 单语言 + 源码运行 + 容器镜像；**云上部署未实测**（见 §10）。

## 1. 能力范围

| 类别 | 名称 | 实现 |
|---|---|---|
| C01 | 依赖漏洞 | 解析 `name==version`，命中独立登记的公开 CVE 事实表 |
| C02 | SQL 注入 | AST 识别 `execute()` 实参的 `%` / `+` / f-string / `.format` |
| C03 | 命令注入 | AST 识别 `os.popen` / `subprocess(..., shell=True)` 拼接 |
| C05 | 硬编码凭据 | 大写敏感名 + 字符串字面量，输出掩码 |

12 类缺陷仅作能力地图上限，本轮**不承诺**全量实现。

## 2. 架构（六层）

```text
接入层   intake/       人工提交、Webhook、指纹幂等、Run 七步初始化
编排层   orchestration/ 18 条迁移守卫、900s 截止、并发/重试/熔断
领域层   domain/       12 类领域对象、11 枚举、不变式
工具层   tools/        沙箱执行器、8 个 MCP 白名单工具、Diff 解析、脱敏
保障层   eval/ + metrics/ + realscan/  评测防泄漏、指标复算、容器域真扫
出口层   api/ + evidence/ + repo/     统一信封、只追加事件链、七步回放
```

关键目录：

```text
backend/app/{config.py,main.py,readiness.py}
backend/app/{intake,orchestration,domain,tools,agents,patch,audit,gate}/ 
backend/app/{eval,metrics,evidence,repo,api}/
backend/app/{realscan,runtime}/       容器约束与真扫
eval/{cases,expected,runs,verdicts}/  用例输入 / 答案 / 运行 / 裁决（物理隔离）
verifix-target/                        Flask 靶场（15 项真值）
sandbox/                              沙箱与靶场镜像定义、隔离策略
deploy/                               compose、CCE、nginx、证书、SQL
scripts/                              构建、评测、复算、真扫、留痕自检
docs/devlog/                          五步留痕与 M0–M8 报告
.evidence/                            只追加证据快照（含 sandbox-realscan）
```

## 3. 快速开始（干净机器 15 分钟）

前置：Python 3.12、`pip`、可选 Docker（容器域验证需要 Docker；**无 Docker 仍可完成评测与指标复算**）。

```bash
# 1) 依赖
pip install -r backend/requirements.txt

# 2) 配置加载即校验（冻结项、阶段超时、沙箱上限）
python -c "import sys;sys.path.insert(0,'backend');from app.config import load_config;load_config();print('config ok')"

# 3) 空转闭环（状态机 + 七步回放）
python scripts/smoke_m0.py

# 4) 指标复算（生成/刷新主报告；主报告已存在可跳过）
python scripts/recalc_metrics.py

# 5) 评测链路：启动 → 驱动 → 裁决 → 专项报告
python scripts/run_eval.py
```

产物：

| 产物 | 路径 |
|---|---|
| 主指标报告 | `docs/devlog/metrics-report.md`，归档 `docs/devlog/metrics/RPT-*.md|json` |
| 评测专项报告 | `docs/devlog/eval-report.md` |
| 运行与裁决 | `eval/runs/EVALRUN-*.json`、`eval/verdicts/` |
| 证据 | `.evidence/`（含 `.evidence/sandbox-realscan/`） |

历史报告 `docs/devlog/m5-eval-report.md` 只读，任何步骤都不会覆写。

> **评测链路前提（重要）**：`run_eval.py` 启动前执行答案隔离自检。若执行身份可读 `eval/expected`，
> 会按设计抛 `VF-8003` 并拒绝启动——宿主同用户域记为"执行域不匹配（HOST_USER）"，容器域可读记为"隔离缺陷"。
> 这是故障关闭行为，**没有**放行开关。
>
> 本机 Windows 同用户环境下该自检必然拒绝，因此"15 分钟出第一份评测报告"需在满足下列前提之一时执行：
> ① 容器域执行（容器内 uid 10001 对答案目录零可见面）；② Linux 原生文件系统上由与答案属主不同的用户执行并 `chmod 700`。
> Windows 的 `/mnt/*` 挂载默认不保留权限位，仅 `chmod` 不足。
> 当前本机状态：自检按预期拒绝（`VF-8003`），该验收项**未完成**，不记为通过。

### Docker / compose 路径（可选）

```bash
cd deploy
cp .env.example .env          # 至少填 VERIFIX_WEBHOOK_SECRET
docker compose up -d --build  # 8443（不使用 80/443）
```

编排结构已用 Compose **v2.26.1** 校验通过（`api` / `mcp` / `sandbox` / `gateway` 四服务，`gateway` 发布 `8443`，卷 `evidence` / `workspace`）；
校验在临时目录使用 `.env.example` 完成，不改动 `deploy/`。服务运行与云上部署**仍未实测**。

本机 Docker 实际入口在 WSL2 Debian（`wsl.exe -d Debian -u root -- docker ...`），Windows 侧路径需做 `wslpath` 映射；
详见 `deploy/README.md`。CCE 清单在 `deploy/cce/`，**未在云上部署**。

## 4. 指标定义与复算

- 口径以 `docs/devlog/metrics-report.md` 与归档 `docs/devlog/metrics/RPT-*.md|json` 为准，定义版本 `v2`。
- M1–M9 的分子/分母与证据源见 `docs/devlog/00-conventions.md` §4；采样、剔除与容许偏差均已登记。
- 8 个不可计算原因码：`SOURCE_MISSING` / `DENOMINATOR_EMPTY` / `EVIDENCE_MISSING` / `EVIDENCE_INCONSISTENT` /
  `COVERAGE_INSUFFICIENT` / `DEFINITION_UNREGISTERED` / `WINDOW_NOT_CLOSED` / `FIRST_ATTEMPT_EVIDENCE_MISSING`。
- 不可计算必须**无值**，禁止填 0 或估算；剔除比例 >10% 记 `COVERAGE_INSUFFICIENT`。
- 复算只读快照、只增不改尝试历史；同一窗口同档并发复算由 `RECALC_CONFLICT` 拦截。

## 5. 五步留痕与报告索引

| 步骤 | 记录 | 状态 |
|---|---|---|
| ① 需求理解 | `docs/devlog/01-requirement.md` | 已归档 |
| ② 代码生成 | `docs/devlog/02-codegen.md` | 已归档（回溯整理，非当时提交） |
| ③ 项目构建 | `docs/devlog/03-build.md` | 已归档（构建真实执行） |
| ④ 问题修复 | `docs/devlog/04-bootstrap.md` | **未执行（阻塞）** |
| ⑤ 部署上线 | `docs/devlog/05-release.md` | **未执行（阻塞）** |

自检：`python scripts/check_devlog.py`（缺失/未执行/时间倒退/前缀缺失均判阻塞，退出码 2）。

阶段报告：

| 报告 | 内容 |
|---|---|
| `m0-sandbox-verification.md` | 沙箱地基 |
| `m1-detect-report.md` / `m1-reachability-report.md` | 检出与可达性（10/10 为**录制桩派生**） |
| `m2-reproduce-report.md` | 复现造红 |
| `m3-patch-report.md` / `m3-e2e-report.md` | 最小补丁与端到端 |
| `m4-*.md` | 并发、演示、灰度、自运行 |
| `m5-eval-report.md` | 50 条评测（**只读**） |
| `m6-sandbox-constraint-report.md` | 容器域约束实测 |
| `m7-target-realscan-report.md` | 靶场真扫（15/15） |
| `m8-isolation-bridge-report.md` | 容器域答案隔离 |
| `sandbox-realscan-index.md` | 证据索引、K/O/Q 表、回归基线 |
| `m9-stage-anchors-review.md` | 六锚点复核：达标/部分达标与阻塞项明示 |
| `m10-code-review.md` | 关键路径代码审查：检查点、问题闭环与设计偏离说明 |
| `m11-coverage-report.md` | 核心判定模块行覆盖 91.86%、分支覆盖 80.68%，G-11 已关闭（含历史基线） |
| `m12-closure-and-blockers.md` | 当前交接结论：`verifix` 61/73、剩余 12 项（含历史冻结基线） |
| `m15-e2e-integration-test-report.md` | §13.2 端到端：五入口→L1 处置、重放零副作用、进程内续跑；链路覆盖 87.08% |

## 6. 容器域真扫（可复现）

```bash
python scripts/build_sandbox_images.py --build-network on
python scripts/run_sandbox_verify.py --policy sandbox/spec.json --p4-05 on --evidence-root .evidence/sandbox-realscan
python scripts/run_realscan.py --scope full --port 0 --exec container --allow-host-fallback on --evidence-root .evidence/sandbox-realscan
python scripts/verify_isolation_bridge.py --cases eval/cases --evidence-root .evidence/sandbox-realscan
```

退出码：`0`=成立/可发布、`2`=未验证、`3`=不成立/失败、`4`=证据归档失败。
证据索引：`.evidence/sandbox-realscan/INDEX.json`（逐文件 sha256 可回读）。

## 7. 安全与凭据

- 凭据只经环境变量注入，不落库、不落盘；出口统一过 `SecretRedactor`，证据写入前再过 `EvidenceScrubber`。
- 证据包遇凭据/答案命中即拒绝落盘（`VF-8012`），不生成半成品目录。
- 运行期沙箱 `--network=none`、`--read-only`、`--cap-drop=ALL`、`no-new-privileges`、`uid 10001`；
  配置层**没有**"放行网络"开关。
- 评测答案目录与用例目录物理隔离；执行与裁决分离；隔离自检失败抛 `VF-8003`，无放行分支。

## 8. 测试与基线

```bash
python -m unittest discover -s backend/tests -p "test_*.py"
```

- 当前：**851 用例**。最近一次全量回归 **851 通过**，功能性失败 0。
- `PERF-02` 的 200ms 判据作用于 `write_block_ms`；抓取端到端耗时只做 `CAPTURE_SLOW` 非阻断告警，
  见 `docs/devlog/perf02-increment-report.md`。
- 靶场自测：`python -m unittest discover -s verifix-target/tests`。

## 9. MCP 工具与接口

- 8 个白名单 MCP 工具，`/api/v1/meta` 暴露名称与 `tool_version`，新增工具需走白名单评审。
- 统一信封：`{"code","message","detail","data"}`；错误码前缀 `VF-7xxx`（指标/证据）、`VF-8xxx`（评测/沙箱）、`VF-9xxx`（凭据）。
- 真扫与约束验证**不新增** API 路由，只提供 CLI + 证据包。

## 10. 已知限制（不得外推）

1. **云上未实测**：无华为云凭据；ECS/CCE/OBS/MaaS/CodeArts 连通性均为 `not_configured`，云端结论标注"云凭据缺失，未验证"。
2. **内核差异**：容器域结论来自 WSL2 内核，不等于 CCE 节点内核。
3. **镜像**：`verifix-sandbox:1.0.0` / `verifix-target:1.0.0` 为本地构建、无远程仓库摘要，镜像更新后须重跑 M6–M8。
4. **字段未采集**：`runtime_driver` / `cgroup_version` 记为 `unknown`，未做本地推断。
5. **待拍板**：O-01…O-06（10 类覆盖 11 键、合成 `.git` 夹具、镜像别名登记、是否暴露 API、运行期 Flask 口径、宿主回退默认开启）。
6. **五步留痕**：④ 自举修复与 ⑤ 发布上线未执行（缺凭据与 Git 远端），`check_devlog.py` 如实判阻塞。
7. **M1 的 10/10** 为录制桩派生，不是真扫；真扫为 M7 的 15/15，两者分母不合并。

## 11. 当前状态（2026-11-22 增量复测）

- 全量回归 **851 用例全部通过**；`PERF-02` 已按写阻塞口径关闭，未放宽阈值
- 任务进度：`verifix` 61/73（当前状态以 `.codeartsdoer/specs/verifix/tasks.md` 为准）、`metrics_recalc` 60/60、`eval_leak_hardening` 230/230、`sandbox_realscan` 302/302
- 剩余 12 项因外部环境/凭据或验收条件未成立而阻塞，逐项状态见 `docs/devlog/m12-closure-and-blockers.md`
- §13.2 端到端：五入口→L1 处置、重放零副作用、进程内 Outbox 续跑已测（链路覆盖 87.08%）；真实 kill 续跑仍阻塞，未勾选
- 五步留痕：①②③ 已归档；④自举、⑤发布未执行（`check_devlog.py` 如实返回 7 条阻塞）
- 覆盖率：核心判定模块行覆盖 **91.86%**（1049/1142）、分支覆盖 **80.68%**（213/264），G-11 已关闭
## 12. 自检入口（M13）

- 命令：`python scripts/selfcheck.py [--scope D1,D2,D3,D4,D5] [--dry-run] [--json]`
- 退出码：`0` 全部通过 / `2` 存在警告或未验证 / `3` 存在阻塞或人工待填
- 归档：`docs/devlog/selfcheck/<run_id>/{report.md,selfcheck.json}`，索引 `docs/devlog/selfcheck/index.json`；入口副本 `docs/devlog/m13-selfcheck-report.md`
- 人工输入：`docs/devlog/selfcheck-manual.md`；草稿 `docs/devlog/selfcheck-manual-draft.md` 只给候选行与定位，不代填级别与结论
- `--allow-writes`：允许 D1-4 执行 15 分钟链路并写 `eval/runs`；`--refresh-evidence`：允许 D1-6 重跑沙箱并写 `.evidence/`
- 默认只读：上述两个开关关闭时，自检不写被检文件与证据库；开启后在报告头部登记豁免范围
- 说明：自检只诊断、定级与排序，不修复被检问题、不补造证据、不改口径
