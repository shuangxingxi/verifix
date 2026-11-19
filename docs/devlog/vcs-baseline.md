# 版本控制基线与留痕追溯口径说明（vcs-baseline）

> 生成日期：2026-11-18
> 上游文档：`.codeartsdoer/specs/git_adoption/spec.md`、`design.md`、`tasks.md`
> 本轮性质：只建立版本控制基线与追溯口径；不修复缺陷、不接远端、不补建五步提交、不改产品代码。

## 1. 摘要

| 项 | 值 |
|---|---|
| 基线标识 | `vcs-baseline/<短标识>`（取提交 SHA 前 12 位；真实值记录在 `.evidence/git-baseline/baseline-meta.json` 的 `baseline_label`；与自检 `v1`–`v4`、`definition_version=v2` 命名空间互不混用） |
| 初始化日期 | 2026-11-18 |
| 分支 | `main`（仅此一个分支，无 remote、无 tag） |
| 提交序列 | 基线 `ecfcad3d8fca`（无父提交，主题不命中五前缀）+ 证据修订 `b61445b`（2026-11-19，主题前缀 `docs(vcs-baseline):`）；后者不计入五步留痕 |
| 清单条目 | 987（提交前 post 清单：L1 逐文件 983 + L2 目录聚合 4） |
| 入库计数 | tracked=true **527** 项 / 7,054,686 字节（约 6.73 MiB） |
| 排除计数 | tracked=false **460** 项（含 4 个 L2 聚合目录，覆盖 4037 个派生文件） |
| pre 清单口径 | 979 条目 / tracked 520 / 排除 459（pre 清单生成于证据文件落盘前；与提交口径的差额归因见 `.evidence/git-baseline/final-report.md` 第 6 节） |
| pre 清单摘要 | `10b957da5ce668233688e3248065b5bfdc411fe70309f36c4080695a00078549` |
| 基线提交对应清单摘要 | `362307f626951b129b5c8bcb6e2c5a38caf9d96cb5f9121a2c9653f84f1fc5da`（post 清单；元数据见 `.evidence/git-baseline/baseline-meta.json`，提交后生成） |
| 自检口径 | 阻塞合计由 3 条变为 7 条；其中全局阻塞由 1 条变为 5 条（两组数字并列，不得单写其一） |

**人工签署（2026-11-18，按维护者授权录入）**

- **AC-08 抽样复核**：10 项（7 个入库项 + secret/answer/derived 各 1）复算误差 **0**，数值未变、结论未改。评审者：**张李焱**。执行方式：AI 复算（`.evidence/git-baseline/ac08-sample.json`）+ 本人授权确认；同一人兼任。
- **AC-13 复核**：`git grep -n "已验证真实仓库"` 命中 13 行，全部为"不得表述为/不声称/必须为 0"的否定句或规范条文，无肯定断言；`fixture=true` 在 7 个文件保留。复核者：**张李焱**（同一人兼任）。**判定**：基线提交内 `vcs_baseline.py` 判 fail（否定句误命中）；以工作区修正版（`NEGATION_TOKENS`）重跑判 **pass**。两版本差异已登记，不因改判而消除。
- **13.5 签发**：**通过（附注）**——以工作区修正版 `vcs_baseline.py` 重跑 AC-01…AC-14 得 **14/14 pass**（证据 `.evidence/git-baseline/ac-report.json`）；基线提交内版本存在 AC-13 检索缺陷，差异与影响见 `.evidence/git-baseline/final-report.md` 第 6 节。维护者：**张李焱**，2026-11-18。（**时点标注**：该 14/14 为 2026-11-18 签署时点口径；2026-11-19 提交 `b61445b` 后 AC-01 客观 fail，改判见下段，签署原文不删改。）

> 上述三处为同一署名人在本人授权下录入，不构成三个独立第三方评审；签署不改变 AC-13 机器项 fail 的事实。

**AC-01 口径变更（2026-11-19，按维护者授权录入）**

