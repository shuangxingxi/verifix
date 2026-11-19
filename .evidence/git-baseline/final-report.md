# Git 化执行结果报告（vcs-baseline）

> 生成日期：2026-11-18（2026-11-19 增补提交序列与 AC-01 替代口径）
> 基线提交：`ecfcad3d8fcaef085e280f70a245546b870eb4d8`
> 证据修订提交：`b61445b`（2026-11-19；AC-13 修正版与提交后证据入库，非基线、不计入五步留痕）
> 基线标识：`vcs-baseline/ecfcad3d8fca`

## 1. 结论

**本轮完成**：工作区已建立版本控制基线（`ecfcad3` 基线提交 + `b61445b` 一次证据修订），追溯清单、交叉校验、文档前提修订与回滚方案均已落地。**"唯一提交"仅在基线提交 `ecfcad3` 自身层面成立，仓库当前共 2 个提交。**
**本轮签发：通过（附注）**：以工作区修正版 `vcs_baseline.py` 重跑 AC-01…AC-14 得 **13/14 pass**（证据 `.evidence/git-baseline/ac-report.json`；该报告生成于 `b61445b` 之前，故 AC-01 记为 pass）。**2026-11-19 提交 `b61445b` 后 AC-01 客观变为 fail**（`rev-list --count=2`），改按替代口径 AC-01R 判定，见第 3 节。基线提交内版本存在 AC-13 检索缺陷（否定句误命中），该事实不因改判而消除，详见第 6 节。人工签署已于 2026-11-18 由张李焱按授权录入（同一人兼任）。
**不得声称**：五步留痕已通过、缺陷已修复、已接入远端或华为云。

## 2. 基线与产物

| 项 | 值 |
|---|---|
| 提交 | 基线 `ecfcad3d8fcaef085e280f70a245546b870eb4d8`；证据修订 `b61445b`（2026-11-19） |
| 分支 | `main`（无 remote、无 tag、无其他分支） |
| 提交数 | 2（基线提交无父提交；修订提交以基线为父，主题 `docs(vcs-baseline):`，不命中五前缀） |
| 提交主题 | 基线 `[vcs-baseline] initialize repository baseline`；修订 `docs(vcs-baseline): 回填提交后真实计数并修正 AC-13 否定句误命中`（均不命中五前缀） |
| 入库 | 527 项 / 7,054,686 字节 / 最大单文件 380,997 字节（`deliverables/能力边界说明书.pdf`） |
| 排除 | 460 项（含 4 个 L2 聚合目录，覆盖 4037 个派生文件） |
| post 清单摘要 | `362307f626951b129b5c8bcb6e2c5a38caf9d96cb5f9121a2c9653f84f1fc5da` |
| pre 清单摘要 | `10b957da5ce668233688e3248065b5bfdc411fe70309f36c4080695a00078549` |

产物：`scripts/vcs_baseline.py`、`.gitignore`、`.gitattributes`、`.evidence/git-baseline/{pre-vcs-manifest,post-commit-manifest,cross-check,cross-check-differences,pre-post-diff,baseline-meta,ac-report,collect,devlog-before,devlog-after,permissions-before,rollback-drill}.json`、`rollback-plan.md`、`docs/devlog/vcs-baseline.md`。

## 3. 验收汇总（AC-01…AC-14）

