# M2 造红验收报告

- 生成时间：2026-11-11T13:39:33.179619+00:00
- 执行后端：local-dev（本机无 Docker；生产必须走沙箱 TOOL-05）
- 判定对象：靶场注入点 Issue 10 条
- 造红成功：10　失败：0　基础设施异常：0

| 编号 | 类别 | 文件:行 | 行为 | 结果 | 说明 |
|---|---|---|---|---|---|
| TGT-001 | C02 | app/main.py:31 | behavioral | PROVEN | 红态确认：behavioral 测试在补丁前失败（local-dev，312ms） |
| TGT-002 | C02 | app/main.py:41 | behavioral | PROVEN | 红态确认：behavioral 测试在补丁前失败（local-dev，328ms） |
| TGT-003 | C02 | app/main.py:50 | behavioral | PROVEN | 红态确认：behavioral 测试在补丁前失败（local-dev，343ms） |
| TGT-004 | C02 | app/main.py:58 | behavioral | PROVEN | 红态确认：behavioral 测试在补丁前失败（local-dev，328ms） |
| TGT-005 | C02 | app/main.py:66 | behavioral | PROVEN | 红态确认：behavioral 测试在补丁前失败（local-dev，328ms） |
| TGT-006 | C02 | app/main.py:74 | behavioral | PROVEN | 红态确认：behavioral 测试在补丁前失败（local-dev，328ms） |
| TGT-007 | C03 | app/main.py:81 | static | PROVEN | 红态确认：static 测试在补丁前失败（local-dev，93ms） |
| TGT-008 | C03 | app/main.py:87 | static | PROVEN | 红态确认：static 测试在补丁前失败（local-dev，94ms） |
| TGT-009 | C03 | app/main.py:93 | static | PROVEN | 红态确认：static 测试在补丁前失败（local-dev，78ms） |
| TGT-010 | C03 | app/main.py:99 | static | PROVEN | 红态确认：static 测试在补丁前失败（local-dev，93ms） |

- 造红率：10/10（验收门槛 ≥6/10）
- 报告路径：E:\shuangxingxi\ICT_agent\docs\devlog\m2-reproduce-report.md