- **事实**：仓库现有 5 个提交（`ecfcad3` 基线 + `b61445b`、`bb93b31`、`9b24a95` 三次证据修订 + `bee4720` 收尾项），`git rev-list --count HEAD = 5`、`git rev-parse HEAD^` 成功 → 原 AC-01（`count=1` 且 `HEAD^` 失败）**客观 fail**，不改判为 pass。
- **替代口径 AC-01R**：基线提交自身的单提交性以 `git rev-list --count ecfcad3 = 1` 判定（成立，且主题不命中五前缀）；基线之后仅允许"证据修订提交"，主题须命中前缀 `docs(vcs-baseline):`（现存 `b61445b`、`bb93b31`、`9b24a95`）。**适用范围（2026-11-19 补记）**：本条仅约束"Git 化基线"自身的证据修订，**不约束其后各收尾路线项的提交**（如 `bee4720 docs(perf-repro):`）；不得据 AC-01R 把后续项提交判为违约，也不得据其恢复"单提交"主张。
- **总账**：**13/14**（AC-01 fail）+ AC-01R 通过 + AC-13 附注通过。`ac-report.json` 生成于 `b61445b` 之前，其中 AC-01 记为 pass，引用时须并列本条改判。
- **口径边界**：`design.md` 要求"AC-01…AC-14 全部 pass 才可进入下一收尾路线项"。**2026-11-19 维护者采纳 AC-01R**，据此推进并完成第 2 项（`bee4720`）；后续收尾项不再受 AC-01 单提交约束。
- **`baseline-meta.json` 不改写**：该文件固定 7 字段，`commit_id`/`baseline_label` 指向基线提交 `ecfcad3` 语义正确，不因第二次提交而变更。

**命名空间声明**：`vcs-baseline/<短标识>`、自检口径 `v1`–`v4`、指标定义 `definition_version=v2` 三者互不混用；`v4` 是自检基线编号，不是"第四个提交"。`eval/eval_set.sha256` 的绑定关系未因 Git 化改变。

**禁止表述**：仓库已 Git 化不等于五步留痕已通过。本轮未补建任何步骤提交。

## 2. 前提变更登记表（27 条）

统一说明：Tier A 为原位替换或追加条目，Tier B 为行内追加"前提变更"标注，Tier C 零改动仅登记。所有 `original_text` 均为修订前原文，`revised_at` 为本次执行时刻。

### 2.1 Tier A（3 条）

#### A-1
- doc_path: `docs/devlog/00-conventions.md`
- section: §3（原行 30-32）
- original_text: `## 3. 当前仓库状态` / `工作区尚未初始化为 Git 仓库，五步留痕先以 \`docs/devlog/\` 文件与归档副本留存；仓库初始化后按本规范补建提交序列，并保持文件时间早于首个实现提交。`
- revised_text: 追加三段：`3.1 版本控制基线`、`3.2 前版本控制期留痕`、`3.3 自基线起的提交要求`；原句作为 3.2 "历史事实"完整保留
- revised_at: 2026-11-18T13:10:31+08:00
- basis: spec 5.3-1、5.3-2；基线 `vcs-baseline/<短标识>`
- tier=A

#### A-2
- doc_path: `docs/devlog/00-conventions.md`
- section: §2 硬性要求（原行 22-28）
- original_text: `1. 每个步骤至少一条可检索提交，前缀与步骤严格对应。` / `2. 提交信息带 Issue 标识（如有）：\`[step-4/bootstrap] fix ISS-xxxx boundary condition\`。` / `3. 提交作者必须为真实使用代码智能体的成员，禁止脚本批量伪造提交时间。` / `4. \`docs/devlog/\` 下记录与提交时间序列必须单调递增；脚本 \`scripts/check_devlog.py\` 负责校验。` / `5. 代码智能体对话记录导出为 PDF 归档到 \`docs/devlog/\`，并同步至 OBS。`
- revised_text: 追加第 6 条："基线提交（`[vcs-baseline]`）不归属任何步骤，不计入步骤提交计数；步骤提交要求自基线提交之后生效。"（1–5 条逐字未变）
- revised_at: 2026-11-18T13:10:31+08:00
- basis: spec 5.3-6；基线 `vcs-baseline/<短标识>`
- tier=A

#### A-3
- doc_path: `.codeartsdoer/specs/sandbox_realscan/tasks.md`
- section: 约束表 C8（原行 21）
- original_text: `| C8 | 工作区**非 Git 仓库**，禁止依赖分支/提交/回滚命令；回滚只能 staging + 文件替换 | 验收命令中不出现 \`git \`；\`docs/devlog/00-conventions.md\` §3 已声明 |`
- revised_text: 约束列改为"工作区已 Git 化（基线 `vcs-baseline/<短标识>`）：允许只读 git 查询用于追溯（白名单 `rev-parse`/`log`/`show`/`status`/`ls-files`/`check-ignore`/`cat-file`/`config --get`/`for-each-ref`）；仍禁止依赖分支/提交/回滚作为交付手段；回滚继续以 staging + 文件替换实现；基线提交不计入五步留痕"；验收列改为"不出现写类 git 操作；只读查询命中须说明用途并可回溯"
- revised_at: 2026-11-18T13:10:31+08:00
- basis: spec 5.3-3、5.3-4；基线 `vcs-baseline/<短标识>`
- tier=A

### 2.2 Tier B（12 条）

