# M7 靶场真扫报告（容器内闭环）

- 生成时间：2026-11-14
- 结论：**ESTABLISHED**（四项成立条件同时满足，`verdict_missing=[]`）
- 证据：`.evidence/sandbox-realscan/SCAN-20261114T164852+0800-9dfe`
- 证据 sha256：`5268b062a8d992920c5ffefad46d3d89351b5587f8101cb02df745a5fbe4f91d`
- 验证来源：`REAL_EXECUTION`

## 1. 运行形态

| 项 | 值 |
|---|---|
| 靶场 | `verifix-target` 1.0.0（Flask） |
| 运行镜像 | `verifix-target:1.0.0`，`sha256:5d0b0a32cd4c1c7f0a9d758e7c4a6b76c860f2ae2696a2f02a6373ee5b096c69` |
| 网络模式 | `NONE_LOOPBACK`（容器 `--network=none`，靶场与扫描同容器经 `127.0.0.1` 通信） |
| 监听端口 | `42021`（`port_source=DYNAMIC`，内核分配） |
| 数据库 | `/tmp/target.db`（tmpfs，可写；`/src` 不落盘） |
| 镜像依赖 | 运行期 Flask `3.1.3`；静态依赖版本按 `verifix-target/requirements.txt` 检出（**采用默认值，待确认**，O-05） |
| 视图摘要 | `target_view_digest=7ef1e5ed21cb…`（视图排除 `ground_truth.json`/`tests/`/`tools/`/`.git`） |

## 2. 扫描范围

- `scope = {C01, C02, C03, C05}`，`item_count=15`，`full_count=15`，`uncovered_classes=[]` → **15/15**
- 本报告只给条目数与覆盖数，不使用比率型汇总口径。

## 3. 独立检出（15 条，行号与源码一致）

| # | 类别 | 文件 | 行 | 规则 | 掩码片段 |
|---|---|---|---|---|---|
| 1 | C05 | app/config.py | 1 | C05-CRED | `SECRET_KEY = "***"` |
| 2 | C05 | app/config.py | 2 | C05-CRED | `DB_PASSWORD = "***"` |
| 3 | C02 | app/main.py | 31 | C02-SQL | `conn.execute("SELECT id, name FROM users WHERE id = '%s'" % uid)` |
| 4 | C02 | app/main.py | 41 | C02-SQL | `"... WHERE name = '" + username + ...` |
| 5 | C02 | app/main.py | 50 | C02-SQL | `"... LIKE '%" + keyword + "%'"` |
| 6 | C02 | app/main.py | 58 | C02-SQL | `"... WHERE id = " + order_id` |
| 7 | C02 | app/main.py | 66 | C02-SQL | `"... created_at = '" + day + "'"` |
| 8 | C02 | app/main.py | 74 | C02-SQL | `f"... WHERE user_id = {user_id}"` |
| 9 | C03 | app/main.py | 81 | C03-CMD | `os.popen("ping -c 1 " + host)` |
| 10 | C03 | app/main.py | 87 | C03-CMD | `subprocess.call("convert " + name + " out.jpg", shell=True)` |
| 11 | C03 | app/main.py | 93 | C03-CMD | `os.popen("tar czf backup.tgz " + folder)` |
| 12 | C03 | app/main.py | 99 | C03-CMD | `subprocess.run("deploy.sh " + env, shell=True, ...)` |
| 13 | C01 | requirements.txt | 2 | C01-DEP | `requests==2.19.1`（CVE-2018-18074，fixed 2.20.0） |
| 14 | C01 | requirements.txt | 3 | C01-DEP | `PyYAML==5.1`（CVE-2020-1747，fixed 5.3.1） |
| 15 | C01 | requirements.txt | 4 | C01-DEP | `Jinja2==2.10.1`（CVE-2020-28493，fixed 2.11.3） |

- 检出由 AST/正则规则独立产生，CVE 事实表独立登记（`rules.py`），**不由真值文件生成**；C05 原始明文不进入 stdout、证据与报告。
- 定位复核：15 条逐条回读视图源码行，偏移数 0。

