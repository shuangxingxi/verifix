# M8 隔离桥接报告（容器域零读取）

- 生成时间：2026-11-14
- 结论：**容器域可发布**（`publishable=true`，5 类探针全部拒绝，`exec_success_count=0`）
- 证据：`.evidence/sandbox-realscan/ISO-20261114T164822+0800-3c37`
- 证据 sha256：`840d112b34e664c6054e1957b31f1b83f5dbb4baaab2f2877f3b4d8a679a7fed`
- 验证来源：`REAL_EXECUTION`

## 1. 容器域结论

| 项 | 值 |
|---|---|
| `exec_domain` | `CONTAINER_EXEC` |
| `exec_identity` | `uid=10001,gid=10001` |
| `visible_roots` | `["/cases"]`（仅挂载 `eval/cases:ro`，挂载数 = 1） |
| `enforcement_mode` | `MANDATORY_SELF_CHECK` |
| `publishable` | `true` |
| `exec_success_count` | **0**（由审计归档按 `actor=exec & result=成功` 复算） |
| `audit_ref` | `ISO-*/audit/access.jsonl#run_ref=ISO-20261114T164822+0800-3c37` |

## 2. 五类探针 + 正例 + 诱饵

| 探针 | 目标 | 结果 | 拒绝方式 |
|---|---|---|---|
| enumerate | `/cases/../expected` | DENIED | PATH_NOT_EXIST |
| open | `../expected/EVAL-0001.answer.json` | DENIED | PATH_NOT_EXIST |
| relative | 相对路径打开答案 | DENIED | PATH_NOT_EXIST |
| traversal | 拼接 `..` 穿越 | DENIED | PATH_NOT_EXIST |
| symlink | `/cases/expected-link` | DENIED | PATH_NOT_EXIST |
| decoy_expected | `/decoy-expected/secret.txt` | DENIED | PATH_NOT_EXIST |
| decoy_shadow | `/etc/shadow` | DENIED | **PERMISSION_DENIED** |
| positive control | `/cases/EVAL-0001.json` | READABLE（正例） | — |

- 拒绝方式分布：`PATH_NOT_EXIST=6`、`PERMISSION_DENIED=1`、`UNKNOWN=0`，两类拒绝均真实可观测。
- **口径说明（如实披露）**：`decoy-expected` 目录经 Windows 文件系统透传到容器，权限位不可控，因此以 `PATH_NOT_EXIST` 形式被拒；"权限拒绝"分支由容器内 `/etc/shadow`（root:root 0600，执行身份 10001）提供，证明 EACCES 可观测，且**不依赖任何答案内容**。
- 零读取的实质保障：只挂载 `eval/cases:ro`，`eval/expected` 根本不在容器可见面内；不依赖文件权限位。

## 3. 双轨口径

| 执行域 | 结论用途 | `publishable` | 强制自检行为 |
|---|---|---|---|
| `HOST_USER`（宿主同用户，历史与过程记录） | 过程记录，不作对外结论 | `false` | 可读即拒绝启动（`VF-8003`） |
| `CONTAINER_EXEC`（本轮容器域） | **对外口径** | `true` | 探针全部拒绝才通过 |

- 宿主域历史结论保留、不删除；`eval_leak_hardening` 阶段"同用户可读导致评测拒绝启动"的记录仍有效。
- 本轮容器域 `exec_success_count=0`，审计归档可按 `run_ref` 检索到 `exec` 与 `control` 两类记录。

## 4. K-02 分类说明（故障关闭一处不放）

- 宿主域读不到答案（`ok=true`）时 `publishable=false`，只记录、不对外发布。
- 宿域可读取答案时：`failure_kind=EXEC_DOMAIN_MISMATCH`，**仍抛 `VF-8003` 拒绝启动**，不计入隔离缺陷统计。
- 容器域可读取答案时：`failure_kind=ISOLATION_DEFECT`，同样抛 `VF-8003`。
- 用例不可读 → `PROBE_INVALID`；运行时不可用 → `RUNTIME_UNAVAILABLE`；五条失败分支全部抛错，**放行分支数 = 0**（单测断言）。

## 5. 与评测链路的关系

- 答案目录唯一成功读取方仍是裁决侧；评测执行身份在容器内对 `expected/` 无可见面。
- `eval/expected`、`eval/runs`、`eval/verdicts` 未被挂载，也未写入。
- 历史 `docs/devlog/m5-eval-report.md` sha256 保持 `931d2044…` 未变。

## 6. 边界声明

1. 本轮结论是**容器域**结论；宿主域仅供过程记录，不得混用。
2. 与 M0/M6 相同的边界：WSL2 内核 ≠ CCE 节点内核，云上需复测。
3. 诱饵目录权限在 Windows 挂载下不可控，已以 `/etc/shadow` 补齐 EACCES 分支，未把 `decoy_expected` 记作 EACCES。

## 7. 复现命令

```text
python scripts/verify_isolation_bridge.py --cases eval/cases --evidence-root .evidence/sandbox-realscan
```

退出码：0=可发布、2=未验证、3=隔离失败（含 `VF-8003`）、4=证据归档失败。