#### B-1
- doc_path: `.codeartsdoer/specs/eval_leak_hardening/tasks.md`
- section: C3（原行 16）
- original_text: `| C3 | 仓库非 Git 管理，不得依赖分支/提交/回滚命令 | 拆分与发布的回滚只能用 staging + 文件替换实现 |`
- revised_text: 追加"前提变更（2026-11-18）：工作区已 Git 化，C3 的'非 Git'限定不再成立；'拆分与发布回滚只能用 staging + 文件替换'的约束仍然有效。"
- revised_at: 2026-11-18T13:10:31+08:00
- basis: 追加标注，结论不改（spec 5.3.1-2）
- tier=B

#### B-2
- doc_path: `.codeartsdoer/specs/metrics_recalc/design.md`
- section: 前言环境约束（原行 6）
- original_text: `> 环境约束：本机无 Docker、无华为云凭据、非 Git 仓库。本方案所有验收路径均可在进程内 \`MemoryStore\` + 本地文件证据目录下完成，不以真实 Pipeline / CodeArts / OBS 连通为前提。`
- revised_text: 追加"前提变更（2026-11-18）：此句中的'非 Git 仓库'已由版本控制基线取代；'无 Docker、无华为云凭据'两项前提不变。"
- revised_at: 2026-11-18T13:10:31+08:00
- basis: 追加标注；`design.md:189`、`design.md:1438` 的同类短语只登记不改
- tier=B

#### B-3
- doc_path: `.codeartsdoer/specs/metrics_recalc/tasks.md`
- section: 执行前置第 4 条（原行 33）
- original_text: `4. **非 Git 仓库**：不安排任何 git 命令；"分支不得为 main"由 \`LocalRepoAdapter\` 与 \`Patch\` 模型校验断言，不依赖 git 状态。`
- revised_text: 追加"前提变更（2026-11-18）：本条'不安排任何 git 命令'的适用范围截至基线提交；此后只读 git 查询可用于追溯，分支守卫断言仍由模型层校验。"
- revised_at: 2026-11-18T13:10:31+08:00
- basis: 追加标注，原句保留
- tier=B

#### B-4
- doc_path: `.codeartsdoer/specs/sandbox_realscan/spec.md`
- section: 前提修正段（原行 6）
- original_text: `> 前提修正：本机 Docker 已实测可用（WSL2 Debian 13 内 Docker 26.1.5+dfsg1，daemon 运行中）；上一阶段"本机无 Docker"的记录作废，但"无华为云凭据、无 pytest、非 Git 仓库"仍然成立。`
- revised_text: 追加"前提变更（2026-11-18）：'非 Git 仓库'于本日被版本控制基线取代；'无华为云凭据、无 pytest'不变。"
- revised_at: 2026-11-18T13:10:31+08:00
- basis: 追加标注；原有"Docker 已可用"结论未变
- tier=B

#### B-5
- doc_path: `.codeartsdoer/specs/sandbox_realscan/design.md`
- section: §0.2 事实表（原行 56）
- original_text: `| 工作区非 Git 仓库；靶场源码树无 \`.git\` | 环境事实；\`verifix-target/\` 目录实检 | P4-01 只能以"合成等价夹具 + 挂载面裁剪"验证，并标注 \`fixture=true\`，不得声称验证了真实 \`.git\` |`
- revised_text: 追加"〔2026-11-18 前提变更：现已成为 Git 仓库；P4-01 仍以合成夹具为准，`fixture=true` 结论不升级。〕"
- revised_at: 2026-11-18T13:10:31+08:00
- basis: 追加标注；表格行列数未变，`fixture=true` 未改写
- tier=B

#### B-6
- doc_path: `.codeartsdoer/specs/sandbox_realscan/design.md`
- section: §2.6（实际位置 `design.md:520` 与 `design.md:1311`；spec 原表述"`sandbox_realscan/tasks.md` 第 5.4.1"为章节号误指，特此纠偏）
- original_text: `- P4-01 使用合成夹具：\`.evidence/sandbox-realscan/<VER>/fixtures/p4-01/{app/main.py,.git/config}\`；视图仅含 \`app/\`；……若工作区未来成为 Git 仓库，同一视图规则排除真实 \`.git\`，探针无需改动。` 与 `| P4-01 | 非 Git 工作区用合成夹具；未来成为 Git 仓库时同规则适配真实 \`.git\`，无需改探针 |`
- revised_text: 两处均追加"〔2026-11-18：已成为 Git 仓库；同一视图规则继续排除真实 `.git`，探针无需改动；不得表述为'已验证真实仓库 `.git`'。〕"
- revised_at: 2026-11-18T13:10:31+08:00
- basis: 追加标注；位置纠偏声明见本记录 section 字段
- tier=B