## 4. 动态可达性（10 条，动态分母恒为 10）

| 端点 | 方法 | 判定 |
|---|---|---|
| `/user` | GET | REPRODUCIBLE（正常 1 行 → 注入 2 行） |
| `/login` | POST | REPRODUCIBLE（`matched` 严格增大） |
| `/search` | GET | REPRODUCIBLE（`LIKE` 通配绕过，行数增大） |
| `/order` | GET | REPRODUCIBLE（数值型注入 `1 OR 1=1`，行数增大） |
| `/report` | GET | REPRODUCIBLE（计数严格增大） |
| `/profile` | GET | REPRODUCIBLE（数值型注入，行数增大） |
| `/ping` | GET | REPRODUCIBLE（响应含 `VF_INJECTED`） |
| `/convert` | GET | REPRODUCIBLE（退出码 `127 → 0`） |
| `/backup` | GET | REPRODUCIBLE（响应含 `VF_INJECTED`） |
| `/deploy` | POST | REPRODUCIBLE（stdout 含 `VF_INJECTED`） |

- C01/C05 为静态类别，`dynamic_status=STATIC_ONLY`，不进入动态分母。
- 判定同时要求"响应可解析 + 差异稳定"；仅 HTTP 200 不构成可达证据。

## 5. 真值对账（扫描后只读 1 次）

| 项 | 值 |
|---|---|
| `truth_read_count` | 1 |
| `read_phase` | `POST_SCAN` |
| `truth_version` | 1.0.0 |
| `truth_sha256` | `286d13be98fdfc9c18967be8d82e761ab1751ee1aacfc836d599e937b69becb2` |
| `matched` | 15 |
| `missing` / `extra` | `[]` / `[]` |
| `coverage` | 15/15 |

- 扫描期 `scan_phase_truth_reads=0`；`detections.json` 在对账前冻结，对账只写 `reconciliation.json`。

## 6. 边界统计

| 类别 | 计数 | 说明 |
|---|---|---|
| REAL_CONTAINER | 25 | 15 条静态检出 + 10 条动态检查，全部容器内真实执行 |
| RECORDED_STUB | 10 | M1 历史 10/10，**录制桩派生，不是真扫**，分母不合并 |
| CLOUD_CREDENTIAL_MISSING | 1 | 云凭据缺失，未验证 |
| REAL_LOCAL | 0 | 本轮未使用宿主回退 |

- M1 的 10/10 只覆盖 C02/C03 子集，本轮真扫为 15/15 全量；二者不可混用、不可相加。
- 云端部分固定为"云凭据缺失，未验证"，未发起任何云端请求。

## 7. 四项成立条件

| 条件 | 结论 | 依据 |
|---|---|---|
| `target_responded` | 满足 | `/health` 200，监听 42021 |
| `behavior_diff_reproducible` | 满足 | 10/10 动态检查行为可区分 |
| `isolation_effective` | 满足 | `scan_phase_truth_reads=0`，视图无真值文件 |
| `evidence_replayable` | 满足 | stdout JSONL 可解析、证据逐文件摘要可回读 |

## 8. 边界声明

1. 靶场与扫描同容器运行，证明的是"禁网容器内回环真扫成立"，不证明云上网络策略等价。
2. 本轮 15/15 是**自建靶场全量**，不是对外指标承诺，不得写成"检出率 100%"。
3. 运行期 Flask 3.1.3 与 `requirements.txt` pins（flask 1.1.1）不一致，C01 只做静态版本检出（O-05 采用默认值，待确认）。
4. 不得把本报告与 M1 录制桩结论合并。

## 9. 复现命令

```text
python scripts/run_realscan.py --scope full --port 0 --exec container --allow-host-fallback on --evidence-root .evidence/sandbox-realscan
```

退出码：0=ESTABLISHED、2=UNVERIFIED、3=NOT_ESTABLISHED、4=证据归档失败。