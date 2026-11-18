# 主流程指标报告 RPT-2026-12-PRELIMINARY-0003

- 窗口：2026-12
- 阶段档：PRELIMINARY
- 生成时间：2027-01-06T12:00:00+00:00
- 发起主体：cli
- 结论：FAIL

| 指标 | 定义版本 | 值 | 可计算 | 原因码 | 分子 | 分母 | 覆盖 | 剔除 | 通道排除 | 不适用 | 采集源 | 复算标识 | 快照摘要 | 评测运行 | 初赛目标 | 达标 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M1 有效告警率 | v2 | 1.0000 | True | - | 30.0000 | 30.0000 | 30 | 0 | 1 | 0 | 已完成评测运行结果 / eval_run_id=EVALRUN-27714aeffb / definition=v2 | RC-20270106T120000000000-46a7ef | 7fef34c7f60ab6297a3984b4961d8f6f9917d2a5b5efd2456d9a028867b824a2 | EVALRUN-27714aeffb | 0.5000 | True |
| M2 漏洞检出率 | v2 | - | False | SOURCE_MISSING | 0.0000 | 0.0000 | 0 | 0 | 1 | 0 | 已完成评测运行结果 / eval_run_id=EVALRUN-27714aeffb / definition=v2 | RC-20270106T120000000000-46a7ef | 7fef34c7f60ab6297a3984b4961d8f6f9917d2a5b5efd2456d9a028867b824a2 | EVALRUN-27714aeffb | 0.0000 | - |
| M3 可达性判定准确率 | v2 | 1.0000 | True | - | 35.0000 | 35.0000 | 35 | 0 | 1 | 0 | 已完成评测运行结果 / eval_run_id=EVALRUN-27714aeffb / definition=v2 | RC-20270106T120000000000-46a7ef | 7fef34c7f60ab6297a3984b4961d8f6f9917d2a5b5efd2456d9a028867b824a2 | EVALRUN-27714aeffb | 0.0000 | - |
| M4 复现成功率 | v2 | 0.5000 | True | - | 1.0000 | 2.0000 | 2 | 0 | 1 | 0 | ReproductionAttempt + Proof + Verdict / definition=v2 | RC-20270106T120000000000-46a7ef | 7fef34c7f60ab6297a3984b4961d8f6f9917d2a5b5efd2456d9a028867b824a2 |  | 0.6000 | False |
| M5 一次修复通过率 | v2 | 1.0000 | True | - | 1.0000 | 1.0000 | 1 | 0 | 1 | 1 | PatchAttempt(first) + GateAttempt + DispositionHistory / definition=v2 | RC-20270106T120000000000-46a7ef | 7fef34c7f60ab6297a3984b4961d8f6f9917d2a5b5efd2456d9a028867b824a2 |  | 0.4500 | True |
| M6 回归破坏率 | v2 | 0.0000 | True | - | 0.0000 | 1.0000 | 1 | 0 | 1 | 1 | GateResult + GateAttempt / definition=v2 | RC-20270106T120000000000-46a7ef | 7fef34c7f60ab6297a3984b4961d8f6f9917d2a5b5efd2456d9a028867b824a2 |  | 0.0000 | - |
| M7 MTTR | v2 | 30.0000 | True | - | 30.0000 | 1.0000 | 1 | 0 | 1 | 1 | Alert.observed_at + Disposition.ready_at / definition=v2 | RC-20270106T120000000000-46a7ef | 7fef34c7f60ab6297a3984b4961d8f6f9917d2a5b5efd2456d9a028867b824a2 |  | 0.0000 | - |
| M8 自动处置率 | v2 | 0.5000 | True | - | 1.0000 | 2.0000 | 2 | 0 | 1 | 0 | Disposition + GateAttempt / definition=v2 | RC-20270106T120000000000-46a7ef | 7fef34c7f60ab6297a3984b4961d8f6f9917d2a5b5efd2456d9a028867b824a2 |  | 0.0000 | - |
| M9 连续自运行 | v2 | 24.0000 | True | - | 24.0000 | 1.0000 | 1 | 0 | 1 | 0 | runtime self-run samples / definition=v2 | RC-20270106T120000000000-46a7ef | 7fef34c7f60ab6297a3984b4961d8f6f9917d2a5b5efd2456d9a028867b824a2 |  | 24.0000 | True |