#### B-7
- doc_path: `.codeartsdoer/specs/sandbox_realscan/design.md`
- section: §2.8 第 10 条（实际位置 `design.md:1454`；spec 原表述"第 10 条"指向 tasks.md 属误指）
- original_text: `10. 不使用 Git 分支/提交/回滚操作（工作区非 Git 仓库）。`
- revised_text: 追加"〔2026-11-18 前提变更：本条的'工作区非 Git 仓库'不再成立；'不使用分支/提交/回滚作为交付手段'仍然有效。〕"
- revised_at: 2026-11-18T13:10:31+08:00
- basis: 追加标注；未改 `tasks.md`
- tier=B

#### B-8
- doc_path: `.codeartsdoer/specs/sandbox_realscan/design.md`
- section: §5.3 O-02 决策表（原行 1871）
- original_text: `| O-02 | P4-01 以合成夹具验证 | 合成 \`.git\` 夹具 + 视图裁剪；标注 \`fixture=true\` | 是否接受"合成夹具"作为 P4-01 依据；若要求真实 \`.git\`，需先将工作区初始化为 Git 仓库（超出本设计范围） |`
- revised_text: 追加"〔2026-11-18：O-02 的环境前提已变化；选项'要求真实 `.git`'仍不在本轮范围，合成夹具结论保持。〕"
- revised_at: 2026-11-18T13:10:31+08:00
- basis: 追加标注；O-02 原判定未改
- tier=B

#### B-9
- doc_path: `.codeartsdoer/specs/sandbox_realscan/tasks.md`
- section: 明确不做第 6 条（原行 233）
- original_text: `6. **不初始化真实 Git 仓库**：不执行 \`git init\`，不依赖分支/提交/回滚；P4-01 只用合成夹具。`
- revised_text: 追加"〔2026-11-18：本条由后续 Git 化轮次取代；本轮已完成基线初始化，本条对 `sandbox_realscan` 阶段仍然有效。〕"
- revised_at: 2026-11-18T13:10:31+08:00
- basis: 追加标注；"不执行 git init"的历史表述保留
- tier=B

#### B-10
- doc_path: `.codeartsdoer/specs/sandbox_realscan/tasks.md`
- section: T-SBX-20 `basis` 项（原行 650）
- original_text: `- [x] \`basis\` 固定为"合成夹具；工作区非 Git 仓库"，**不得**表述为"已验证真实仓库 \`.git\`"（O-02：采用默认值，待确认）`
- revised_text: 追加"〔2026-11-18：`basis` 原文不改写；工作区已 Git 化，但'不得表述为已验证真实仓库 `.git`'仍然有效。〕"
- revised_at: 2026-11-18T13:10:31+08:00
- basis: 追加标注；`basis` 原句未被替换
- tier=B

#### B-11
- doc_path: `.codeartsdoer/specs/selfcheck_harness/design.md`
- section: §1.2.4 约束段（原行 160）
- original_text: `- **约束**：当前工作区未初始化为 Git 仓库，D5 与 D1 引用其结果时必然得到阻塞；自检必须如实转述，不得以"其他项已通过"抵消。注意其"3 个阻塞"指阻塞条目数，进程退出码仍为 \`2\`。`
- revised_text: 追加"〔2026-11-18：自基线提交起，本约束改为'提交前缀缺失'阻塞；全局阻塞由 1 条变为 5 条、阻塞合计由 3 条变为 7 条，须如实转述。〕"
- revised_at: 2026-11-18T13:10:31+08:00
- basis: 追加标注；原"3 个阻塞"表述保留，全局 1→5 与合计 3→7 并列出现
- tier=B

#### B-12
- doc_path: `.codeartsdoer/specs/selfcheck_harness/tasks.md`
- section: 8.6 验收行（原行 661）
- original_text: `- 验收：\`git diff\`（或文件摘要对比）显示仅新增小节，无既有数值/结论行被修改；\`python scripts/check_devlog.py --devlog docs/devlog --json\` 输出与运行前一致（该脚本当前的非 Git 阻塞结果不得被"抵消"）`
- revised_text: 追加"〔2026-11-18：该'非 Git 阻塞结果不得被抵消'的表述适用范围截至基线提交；基线后以'五步前缀缺失'阻塞为准，同样不得抵消。〕"
- revised_at: 2026-11-18T13:10:31+08:00
- basis: 追加标注；8.6 其他条目与数值未变
- tier=B

### 2.3 Tier C（12 条，零改动）

#### C-1
- doc_path: `docs/devlog/m5-eval-report.md`
- section: 全文只读
- original_text: 全文只读（不改任何字节）
- revised_text: 未改动（仅登记）
- revised_at: 2026-11-18T13:10:31+08:00
- basis: sha256 `931d20442673b0922a32cfb42de1dcc9996925836607f6ddedbc5e8b1f165502`
- tier=C

