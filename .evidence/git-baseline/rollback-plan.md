# 回滚方案与失败恢复（vcs-baseline）

> 生成日期：2026-11-18
> 基线提交：`ecfcad3d8fcaef085e280f70a245546b870eb4d8`（`vcs-baseline/ecfcad3d8fca`）
> 性质：**只出方案与隔离演练，不真实回滚工作区**。

## 1. 断点恢复判定表（14.1）

| 断点 | 判定条件 | 恢复动作 | 是否触碰工作区文件 |
|---|---|---|---|
| 无 `.git` | `git rev-parse` 失败且目录不存在 | 从步骤 1 重跑；已存在的 `.gitignore` / `.gitattributes` 校验内容不变后复用 | 否（仅新增规则文件） |
| `.git` 存在、无提交 | `.git/HEAD` 指向未出生分支，`rev-list --count` 返回 0 或失败 | 删除 `.git/index`（不动 `.git`），重新生成清单，从暂存步骤重跑 | 否 |
| `.git` 存在、1 个基线提交 | `rev-list --count HEAD = 1` 且主题命中 `[vcs-baseline]` | 判定"已完成"，幂等返回既有 `commit_id` 与 `baseline_label` | 否 |
| `.git` 存在、多个提交 | `rev-list --count HEAD > 1` | **停止并输出历史，转人工确认；不得自动 reset、不得自动 rebase** | 否 |

实测佐证：本次 `init --branch main --confirm` 在已完成状态下返回 `already_initialized`、`rev-list --count=1`，未新增提交。

## 2. 主动回滚操作单（14.2）

| 步骤 | 动作 | 校验 | 误删防护 |
|---|---|---|---|
| R1 | 删除 `.git/` | 删除后按 `.evidence/git-baseline/post-commit-manifest.json` 复算工作区，差异数必须为 0 | 只删 `.git`，不删任何工作区文件 |
| R2 | 删除本轮新增文件：`.gitignore`、`.gitattributes`、`.evidence/git-baseline/*`、`docs/devlog/vcs-baseline.md` | 与 E-01 白名单逐项比对 | 删除清单仅限 E-01 白名单四类，**不得多删既有文件** |
| R3 | 按 `docs/devlog/vcs-baseline.md` 的 `original_text` 逐条还原 Tier A 3 处与 Tier B 12 处 | 还原后复算 9 个文件 sha256，必须等于 `.evidence/git-baseline/collect.json` 中的 `pre_sha256` | 逐条按记录还原，不整文件回退 |
| R4 | Tier C 12 个文件与 `m5-eval-report.md` 无需动作 | sha256 必须仍为 `931d20442673b0922a32cfb42de1dcc9996925836607f6ddedbc5e8b1f165502` | 不触碰 |
| R5 | 复跑 `python scripts/check_devlog.py --json` | 必须回到 `blocking_total=3`、`global_blocking` 1 条、`git_commits={}` | 不改脚本 |

## 3. 部分失败处置（14.4）

| 场景 | 判定条件 | 动作 |
|---|---|---|
| 暂存完成但提交失败 | `.git/index` 残留、`rev-list --count` 仍为 0 | 保留 `.git`，删除 `.git/index` 后重算清单并重试；工作区不变 |
| 文件不可读 | `manifest` 返回 `EXIT_MANIFEST_UNREADABLE(3)` 并列出路径 | 提交前中止，不产生部分提交；修复可读性后重跑 |
| 提交成功但 `verify` 失败 | `ac-report.json` 存在 `fail` 项 | **不回滚提交**；先输出失败项。仅当失败属"入库范围错误"时按第 2 节全量回滚后重分类；**禁止用追加提交掩盖失败** |

## 4. 方案自检（14.5）

- 全文不含 `push --force`、`reset --hard`、`clean -fdx`、`checkout --force` 等破坏性命令。
- 所有删除动作限定在本轮新增路径内（`.git` 与 E-01 白名单）。
- 多提交断点明确"停止并转人工"，不提供自动重置路径。

## 5. 隔离副本演练（14.3）

- 副本路径：`C:\Temp\vcsrb-kafjp9yw`（演练后已清理，副本已不存在）。
- 演练方式：复制工作区到临时目录（排除 `node_modules`、`edgeprofile*`、`__pycache__`、`.codebase`、`temp`、`dist`），清单输出置于副本外以避免自引用；先在有 `.git` 状态下生成清单，再删除副本 `.git` 后重新生成。
- 结果：`digest_with_git` 与 `digest_without_git` 均为 `42f8a9bc6e428d85958fb41c89aaa4565058483c22bc66316f0910c0b888d91f`，**差异数 0**（702 条目 / tracked 532）。
- 真实工作区 `.git` 全程存在，未被删除、未执行任何回滚动作。
- 记录文件：`.evidence/git-baseline/rollback-drill.json`。

**边界**：演练范围排除了四个 L2 派生目录与工具缓存，因此不等于对 527 项入库集合逐项验证；但可证明"删除 `.git` 不改变工作区文件字节"这一回滚前提成立。