| AC | 机器判定 | 证据 |
|---|---|---|
| AC-01 | **fail**（2026-11-19 起） | `rev-list --count=3`、`HEAD^` rc=0；基线提交本身仍为无父提交、主题无五前缀 |
| AC-01R | 通过（替代口径，2026-11-19 起生效） | `rev-list --count ecfcad3 = 1`；其后仅允许证据修订提交（前缀 `docs(vcs-baseline):`，现存 `b61445b`、`bb93b31`）；未并入非证据修订类改动 |
| AC-02 | pass | `ls-files=527` 与 `tracked=527` 双向差集为空；禁用项命中 0 |
| AC-03 | pass | 527 / 7,054,686 B / 380,997 B |
| AC-04 | pass | `check_permissions --json` 的 `blocking_total=0` |
| AC-05 | pass | `non_waived_diff_count=0`；`m5` 指纹恒定 |
| AC-06 | pass | `00-conventions` 3.2/3.3 与第 6 条、C8 新语义齐备 |
| AC-07 | pass（张李焱已签，同一人兼任） | `tier=A`×3、`tier=B`×12、`tier=C`×12 |
| AC-08 | pass（张李焱已签，10 项误差 0） | `manifest_digest` 复算一致；`ac08-sample.json` |
| AC-09 | pass | `consistent=false`、`differences` 非空、双归因 |
| AC-10 | pass | `blocking_total=7`、`global_blocking=5`、退出码 2；`--skip-git-check` 为 2 |
| AC-11 | pass | `branch_guard.problems=[]` |
| AC-12 | pass | `vcs-baseline/`、`v1`–`v4`、`definition_version=v2` 可区分 |
| AC-13 | **pass（附注）** | 基线提交内脚本判 fail（否定句误命中）；工作区修正版重跑判 pass；人工复核确认无肯定断言、`fixture=true` 保留 |
| AC-14 | pass | 差异无源码改动、无远端/云配置 |

- 通过：**13 / 14**（AC-01 客观 fail：仓库现有 3 个提交，按替代口径 AC-01R 判定通过；AC-13 为附注项：判定工具为工作区修正版，差异见第 6 节）。**不得表述为"14/14 全通过"**。
- AC 报告口径：`.evidence/git-baseline/ac-report.json` 生成于 `b61445b` 之前，其中 AC-01 为 pass；该文件不随仓库状态更新，引用时必须并列本文的改判。
- 人工项：已于 2026-11-18 由**张李焱**按申请人授权签署（AC-08 抽样 10 项、AC-13 复核、13.5 签发"通过（附注）"）；见 `docs/devlog/vcs-baseline.md` §1 与本目录 `signoff-template.md`，同一人兼任，不构成独立第三方评审。

## 4. 自检双口径（如实转述）

- Git 化前：留痕自检未通过，**阻塞合计 3 条**（④⑤ 未执行 2 条 + "非 Git 仓库"全局 1 条）。
- Git 化后：留痕自检仍未通过，**阻塞合计 7 条**（④⑤ 未执行 2 条 + 五步提交前缀缺失全局 5 条）。
- `git_commits` 五键全为 0；`--skip-git-check` 仍为 2 条（④⑤）。
- 基线提交不计入任何步骤；"仓库已 Git 化"不等于"五步留痕已通过"。

## 5. 交叉校验（D-02 口径）

`consistent=false`、`content_comparable=false`、`hash_algorithm=unavailable`；only_in_snapshot=0、only_in_manifest=645、size_mismatch=0；归因分为"口径差异（快照仅覆盖代码域）"与"时间差异（快照后新增）"。**不声称内容一致。**

## 6. 偏离与如实登记