#### C-2
- doc_path: `docs/devlog/m9-stage-anchors-review.md`
- section: 第 45 行
- original_text: `- \`check_devlog.py\` 当前如实返回阻塞（04/05 未执行 + 非 Git），未通过文案绕过。`
- revised_text: 未改动（仅登记）
- revised_at: 2026-11-18T13:10:31+08:00
- basis: sha256 `37023d93576c87d7aa3adf5aab73e2380a9b95804243171d8ab578c93c5edbfd`
- tier=C

#### C-3
- doc_path: `docs/devlog/m12-closure-and-blockers.md`
- section: 第 17 行
- original_text: `| 五步留痕 | \`check_devlog.py\` 返回 **3 个阻塞**（④⑤ 未执行 + 非 Git），如实 |`
- revised_text: 未改动（仅登记）
- revised_at: 2026-11-18T13:10:31+08:00
- basis: sha256 `d978309738c88091481d345eb836cf1339988141622b2e72a96245da9f77cf65`；该"3"为前版本控制期合计口径
- tier=C

#### C-4
- doc_path: `docs/devlog/m13-selfcheck-report.md`
- section: 全文检索
- original_text: 实测检索 `非 Git`/`git` 命中数为 0（与 spec 假设不符，按实际登记）
- revised_text: 未改动（仅登记）
- revised_at: 2026-11-18T13:10:31+08:00
- basis: sha256 `f557b200cf2223499c28c2cf7ef1695ca0d09ddaecbb369e2ea3c61a48488471`；无前提表述需修订
- tier=C

#### C-5
- doc_path: `docs/devlog/m13-analysis-plan.md`
- section: 第 172 行
- original_text: `3. **15 天够不够？** —— 够，但顺序不能错：**先 Git 化 → 再 CodeArts 真链路 → 再云上 → 最后材料**`
- revised_text: 未改动（仅登记）
- revised_at: 2026-11-18T13:10:31+08:00
- basis: sha256 `ad2d3b9d0fc8d09a1b3d199ae9786733198041f28b82b5af3ab1a569ae6d8bd7`；该行属计划表述而非环境前提，且 8.6 的"末尾追加实施状态"历史任务本轮不得触发
- tier=C

#### C-6
- doc_path: `docs/devlog/m11-coverage-report.md`
- section: 全文检索
- original_text: 实测检索 `非 Git`/`git` 命中数为 0（与 spec 假设不符，按实际登记）
- revised_text: 未改动（仅登记）
- revised_at: 2026-11-18T13:10:31+08:00
- basis: sha256 `e11d1c8c447b3fb4bab7f2dfd9388b769d1f5ff65b9e0451d2ff1797b9632198`
- tier=C

#### C-7
- doc_path: `docs/devlog/03-build.md`
- section: 第 68 行
- original_text: `| 提交前缀 | 非 Git 仓库，无 \`[step-3/build]\` 提交；\`check_devlog.py\` 列为全局阻塞 |`
- revised_text: 未改动（仅登记）
- revised_at: 2026-11-18T13:10:31+08:00
- basis: sha256 `e9609f0f974257ab54db8120d8e43e1c111d43146dc6d5a679ed050d020a94b1`
- tier=C

#### C-8
- doc_path: `docs/devlog/02-codegen.md`
- section: 第 9 行、第 66 行
- original_text: `> 说明：本工作区**尚未初始化为 Git 仓库**（见 \`docs/devlog/00-conventions.md\` §3）。……` 与 `当前预期：本章通过存在性 / 时间 / 前缀正文检查；全局仍因"非 Git 仓库"阻塞（如实输出，不判通过）。`
- revised_text: 未改动（仅登记）
- revised_at: 2026-11-18T13:10:31+08:00
- basis: sha256 `85901087ca8ac6f5fe217f4834bea1016c1c24d4f2a1521602219385c0401991`
- tier=C

#### C-9
- doc_path: `docs/devlog/metrics-report.md`
- section: 第 56 行
- original_text: `| 5 无 Docker/无云凭据/非 Git 环境可执行 | 通过 | 全部验收基于本地 \`MemoryStore\` + 临时目录 + 录制适配器 |`
- revised_text: 未改动（仅登记）
- revised_at: 2026-11-18T13:10:31+08:00
- basis: sha256 `678087b0f98ffb0bc8b39f015c8e20b30a81bab80c6441a7f94e6747247a4480`；数值未变
- tier=C

#### C-10
- doc_path: `docs/devlog/04-bootstrap.md`
- section: 第 15 行
- original_text: `| 仓库形态 | 工作区**不是 Git 仓库**，无法创建分支、提交与 PR |`
- revised_text: 未改动（仅登记）
- revised_at: 2026-11-18T13:10:31+08:00
- 自检输入文件，字节未变；sha256 `002849fa15a3fcc3cd8e21aa0a648cd1d4d57c758fbdc4ebce3dc675067debc0`
- tier=C

