# M4 并发压测报告

- 生成时间：2026-11-11T14:21:42.579819+00:00
- 执行方式：asyncio 并发沿 ConcurrencyController 槽位调度（无 Docker）

| 并发上限 | 任务数 | 完成 | 用时(s) |
|---|---|---|---|
| 3 | 12 | 12 | 0.125 |
| 6 | 12 | 12 | 0.062 |
| 8 | 12 | 12 | 0.063 |

- 文件冲突排队：是；提示：file app/main.py in verifix-target has a parallel task; queued
- 结论：PASS
