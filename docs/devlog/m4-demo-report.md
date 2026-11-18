# M4 演示排练报告

- 生成时间：2026-11-11T14:55:05.069904+00:00
- 方式：进程内 TestClient + 真实服务链路（local-dev 执行器，无 Docker）

| 检查项 | 结果 | 说明 |
|---|---|---|
| 入口1 人工提交 | 通过 | ISS-0bfc34c6d414 |
| 入口2 定时扫描（幂等） | 通过 | RUN-TRIG-cccee31b5466 / RUN-TRIG-cccee31b5466 |
| 入口3 Repo Webhook | 通过 | accepted |
| 入口4 CVE 订阅 | 通过 | CVE 订阅事件已归一化 |
| 入口5 运行时告警 | 通过 | 运行时告警视为可达性强证据，仍需静态路径补齐 |
| 判定→复现→补丁→审计 | 通过 | PROVEN/PATCHED/PASSED |
| 回放七步 | 通过 | steps=7 events=7 chain=True |
| 熔断与解除 | 通过 | VF-6001 -> CLOSED |
| 暂停与恢复 | 通过 | 自动处置已暂停，任务已排队（QUEUED_BY_PAUSE） |
| 看板六类要素 | 通过 | 在办数=有,级别分布=有,熔断状态=有,连续自运行时=有,失败原因 Top N=有,指标=有 |

结论：PASS

报告路径：E:\shuangxingxi\ICT_agent\docs\devlog\m4-demo-report.md