#### C-11
- doc_path: `docs/devlog/m6-sandbox-constraint-report.md`
- section: 第 67 行
- original_text: `- **P4-01 纠偏**：\`:ro\` 挂载**不能**阻止进程读取挂载源中的 \`.git\`；本轮改为挂载面裁剪，工作区非 Git 仓库，使用合成 \`.git\` 夹具（\`fixture=true\`），不声称已验证真实仓库的 \`.git\`。`
- revised_text: 未改动（仅登记）
- revised_at: 2026-11-18T13:10:31+08:00
- 字节未变；sha256 `389767d2841769d158756ede7e6c56343859ab53bc768fa63480a8e25602c9cb`
- tier=C

#### C-12
- doc_path: `docs/devlog/sandbox-realscan-index.md`
- section: 第 124 行
- original_text: `6. 未初始化真实 Git 仓库（P4-01 用合成夹具）。`
- revised_text: 未改动（仅登记）
- revised_at: 2026-11-18T13:10:31+08:00
- 字节未变；sha256 `cc7075236a91c9e0c88749bf0cded31164893548ed8e46e155e4f71f373d8b27`
- tier=C

## 3. 排除规则对照

### 3.1 根 `.gitignore` 六段 ↔ `excluded[].reason`

| 段 | 条目 | reason |
|---|---|---|
| 1 依赖缓存 | `frontend/node_modules/`、`**/node_modules/`、`__pycache__/`、`*.py[cod]`、`.pytest_cache/`、`.mypy_cache/`、`.ruff_cache/`、`.venv/`、`venv/`、`env/` | 依赖缓存 |
| 2 用户目录 | `edgeprofile/`、`edgeprofile*/`、`*profile*/` | 用户目录 |
| 3 运行产物 | `.evidence/**/.work/`、`.evidence/**/fixtures/**/.git/`、`frontend/dist/`、`verifix-target/target.db`、`verifix-target/backup.tgz`、`.codeartsdoer/.codebase/`、`.codeartsdoer/temp/`、`*.log` | 运行产物 |
| 4 凭据证书 | `.env`、`.env.*`、`!.env.example`、`*.pem`、`*.key`、`*.pfx`、`*.p12`、`deploy/certs/` | 凭据证书 |
| 5 答案 | `eval/`、`verifix-target/ground_truth.json`、`.evidence/redteam-baseline/gt.txt` | 答案 |
| 6 临时调试 | `/dom.txt`、`/err.txt`、`/.patch_fix*.py` | 临时调试 |

### 3.2 override 清单与不 override 清单

- **override（逐条 `git add -f`，禁 `git add -f .`）**：`.codeartsdoer/specs/**` 共 20 个文件、`.codeartsdoer/mcp/mcp_settings.json`、`.codeartsdoer/rule/metadata.properties`、`.codeartsdoer/package.json`、`.codeartsdoer/mem-exp-config.json`、`.codeartsdoer/.gitignore`、`eval/.gitignore`，合计 26 条，见 `.evidence/git-baseline/override-paths.txt`（sha256 `f75ce825f688a5fe3b2bfa08817f916f6cd74926defde86da33b1651665ba7e4`）。
- **不 override**：`.codeartsdoer/.codebase/**`、`.codeartsdoer/temp/**`、`eval/**`（仅 `eval/.gitignore` 例外）。
- **原因**：`.codeartsdoer/.gitignore` 与 `eval/.gitignore` 内容均为 `*`，Git 语义为下层优先，上层 `!` 否定规则无法覆盖，因此只能以 `git add -f` 强制纳入。

### 3.3 L2 目录聚合（D-03）

| 目录 | 文件数 | 大小（字节） | 摘要口径 | role / tracked |
|---|---|---|---|---|
| `frontend/node_modules` | 3135 | 80814136 | path+size | derived / false |
| `edgeprofile` | 368 | 18560722 | path+size | derived / false |
| `edgeprofile2` | 267 | 7378265 | path+size | derived / false |
| `edgeprofile3` | 267 | 7240979 | path+size | derived / false |

若逐文件展开将新增 4037 条，突破 60 秒窗口，故按目录聚合；聚合条目仍登记路径、大小与摘要，满足"含被排除项可复算"。

### 3.4 Tier C 文件指纹（12 个）

