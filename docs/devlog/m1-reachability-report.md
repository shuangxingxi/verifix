# M1 可达性判定报告

- 生成时间：2026-11-11T13:26:03.562358+00:00
- 判定对象：靶场注入点 Issue 10 条
- 可达：10　不可达：0　可疑：0
- 与人工标注一致：10/10

| 编号 | 类别 | 文件:行 | 结论 | 置信度 | 路径 |
|---|---|---|---|---|---|
| TGT-001 | C02 | app/main.py:31 | REACHABLE | 0.9 | app/main.py:user |
| TGT-002 | C02 | app/main.py:41 | REACHABLE | 0.9 | app/main.py:login |
| TGT-003 | C02 | app/main.py:50 | REACHABLE | 0.9 | app/main.py:search |
| TGT-004 | C02 | app/main.py:58 | REACHABLE | 0.9 | app/main.py:order |
| TGT-005 | C02 | app/main.py:66 | REACHABLE | 0.9 | app/main.py:report |
| TGT-006 | C02 | app/main.py:74 | REACHABLE | 0.9 | app/main.py:profile |
| TGT-007 | C03 | app/main.py:81 | REACHABLE | 0.9 | app/main.py:ping |
| TGT-008 | C03 | app/main.py:87 | REACHABLE | 0.9 | app/main.py:convert |
| TGT-009 | C03 | app/main.py:93 | REACHABLE | 0.9 | app/main.py:backup |
| TGT-010 | C03 | app/main.py:99 | REACHABLE | 0.9 | app/main.py:deploy |

报告路径：E:\shuangxingxi\ICT_agent\docs\devlog\m1-reachability-report.md
