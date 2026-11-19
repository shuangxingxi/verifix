# 主流程指标报告 RPT-2026-12-PRELIMINARY-0001

- 窗口：2026-12
- 阶段档：PRELIMINARY
- 定义版本：v2
- 生成时间：2027-01-06T12:00:00+00:00
- 发起主体：cli
- 评测运行：EVALRUN-27714aeffb
- 历史留痕摘要：931d20442673b0922a32cfb42de1dcc9996925836607f6ddedbc5e8b1f165502
- 结论：UNDETERMINED

| 指标 | 定义版本 | 值 | 可计算 | 原因码 | 分子 | 分母 | 覆盖 | 剔除 | 通道排除 | 不适用 | 采集源 | 复算标识 | 快照摘要 | 评测运行 | 初赛目标 | 达标 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M4 复现成功率 | v2 | 0.6667 | True | - | 2.0000 | 3.0000 | 3 | 0 | 1 | 0 | ReproductionAttempt + Proof + Verdict / definition=v2 | RC-20270106T120000000000-f0134f | fd356f9645c75f75be84f00f27bf866820f8dfb34fb3397835b26a0568919ee8 |  | 0.6000 | True |
| M5 一次修复通过率 | v2 | 1.0000 | True | - | 2.0000 | 2.0000 | 2 | 0 | 1 | 1 | PatchAttempt(first) + GateAttempt + DispositionHistory / definition=v2 | RC-20270106T120000000000-f0134f | fd356f9645c75f75be84f00f27bf866820f8dfb34fb3397835b26a0568919ee8 |  | 0.4500 | True |
| M6 回归破坏率 | v2 | 0.0000 | True | - | 0.0000 | 2.0000 | 2 | 0 | 1 | 1 | GateResult + GateAttempt / definition=v2 | RC-20270106T120000000000-f0134f | fd356f9645c75f75be84f00f27bf866820f8dfb34fb3397835b26a0568919ee8 |  | 0.0000 | - |
| M7 MTTR | v2 | 30.0000 | True | - | 60.0000 | 2.0000 | 2 | 0 | 1 | 1 | Alert.observed_at + Disposition.ready_at / definition=v2 | RC-20270106T120000000000-f0134f | fd356f9645c75f75be84f00f27bf866820f8dfb34fb3397835b26a0568919ee8 |  | 0.0000 | - |
| M8 自动处置率 | v2 | 0.6667 | True | - | 2.0000 | 3.0000 | 3 | 0 | 1 | 0 | Disposition + GateAttempt / definition=v2 | RC-20270106T120000000000-f0134f | fd356f9645c75f75be84f00f27bf866820f8dfb34fb3397835b26a0568919ee8 |  | 0.0000 | - |
| M9 连续自运行 | v2 | 未验证 | False | EVIDENCE_MISSING | 0.0000 | 0.0000 | 0 | 0 | 1 | 0 | runtime self-run samples / definition=v2 | RC-20270106T120000000000-f0134f | fd356f9645c75f75be84f00f27bf866820f8dfb34fb3397835b26a0568919ee8 |  | 24.0000 | - |

## 与历史 m5 报告的口径差异对照

| 指标 | 历史值/状态 | 新值/状态 | 差异原因 |
|---|---|---|---|
| M1 | 1.0000（可计算） | 1.0000（可计算） | 历史 m5 报告以单文件评测集口径记 1.0；新口径为裁决后的正例+边界检出率，分母固定 30 |
| M2 | 1.0000（可计算） | -（不可计算，原因码 SOURCE_MISSING） | 历史报告记录 1.0；新口径要求显式漏洞检出字段，缺失即 SOURCE_MISSING，不本地推导 |
| M3 | 1.0000（可计算） | 1.0000（可计算） | 历史报告记录 1.0；新口径分母为有可达性标注样本数，须由裁决结论披露分子分母 |
| M4 | 不可计算 | 0.6667（可计算） | 历史 m5 报告只覆盖评测通道；新口径按 v2 主流程复现证据计算 |
| M5 | 不可计算 | 1.0000（可计算） | 历史 m5 报告未采集首次补丁尝试；新口径取门禁结论与门禁尝试 |
| M6 | 不可计算 | 0.0000（可计算） | 历史文本曾以日志口径描述 M6；新口径采集源为门禁结论与门禁尝试 |
| M7 | 不可计算 | 30.0000（可计算） | 历史 m5 报告未覆盖主流程时效；新口径按告警首次观测与 PR 就绪时间差计算 |
| M8 | 不可计算 | 0.6667（可计算） | 历史 m5 报告未覆盖主流程处置率；新口径按 v2 主流程处置与门禁证据计算 |
| M9 | 24.0000（可计算、达标） | 未验证（不可计算，达标 -） | 历史值来自夹具采样；新口径要求真实运行时连续 24 小时证据，否则为未验证 |

## 验证说明

| 项 | 命令 | 结果 |
|---|---|---|
| 全量回归 | `python -m unittest discover -s backend/tests -p "test_*.py"` | 429 用例通过（实测 2026-11-12） |
| 不变量守护 | `python -m unittest backend.tests.test_metrics_invariants` | 9 用例通过 |
| 性能预算 | `python -m unittest backend.tests.test_metrics_perf` | PERF-01 0.011s / PERF-02 抓取 157ms、复算 0.447s / PERF-04 0.001s |
| 端到端复算 | `python -m unittest backend.tests.test_metrics_e2e` | 8 用例通过 |
| 离线复算 | `python scripts/recalc_metrics.py --window 2026-12 --tier PRELIMINARY --now 2027-01-06T12:00:00+00:00` | 退出码 0，报告版本递增 |

验证边界：本机无 Docker、无华为云凭据、无 redis。外部 CodeArts Check/Governance/Pipeline 均为录制桩；复算只读本地快照；
`RecalcGuard` 为进程内互斥，多实例部署需外部锁（不在本次范围）。M2 在评测运行未提供显式漏洞检出字段时按 `SOURCE_MISSING` 处理，不本地推导。

## 完成定义（DoD）对照

| DoD | 结论 | 证据 |
|---|---|---|
| 1 M4/M5/M7/M8 可计算且可下钻；M6 有门禁可计算 | 通过 | 本报告 M4=0.6667、M5=1.0、M7=30min、M8=0.6667、M6=0.0；`test_metrics_e2e` |
| 2 M9 真实连续运行证据 | 未验证 | 夹具采样不作为转正证据；本报告 M9 值列为“未验证”、达标列为“-” |
| 3 旧报告作为历史留痕保留，新报告取代误导结论 | 通过 | `docs/devlog/m5-eval-report.md` sha256 未变；本报告 M6 按门禁结论与门禁尝试采集 |
| 4 状态机、证据写入语义、main 硬约束零改动 | 通过 | `test_metrics_invariants`（17+3 迁移、main 硬拒） |
| 5 无 Docker/无云凭据/非 Git 环境可执行 | 通过 | 全部验收基于本地 `MemoryStore` + 临时目录 + 录制适配器 |