| 文件 | sha256 |
|---|---|
| `docs/devlog/m5-eval-report.md` | `931d20442673b0922a32cfb42de1dcc9996925836607f6ddedbc5e8b1f165502` |
| `docs/devlog/m9-stage-anchors-review.md` | `37023d93576c87d7aa3adf5aab73e2380a9b95804243171d8ab578c93c5edbfd` |
| `docs/devlog/m12-closure-and-blockers.md` | `d978309738c88091481d345eb836cf1339988141622b2e72a96245da9f77cf65` |
| `docs/devlog/m13-selfcheck-report.md` | `f557b200cf2223499c28c2cf7ef1695ca0d09ddaecbb369e2ea3c61a48488471` |
| `docs/devlog/m13-analysis-plan.md` | `ad2d3b9d0fc8d09a1b3d199ae9786733198041f28b82b5af3ab1a569ae6d8bd7` |
| `docs/devlog/m11-coverage-report.md` | `e11d1c8c447b3fb4bab7f2dfd9388b769d1f5ff65b9e0451d2ff1797b9632198` |
| `docs/devlog/03-build.md` | `e9609f0f974257ab54db8120d8e43e1c111d43146dc6d5a679ed050d020a94b1` |
| `docs/devlog/02-codegen.md` | `85901087ca8ac6f5fe217f4834bea1016c1c24d4f2a1521602219385c0401991` |
| `docs/devlog/metrics-report.md` | `678087b0f98ffb0bc8b39f015c8e20b30a81bab80c6441a7f94e6747247a4480` |
| `docs/devlog/04-bootstrap.md` | `002849fa15a3fcc3cd8e21aa0a648cd1d4d57c758fbdc4ebce3dc675067debc0` |
| `docs/devlog/m6-sandbox-constraint-report.md` | `389767d2841769d158756ede7e6c56343859ab53bc768fa63480a8e25602c9cb` |
| `docs/devlog/sandbox-realscan-index.md` | `cc7075236a91c9e0c88749bf0cded31164893548ed8e46e155e4f71f373d8b27` |

> 说明：以上 12 个指纹在修订后复算，差异必须为 0；`m5-eval-report.md` 指纹恒定。

## 4. 交叉校验结果（D-02 口径）

- 快照元数据：`rootHash=e7aefa1dd8b076d5d9cfa5439766cb599e385988df533c2ee5532ebf00c4571e`、`fileCount=334`、`timestamp=1794916749441`；快照文件 sha256 `daea4208fd01faa30de2fa5709caa984e78bacaa4df73c5c44f95a21c1c27a12`。
- 校验层级：仅计数 + 路径集合 + 大小；`content_comparable=false`、`hash_algorithm=unavailable`。
- 结果：`consistent=false`（快照 334 项 vs 清单 979 项）；`only_in_snapshot=0`、`only_in_manifest=645`、`size_mismatch=0`。
- 差异归因：①口径差异——快照仅覆盖代码域与部分证据，清单覆盖全量工作区；②时间差异——快照生成后又新增文件。`fileCount` 不同属口径差异，**不判失败**，也不表述为"内容完全一致"。

## 5. 明确不做（8 条）

1. 不补建 `[step-1]`…`[step-5]` 提交，不拆分基线提交，不设置历史时间。
2. 不接入远端、不推送、不配置 CI、不涉及华为云任何真实链路。
3. 不修改任何源码、脚本判定逻辑、历史报告正文与数值（Tier C 字节不变）。
4. 不重算、不覆盖 `.merkle-snapshot.json`；不改其算法与覆盖口径。
5. 不删除任何被排除的派生产物与答案数据（排除仅作用于版本控制纳入范围）。
6. 不修复 8 个编码 error、`PERF-02`、D1-2 失败用例。
   - **口径澄清（2026-11-19）**："8 个编码 error"是 `m13-analysis-plan.md:46` 的**计划值**（缺省 `PYTHONUTF8` 下 D1-2 试跑的观测假设），全仓无清单、无归档输出，其后四次自检归档均为 `errors=0`。本句按"不修复任何缺陷"理解；当前可复现的待处理项只有 `PERF-02` 与 D1-1 的 `PYTHONUTF8` 隐式依赖。
7. 不改变 `check_devlog.py` 的 `0/2/3` 语义与 `--skip-git-check` 用途；本轮脚本差异数 0。
8. 不把"工作区成为 Git 仓库"表述为"五步留痕验收通过"。

## 6. 标准表述

> Git 化前：留痕自检未通过，阻塞合计 3 条（④⑤ 未执行 2 条 + "非 Git 仓库"全局 1 条）。

> Git 化后：留痕自检仍未通过，阻塞合计 7 条（④⑤ 未执行 2 条 + 五步提交前缀缺失全局 5 条）。

> 基线提交不计入任何步骤；"仓库已 Git 化"不等于"五步留痕已通过"。

## 7. 附录：OQ / D / E 决策表（20 条）

### 7.1 OQ-1…OQ-7（均"采用默认值，待确认"）

