# 大赛交付台账（DoD 判定）

> 判定日期：2026-11-20
> 判定依据：`.codeartsdoer/specs/competition_delivery/spec.md` §5.1（交付对象定义）、§5.2（分层路由）
> 状态枚举：`DONE` / `PARTIAL` / `BLOCKED` / `NOT_STARTED` / `EVIDENCE_GAP`
> 总判定规则：按最差项收敛，顺序 `BLOCKED > EVIDENCE_GAP > PARTIAL > DONE`。

## 1. 逐项判定

| 编号 | 类别 | 层 | 交付对象 | 状态 | 判定依据 / 证据 |
|---|---|---|---|---|---|
| DLV-A01 | A | L0 | 本机 Git 仓库与证据快照 | **DONE** | 提交自 `ecfcad3` 起累计 ≥9 次、无 remote（计数随迭代只增，不作判定依据）；工作区仅 `.codeartsdoer/package.json`（IDE 插件升版，与交付无关）未提交；AC 13/14 + AC-01R（`a01-repo-snapshot.log`） |
| DLV-A02 | A | L1 | 真实远端仓库与 Issue/PR 留痕 | **BLOCKED** | `reason_code=NO_ACCOUNT`、`fallback=NONE`；无 CodeArts 账号 |
| DLV-B01 | B | L0 | 本机可运行系统 | **DONE** | `smoke_m0` PASS、`recalc_metrics` rc=0、`vue-tsc`+`vite build` 通过（`b01-*.log`） |
| DLV-B02 | B | L0 | 本地容器编排结构 | **DONE** | WSL Debian `docker-compose config` rc=0，4 服务 2 卷（`b02-compose.log`）。**服务运行与云上部署未实测，并列标注** |
| DLV-B03 | B | L1 | 云上 ECS/CCE 部署实测 | **BLOCKED** | `reason_code=NO_CREDENTIAL`；无华为云凭据 |
| DLV-C01 | C | L0 | 本机演示环境 | **DONE** | `demo_rehearsal` 10 项 PASS（`c01-demo.log`）；历史报告已恢复，sha256 校验 OK |
| DLV-C02 | C | L1 | 云上演示入口 | **BLOCKED** | 依赖 DLV-B03；无凭据 |
| DLV-D01 | D | L0 | 方案与架构类材料 | **PARTIAL** | 文件齐全（总方案/CodeArts方案/架构图/能力矩阵）；**`CodeArts方案.md:18` 仍有"队名待补"** |
| DLV-D02 | D | L0 | 能力边界说明书与自攻报告 | **DONE** | md/html/pdf 三形态齐全；`capability-boundary.md` 无占位符 |
| DLV-D03 | D | L0 | 指标口径表 | **DONE** | 本轮产出 `deliverables/指标口径表.md`，覆盖 M1–M9，M9 标"未验证" |
| DLV-D04 | D | L0 | 演示脚本 | **DONE** | 本轮产出 `deliverables/演示脚本.md`，5 段分镜 + 兜底分支 |
| DLV-D05 | D | L0 | 自检报告 | **DONE** | `SC-*-v4` + `m13-selfcheck-report.md`；通过 14 / 阻塞 7 / 人工待填 6 / 未验证 3，退出码 3 如实 |
| DLV-D06 | D | L0 | 评审应答口径卡 | **DONE** | 本轮产出 `deliverables/评审应答卡.md`，8 条可声称 + 7 条不可声称 + 8 个高危问答 |
| DLV-D07 | D | L2 | 演示文稿 PPT | **NOT_STARTED** | 需真人素材与队名定稿；草案不算成片 |
| DLV-D08 | D | L2 | 演示视频 | **NOT_STARTED** | 需录屏环境与讲解人 |
| DLV-E01 | E | L0 | 外部依赖与接入顺序清单 | **DONE** | 本轮产出 `deliverables/外部依赖清单.md`，7 项依赖含 `provided_by` 与首动作 |
| DLV-E02 | E | L2 | 独立第三方评审签署 | **BLOCKED** | 需真实独立评审人；同一人兼任不构成独立评审 |

## 2. 分层汇总

| 层 | 项数 | DONE | PARTIAL | BLOCKED | NOT_STARTED |
|---|---|---|---|---|---|
| L0（本机可完成） | 11 | 10 | 1 | 0 | 0 |
| L1（需外部账号） | 3 | 0 | 0 | 3 | 0 |
| L2（需真人素材/签署） | 3 | 0 | 0 | 1 | 2 |
| 合计 | 17 | 10 | 1 | 4 | 2 |

**L0 层已无 `NOT_STARTED`**，满足 spec 5.2.1-2（可做层必须优先清空）。唯一 L0 未完成项是 `DLV-D01` 的队名占位符，属 `PARTIAL`，任务量约 1 分钟。

## 3. 总判定

**BLOCKED**

原因：存在 4 项 `BLOCKED`（`DLV-A02`、`DLV-B03`、`DLV-C02`、`DLV-E02`）与 2 项 `NOT_STARTED`（`DLV-D07`、`DLV-D08`）。按最差项收敛，交付包不得判为 PASS 或 PARTIAL。

## 4. 解除 BLOCKED 的唯一路径

见 `deliverables/外部依赖清单.md`。最短路径：

1. 用户提供队名 → 关闭 `DLV-D01`（L0 全绿）
2. 用户提供 CodeArts 账号 → `DLV-A02`
3. 用户提供云凭据 → `DLV-B03` → `DLV-C02`
4. 用户提供录屏与签署 → `DLV-D07`、`DLV-D08`、`DLV-E02`

## 5. 不得声称

- 不得声称"交付包已完成"或"可提交评审"——总判定为 `BLOCKED`。
- 不得声称"已上云"、"已接真实 CodeArts"、"已录制演示视频"。
- 不得用 L0 的机器证据替代 L1 实测或 L2 素材证明（spec 5.2.1-6）。