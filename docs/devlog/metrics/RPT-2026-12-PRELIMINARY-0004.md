# 主流程指标报告 RPT-2026-12-PRELIMINARY-0004

- 窗口：2026-12
- 阶段档：PRELIMINARY
- 生成时间：2027-01-06T12:00:00+00:00
- 发起主体：cli
- 结论：PASS

| 指标 | 定义版本 | 值 | 可计算 | 原因码 | 分子 | 分母 | 覆盖 | 剔除 | 通道排除 | 不适用 | 采集源 | 复算标识 | 快照摘要 | 评测运行 | 初赛目标 | 达标 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M1 有效告警率 | v2 | 1.0000 | True | - | 30.0000 | 30.0000 | 30 | 0 | 1 | 0 | 已完成评测运行结果 / eval_run_id=EVALRUN-27714aeffb / definition=v2 | RC-20270106T120000000000-be02be | 09ab94a85169d2166f685f7aa807a786c70f1ccdc5e26695e6e51cfa4be8d21c | EVALRUN-27714aeffb | 0.5000 | True |
| M2 漏洞检出率 | v2 | - | False | SOURCE_MISSING | 0.0000 | 0.0000 | 0 | 0 | 1 | 0 | 已完成评测运行结果 / eval_run_id=EVALRUN-27714aeffb / definition=v2 | RC-20270106T120000000000-be02be | 09ab94a85169d2166f685f7aa807a786c70f1ccdc5e26695e6e51cfa4be8d21c | EVALRUN-27714aeffb | 0.0000 | - |
| M3 可达性判定准确率 | v2 | 1.0000 | True | - | 35.0000 | 35.0000 | 35 | 0 | 1 | 0 | 已完成评测运行结果 / eval_run_id=EVALRUN-27714aeffb / definition=v2 | RC-20270106T120000000000-be02be | 09ab94a85169d2166f685f7aa807a786c70f1ccdc5e26695e6e51cfa4be8d21c | EVALRUN-27714aeffb | 0.0000 | - |
| M4 复现成功率 | v2 | 0.6667 | True | - | 2.0000 | 3.0000 | 3 | 0 | 1 | 0 | ReproductionAttempt + Proof + Verdict / definition=v2 | RC-20270106T120000000000-be02be | 09ab94a85169d2166f685f7aa807a786c70f1ccdc5e26695e6e51cfa4be8d21c |  | 0.6000 | True |
| M5 一次修复通过率 | v2 | 1.0000 | True | - | 2.0000 | 2.0000 | 2 | 0 | 1 | 1 | PatchAttempt(first) + GateAttempt + DispositionHistory / definition=v2 | RC-20270106T120000000000-be02be | 09ab94a85169d2166f685f7aa807a786c70f1ccdc5e26695e6e51cfa4be8d21c |  | 0.4500 | True |
| M6 回归破坏率 | v2 | 0.0000 | True | - | 0.0000 | 2.0000 | 2 | 0 | 1 | 1 | GateResult + GateAttempt / definition=v2 | RC-20270106T120000000000-be02be | 09ab94a85169d2166f685f7aa807a786c70f1ccdc5e26695e6e51cfa4be8d21c |  | 0.0000 | - |
| M7 MTTR | v2 | 30.0000 | True | - | 60.0000 | 2.0000 | 2 | 0 | 1 | 1 | Alert.observed_at + Disposition.ready_at / definition=v2 | RC-20270106T120000000000-be02be | 09ab94a85169d2166f685f7aa807a786c70f1ccdc5e26695e6e51cfa4be8d21c |  | 0.0000 | - |
| M8 自动处置率 | v2 | 0.6667 | True | - | 2.0000 | 3.0000 | 3 | 0 | 1 | 0 | Disposition + GateAttempt / definition=v2 | RC-20270106T120000000000-be02be | 09ab94a85169d2166f685f7aa807a786c70f1ccdc5e26695e6e51cfa4be8d21c |  | 0.0000 | - |
| M9 连续自运行 | v2 | 24.0000 | True | - | 24.0000 | 1.0000 | 1 | 0 | 1 | 0 | runtime self-run samples / definition=v2 | RC-20270106T120000000000-be02be | 09ab94a85169d2166f685f7aa807a786c70f1ccdc5e26695e6e51cfa4be8d21c |  | 24.0000 | True |