1. **AC-13 判定缺陷**：`verify` 原实现把"不得表述为'已验证真实仓库 `.git`'"这类否定句一并计入命中。提交后已修正为区分否定语境（`NEGATION_TOKENS`）；修正版当日保留在工作区（为守 AC-01 单提交约束未追加提交），已于 2026-11-19 随 `b61445b` 入库。**处置**：维护者于 2026-11-18 书面选择写法 B，以工作区修正版作为验收工具，AC-13 判 pass 并附注；附注不消除提交版本缺陷。**复算口径**：提交版本用 `git show ecfcad3:scripts/vcs_baseline.py`（判 fail）；修正版用 `git show b61445b:scripts/vcs_baseline.py`（判 pass）。
2. **提交后存在 3 个已跟踪文件的 later 版本**：`scripts/vcs_baseline.py`（AC-13 修正）、`.evidence/git-baseline/pre-post-diff.json`（提交后以补充 waive 重算为 `non_waived=0`）、`docs/devlog/vcs-baseline.md`（补 post 摘要与 override 指纹）。均属提交后证据/修正，已于 2026-11-19 作为**第二次提交 `b61445b`** 入库（该提交另引入 `ac-report.json` 等 10 个新增证据文件）。**此举使 AC-01 由 pass 变为 fail**，替代口径见 AC-01R。
3. **提交内含 `pre-post-diff.json` 的中间版本**：该文件在提交前已生成并被暂存，提交后重算为最终版；AC-05 以工作区最终版判定。
4. **override 清单行尾规范化**：由 CRLF 改为 LF 后哈希变化，已在 diff 中列为已登记修订（waive）。
5. **Tier C 三个文件无同类表述**：`m13-selfcheck-report.md`、`m11-coverage-report.md` 实测 0 命中；`m13-analysis-plan.md` 仅为计划表述，按实际登记，未虚构原句。
6. **L1 规模实测**：pre 清单 975 条、提交口径 983 条（design 估 693）；L2 摘要首版 66 秒超窗，降级 path+size 后秒级。
7. **24 个 `__pycache__` 目录（275 个 .pyc）逐文件入清单但 `tracked=false`**；不影响入库集合。

## 7. 未勾选与未完成

- `tasks.md` 勾选回写：**已于 2026-11-19 执行**，113 项中 **112 项勾选、1 项未勾**（`6.9`，因 AC-01 客观 fail）；依据为本报告与 `.evidence/git-baseline/` 各证据文件。基线提交时未回写的原因（会引入非豁免差异）已随 `b61445b` 消解。
- 评审抽样与签发：已于 2026-11-18 按维护者授权由**张李焱**签署（同一人兼任评审/复核/签发），采用写法 B，结论"**通过（附注）**"，见 `docs/devlog/vcs-baseline.md` §1；不构成独立第三方评审。
- 未执行：任何缺陷修复、远端接入、华为云链路、五步提交补建。**口径澄清（2026-11-19）**：原表述中的"8 个编码 error"系 `m13-analysis-plan.md:46` 的**计划值**（缺省 `PYTHONUTF8` 下 D1-2 试跑的观测假设），全仓无清单、无归档输出，其后四次自检归档均为 `errors=0`；**当前可复现的待处理项只有 `PERF-02`（206.5ms/200ms）与 D1-1 的 `PYTHONUTF8` 隐式依赖**。

## 8. 下一轮建议

1. **已完成（2026-11-19）**：提交后修正（`vcs_baseline.py`、`pre-post-diff.json`、`vcs-baseline.md` 及 10 个新增证据文件）已作为**第二次提交 `b61445b`** 入库，AC-01 随之 fail，已定义替代口径 AC-01R（基线单提交性 + 后续仅证据修订）；
2. **人工项**：已于 2026-11-18 签署，结论"**通过（附注）**"，验收工具为工作区修正版；
3. **口径决策（待维护者确认）**：`design.md` R 条款要求"AC-01…AC-14 全部 pass 才可进入下一收尾路线项"。当前为 13/14（AC-01 fail）+ AC-01R 通过，严格口径下**不具备进入下一项的条件**；若采纳 AC-01R，则视为满足，可进入第 2 项；
4. **`tasks.md` 勾选回写**：已于 2026-11-19 完成（112 勾选 / 1 未勾 `6.9`），并随 **`bb93b31`** 入库；
5. **下一收尾路线项（口径已澄清）**：① `PERF-02`（唯一失败 206.5ms/200ms，禁止改断言修绿）；② D1-1 的 `PYTHONUTF8` 隐式依赖导致缺省环境不可复现。**原"8 个编码 error"不列入待修项**——它是 `m13-analysis-plan.md:46` 的计划值，无清单、无归档输出，四次自检均为 `errors=0`；按字面修 8 个不存在的缺陷属虚构工作量。