| 编号 | 事实 | 取法 | 状态 |
|---|---|---|---|
| OQ-1 | `sandbox/` 是否整体入库 | 整体入库（5 文件，`role=source`） | 采用默认值，待确认 |
| OQ-2 | `frontend/dist/` 是否入库 | 排除；部署前需 `npm run build` | 采用默认值，待确认 |
| OQ-3 | 临时调试文件 | 排除 `dom.txt`、`err.txt`、`.patch_fix*.py` | 采用默认值，待确认 |
| OQ-4 | 红队真值 `gt.txt` | 按答案排除，`tracked=false` | 采用默认值，待确认 |
| OQ-5 | `.merkle-snapshot.json` 是否入库 | 入库且只读，元数据冻结 | 采用默认值，待确认 |
| OQ-6 | 默认分支名 | `main` | 采用默认值，待确认 |
| OQ-7 | 是否立即补建五步提交 | 不补建 | 采用默认值，待确认 |

### 7.2 D-01…D-10

| 编号 | 事实 | 取法 | 状态 |
|---|---|---|---|
| D-01 | 嵌套 `.gitignore` 均为 `*`，上层否定无法覆盖 | 不改既有文件，用 `git add -f` override 清单 | 采用默认值，待确认 |
| D-02 | 快照 `hash` 不可复算（334 项 5 种变体 0 匹配），覆盖域不含 docs/specs/deploy/eval | 降级为计数 + 路径集合 + 大小级校验 | 采用默认值，待确认 |
| D-03 | 逐文件展开将达 4000+ 条，突破 60 秒窗口 | L1 逐文件 + L2 目录聚合 | 采用默认值，待确认 |
| D-04 | `eval/` 与 `eval_set.sha256` 入库冲突 | `eval/**` 不入库，`eval_set.sha256` 仅工作区校验 | 采用默认值，待确认 |
| D-05 | `verifix-target/` 需最小粒度排除 | 保留父目录，仅排 `ground_truth.json`、`target.db`、`backup.tgz` | 采用默认值，待确认 |
| D-06 | `deploy/certs/server.crt` 是否属私钥材料 | 整目录排除，reason=凭据证书 | 采用默认值，待确认 |
| D-07 | Tier C 实为 12 个文件 | 增补 `04-bootstrap.md`、`m6-sandbox-constraint-report.md`、`sandbox-realscan-index.md`，零改动 | 采用默认值，待确认 |
| D-08 | `deliverables/` 未在 spec 输入清单点明 | 18 文件按交付材料入库，`role=source` | 采用默认值，待确认 |
| D-09 | 需新增根 `.gitattributes` | 新增 `* -text`，作为 1 个入库条目 | 采用默认值，待确认 |
| D-10 | 摘要遍历规模 | 单线程顺序读 + 分块哈希；L2 降级为 path+size 摘要后实测 1 秒级 | 采用默认值，待确认 |

### 7.3 E-01…E-03

| 编号 | 事实 | 取法 | 状态 |
|---|---|---|---|
| E-01 | pre 清单早于 `.gitignore`/`.gitattributes`/证据/本文档 | `changed`/`deleted` 非豁免数必须为 0；`added` 仅限 `.gitignore`、`.gitattributes`、`.evidence/git-baseline/**`、`docs/devlog/vcs-baseline.md`；白名单外 added 判不通过 | 采用默认值，待确认 |
| E-02 | `vcs-baseline/<短标识>` 只有在提交后才存在 | 方案①：提交前写占位，提交后 `git commit --amend --no-edit` 回填；须维护者书面确认 | 待确认（未确认前不执行提交） |
| E-03 | `baseline-meta.json` 等只能在提交后生成 | 作为提交后证据 `tracked=false`、`role=evidence` 登记；不产生第二次提交，不写入 `.gitignore` | 采用默认值，待确认 |

## 8. 本轮事实偏差登记（实施阶段实测）

1. **自检阻塞为 3→7**：当前实测 `blocking_total=3`（④⑤未执行 2 条 + 非 Git 全局 1 条）；Git 化后全局 1→5，合计 7。两组数字并列，禁止混用。
2. **Tier C 三个文件无同类表述**：`m13-selfcheck-report.md`、`m11-coverage-report.md` 中 `非 Git`/`git` 实测命中 0；`m13-analysis-plan.md` 仅有计划表述（第 172 行）。按实际登记，不虚构原句。
3. **清单规模与 design 估算不同**：实测 L1 975 条（design 估 693），入库 520 条 / 6.74 MB；L2 聚合覆盖 4037 个派生文件。
4. **L2 摘要口径降级**：逐文件内容哈希导致首次生成耗时 66 秒，超出 60 秒窗口；改为 path+size 摘要后实测评级为秒级，`digest_mode=path+size` 已写入清单。
5. **Tier B 位置纠偏**：B-6/B-7 实际位于 `sandbox_realscan/design.md:520`、`:1311`、`:1454`，不在 `tasks.md`；"5.4.1"为 spec 章节号。