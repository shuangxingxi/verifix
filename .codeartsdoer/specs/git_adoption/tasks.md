# Git 化与留痕追溯基线 · 编码任务清单（tasks.md）

> 上游文档：`.codeartsdoer/specs/git_adoption/spec.md`（v1.0）+ `.codeartsdoer/specs/git_adoption/design.md`（v1.0）
> 生成日期：2026-11-18
> 本轮性质：**只做版本控制基线与留痕追溯口径**；不修复缺陷、不接远端、不补建五步提交、不改产品代码。
> 本清单只做任务规划，**不执行任何 git 操作、不修改既有文档或产品代码**。

## 0. 前置强制口径（先读，违反即判任务不合格）

| # | 强制口径 | 禁止的错误写法 |
|---|---|---|
| P-1 | 自检阻塞：**合计 3 → 7**（④⑤未执行 2 条 + 非 Git 全局 1 条 → Git 化后全局 5 条，合计 2+5=7） | 把"1 → 5"当成合计；写"阻塞由 3 条降为…" |
| P-2 | 全局阻塞单列时才可写 **1 → 5**，且必须与"合计 3 → 7"并列出现 | 任何孤立出现的单个阻塞数字 |
| P-3 | 两个嵌套 `.gitignore`（`.codeartsdoer/.gitignore`、`eval/.gitignore`）内容均为 `*`；下层优先，上层 `!` 无法覆盖 → **只能 `git add -f` override**（D-01），**不得修改嵌套 `.gitignore` 文件内容** | 用 `!specs/**` 之类的否定规则"覆盖"下游 `*` |
| P-4 | `.merkle-snapshot.json` 的 `hash` **不可复算**（334 项 × 5 种变体 0 匹配，覆盖域不含 docs/specs/deploy/eval）→ 交叉校验只能做**计数 + 路径集合 + 大小**级（D-02），`content_comparable=false` | 声称与快照"内容完全一致"；以 `consistent=true` 兜底 |
| P-5 | Tier B 目标位置实为 `sandbox_realscan/design.md:520` 与 `sandbox_realscan/design.md:1454`；"5.4.1"是 spec 章节号，**不是** `tasks.md` 的位置 | 去 `.codeartsdoer/specs/sandbox_realscan/tasks.md` 找"5.4.1"并改写 |
| P-6 | OQ-1…OQ-7 一律采用 design 2.4.1 的默认值，并在所有落点标注"**采用默认值，待确认**" | 把 OQ 默认值写成已拍板结论 |
| P-7 | D-01…D-10 共 10 项规格未覆盖冲突必须逐项登记，不得因"spec 没写"而跳过 | 只登记其中几项、或登记为"无影响" |
| P-8 | 新增执行侧决策 E-01…E-03（见任务组 2）同样必须登记并拍板，未拍板不得进入任务组 6 | 自行决定 amend、自行决定 diff 白名单 |
| P-9 | 任何任务在**实测证据存在前不得勾选**；不得预勾选、不得以"已按设计执行"代替证据、不得代填 AC 结果 | 先生成勾选状态再补证据 |
| P-10 | 提交时间必须真实：**禁止**设置 `GIT_AUTHOR_DATE` / `GIT_COMMITTER_DATE`，禁止 `git commit --date`、禁止拆分基线提交伪装五步留痕 | 以环境变量或 `--date` 回填历史时间 |

### 执行顺序总览（不可调换处已标 ⛔）

| 组 | 名称 | 依赖 | 关键不可调换点 |
|---|---|---|---|
| 1 | 范围冻结与修订前指纹基线 | — | 必须最先执行 |
| 2 | 待确认决策与 D-01…D-10 登记 | 1 | ⛔ 未拍板不得进入组 6 |
| 3 | 排除规则与 `git add -f` override 清单 | 2 | ⛔ 必须先于组 4 |
| 4 | pre-VCS 追溯清单生成 | 3 | ⛔ 必须早于组 6 的 `git init` |
| 5 | 快照交叉校验（D-02） | 4 | 可在组 6 前后，默认在组 4 之后立即做 |
| 6 | `git init` + 单基线提交 | 2、3、4、8、9 | ⛔ Tier A/B 修订必须先于暂存；⛔ pre 清单必须先于 init |
| 7 | 双采集差异核对（pre/post） | 4、6 | ⛔ 必须晚于提交 |
| 8 | Tier A 修订（3 处） | 1 | ⛔ 必须先于组 6 暂存 |
| 9 | Tier B 修订（12 处） | 1 | ⛔ 必须先于组 6 暂存 |
| 10 | Tier C 登记（12 个文件，零改动） | 1 | 可与组 8/9 并行 |
| 11 | 自检与门禁行为变化核对 | 6 | ⛔ 必须晚于提交 |
| 12 | 修订说明成文（`docs/devlog/vcs-baseline.md`） | 2、7、8、9、10、11 | 需 commit_id 才能定稿 |
| 13 | AC-01…AC-14 验收映射 | 全部 | ⛔ 最后一组，未全 pass 不得签发 |
| 14 | 回滚方案与失败恢复 | 6、7 | 只出方案与隔离演练，**不真实回滚工作区** |

---

## 1. 范围冻结与修订前指纹基线

- [ ] **1.1 冻结本轮范围与"明确不做" 8 项**
  - 动作：把 design 2.8.2 的 8 条"明确不做"逐条落成可检索清单，供组 12 章节 5 引用。
  - 完成判定：清单含 8 条，且与 design 2.8.2 一一对应，包含"不补建五步提交 / 不接远端 / 不改历史报告 / 不重算快照 / 不删除派生 / 不修 8 个 error / 不改脚本语义 / 不宣称留痕通过"。
  - 依赖：无。

- [ ] **1.2 采集 Tier A/B 共 15 处待修订原文与 `pre_sha256`**
  - 动作：按 design 2.5.1、2.5.2 的定位逐条读取原文，记录"文件 / 行号 / 原句全文 / 文件 sha256 / 采集时刻"。
  - 必须覆盖：`docs/devlog/00-conventions.md` §2（行 22-28）、§3（行 30-32）；`.codeartsdoer/specs/sandbox_realscan/tasks.md` 行 21（C8）、行 233（第 6 条）、行 650（T-SBX-20 basis）；`eval_leak_hardening/tasks.md` 行 16（C3）；`metrics_recalc/design.md` 行 6、`metrics_recalc/tasks.md` 行 33；`sandbox_realscan/spec.md` 行 6；`sandbox_realscan/design.md` 行 56、520、1311、1454、1871；`selfcheck_harness/design.md` 行 160、`selfcheck_harness/tasks.md` 行 661。
  - 完成判定：15 条记录中每条都能按行号原样复读比对成功（字符串完全一致），且 `pre_sha256` 为 64 位小写十六进制。
  - 依赖：1.1。

- [ ] **1.3 采集 Tier C 共 12 个文件指纹与待登记原句**
  - 动作：对 `m5-eval-report.md`、`m9-stage-anchors-review.md`、`m12-closure-and-blockers.md`、`m13-selfcheck-report.md`、`m13-analysis-plan.md`、`m11-coverage-report.md`、`03-build.md`、`02-codegen.md`、`metrics-report.md`、`04-bootstrap.md`、`m6-sandbox-constraint-report.md`、`sandbox-realscan-index.md` 记录 sha256 与含"非 Git / 未初始化 Git 仓库 / 无分支提交回滚"的原句行号。
  - 完成判定：12 个文件均有 sha256；其中 `m5-eval-report.md` 复算值严格等于 `931d20442673b0922a32cfb42de1dcc9996925836607f6ddedbc5e8b1f165502`；`04-bootstrap.md`（行 15）、`m6-sandbox-constraint-report.md`（行 67）、`sandbox-realscan-index.md`（行 124）已作为 D-07 增补项登记。
  - 依赖：1.2。

- [ ] **1.4 标注 OQ-1…OQ-7 默认值并注明"采用默认值，待确认"**
  - 动作：逐条记录 OQ-1 `sandbox/` 整体入库、OQ-2 `frontend/dist/` 排除、OQ-3 临时调试四项排除、OQ-4 `gt.txt` 按答案排除、OQ-5 快照入库且只读、OQ-6 分支 `main`、OQ-7 不补建五步提交。
  - 完成判定：7 条均带 OQ 编号、默认取值、状态"采用默认值，待确认"、改变取值的影响说明（如改 OQ-2 需接受体积增长）。
  - 依赖：无。

- [ ] **1.5 建立修订记录骨架（7 字段规范）**
  - 动作：按 spec 6.3 建立记录骨架：`doc_path | section | original_text | revised_text | revised_at | basis | tier`，预置 Tier A 3 条、Tier B 12 条、Tier C 12 条的空记录位。
  - 完成判定：27 条记录位全部存在；`tier ∈ {A,B,C}`；Tier C 的 `revised_text` 预置为"未改动（仅登记）"。
  - 依赖：1.2、1.3。

---

## 2. 待确认决策与规格未覆盖冲突登记（E-01…E-03 + D-01…D-10）

> 本组全部条目状态为"**采用默认值，待确认**"。未完成本组不得进入任务组 6。

- [ ] **2.1 登记 E-01：pre/post 差异的"新增文件白名单"**
  - 冲突事实：`pre-vcs-manifest.json` 在 `git init` 之前采集，而 `.gitignore`、`.gitattributes`、`.evidence/git-baseline/**`、`docs/devlog/vcs-baseline.md` 均在本轮新增，因此 post 清单必然多出这些路径，AC-05 的"非豁免差异数=0"需要明确豁免口径。
  - 默认取法：`diff` 结果按 `added / changed / deleted` 三分；`changed` 与 `deleted` 的非豁免数必须为 0；`added` 只允许上述白名单内路径。白名单逐条列明，不使用通配目录。
  - 完成判定：白名单条目数与路径全文可检索；明确写"白名单外的 added 也判不通过"。
  - 依赖：1.5。

- [ ] **2.2 登记 E-02：`vcs-baseline/<短标识>` 的回填方式**
  - 冲突事实：Tier A 修订要求 §3.1 与 C8 写入基线短标识，而短标识来自 `commit_id`，只有提交后才存在；若提交后再改文档并单独提交，则提交数=2，违反 AC-01。
  - 候选方案：①提交前写占位 `<短标识待补>`，提交后以 `git commit --amend --no-edit` 把回填纳入同一提交（提交数仍 1、无父提交、提交信息不变、committer 时间仍为当日）；②缺省不动，仅在 `docs/devlog/vcs-baseline.md` 中补记，Tier A 文档保留占位（与 §3.1 要求冲突）。
  - 默认取法：方案①，且**必须先经维护者书面确认**；执行前记录 amend 前后 `git rev-list --count HEAD = 1` 与提交信息未变。
  - 完成判定：决策记录含"方案 / 理由 / 影响 / 待确认"；未确认则任务组 6 不得执行提交。
  - 依赖：1.5。**不可调换：必须先于组 6。**

- [ ] **2.3 登记 E-03：提交后产物（`baseline-meta.json` 等）的入库与未跟踪说明**
  - 冲突事实：`baseline-meta.json` 含 `commit_id`，只能在提交后生成，无法进入同一基线提交；若放任其未跟踪，`git status` 会出现 1 个非派生噪声。
  - 默认取法：`baseline-meta.json`、`ac-report.json` 及提交后二采清单作为"提交后证据"`tracked=false`、`role=evidence` 登记（经 E-01 白名单或单独登记），并在组 12 与 AC 报告中书面说明"提交后工作区存在 1–3 个提交后证据文件属预期"，**不得**用第二次提交收纳，**不得**写进 `.gitignore` 当作派生产物。
  - 完成判定：说明文本可检索；未产生第二次提交。
  - 依赖：1.5、2.2。

- [ ] **2.4 登记 D-01（嵌套 `.gitignore` = `*`）**
  - 取法：不修改 `.codeartsdoer/.gitignore`、`eval/.gitignore`；用 override 清单 + `git add -f` 逐条强制纳入 `.codeartsdoer/specs/**`、`.codeartsdoer/{agents,rule,skills,mcp}/**`、`.codeartsdoer/package.json`、`mem-exp-config.json`、`.codeartsdoer/.gitignore`、`eval/.gitignore`；`tracked` 与最终判定一致。
  - 完成判定：登记含"事实/取法/影响/待确认"；明确写入"上层 `!` 规则无法覆盖下层 `*`"。
  - 依赖：1.5。

- [ ] **2.5 登记 D-02（快照 `hash` 不可复算）**
  - 取法：交叉校验降级为计数 + 路径集合 + 大小；`content_comparable=false`、`hash_algorithm=unavailable`；`consistent=false` 且 `differences` 非空。
  - 完成判定：登记含"334 项 5 种变体 0 匹配""覆盖域不含 docs/specs/deploy/eval"两项实测依据；明确禁止"完全一致"表述。
  - 依赖：1.5。

- [ ] **2.6 登记 D-03（清单 L1/L2 分层）**
  - 取法：L1 逐文件（常规文件，实测 693 项）；L2 目录聚合 `frontend/node_modules`、`edgeprofile`、`edgeprofile2`、`edgeprofile3` 各 1 条，`role=derived`、`tracked=false`，`sha256` 为目录摘要。
  - 完成判定：登记含"若逐文件展开将达 4000+ 条、突破 60 秒窗口"的理由；AC-08 抽样 3 个排除项须来自 L1 的 `secret/answer/derived` 条目。
  - 依赖：1.5。

- [ ] **2.7 登记 D-04（`eval/` 整目录不入库）**
  - 取法：`eval/**` 全部 `role=answer`、`tracked=false`；`eval_set.sha256` 仍可在工作区校验；历史引用登记为"仅工作区可定位"。
  - 完成判定：登记含"既有 `eval/.gitignore=*` 与 verifix spec『评测集不入仓库』"依据；仅 `eval/.gitignore` 单文件可 override 入库。
  - 依赖：1.5。

- [ ] **2.8 登记 D-05（`verifix-target/` 最小粒度排除）**
  - 取法：父目录保留，仅排除 `ground_truth.json`、`target.db`、`backup.tgz`。
  - 完成判定：登记含"最小排除粒度优先排除子路径而非父目录"（spec 5.2.3-3）；`ground_truth.json` 引用登记为工作区锚点。
  - 依赖：1.5。

- [ ] **2.9 登记 D-06（`deploy/certs/` 整目录排除）**
  - 取法：`deploy/certs/` 整目录 `role=secret`、`tracked=false`，`reason=凭据证书`；清单登记 `server.crt`、`server.key`。
  - 完成判定：登记含"`server.crt` 是否属私钥材料的判定依据"与"`check_permissions.SKIP_DIRS` 已含 `certs`"。
  - 依赖：1.5。

- [ ] **2.10 登记 D-07（Tier C 实为 12 个）**
  - 取法：在 spec 列的 9 个之外增补 `04-bootstrap.md`、`m6-sandbox-constraint-report.md`、`sandbox-realscan-index.md`，合计 12 个，零改动。
  - 完成判定：登记含增补三文件的行号（15 / 67 / 124）与"仅登记"结论。
  - 依赖：1.3。

- [ ] **2.11 登记 D-08（`deliverables/` 入库）**
  - 取法：18 文件 2.42 MB，按"产品与交付材料"入库，`role=source`。
  - 完成判定：登记含实测文件数与体积；`verify` 负向断言包含 `deliverables/` 必须出现。
  - 依赖：1.5。

- [ ] **2.12 登记 D-09（新增 `.gitattributes`）**
  - 取法：新增根 `.gitattributes`，内容 `* -text`，自述"禁止行尾转换，保证跨平台字节一致"。
  - 完成判定：登记含"作为 1 个入库条目，`role=source`/配置类，`tracked=true`"。
  - 依赖：1.5。

- [ ] **2.13 登记 D-10（单线程摘要与 60 秒窗口）**
  - 取法：先单线程顺序读 + 分块哈希；实测超 60 秒才改按目录并发，且并发不得改变清单结果。
  - 完成判定：登记含"693 文件 / 6.94 MB，预计 <10 秒"的估算依据与"超时改并发不改结果"的约束。
  - 依赖：1.5。

---

## 3. 排除规则与 `git add -f` override 清单（只新增，不改既有规则文件）

- [ ] **3.1 编写根 `.gitignore`（六段，逐段中文注释）**
  - 动作：按 design 2.2.2 I-06 落六段：①依赖缓存 `frontend/node_modules/`、`**/node_modules/`、`__pycache__/`、`*.py[cod]`、`.pytest_cache/`、`.mypy_cache/`、`.ruff_cache/`、`.venv/`、`venv/`、`env/`；②用户目录 `edgeprofile/`、`edgeprofile*/`、`*profile*/`；③运行产物 `.evidence/**/.work/`、`.evidence/**/fixtures/**/.git/`、`frontend/dist/`、`verifix-target/target.db`、`verifix-target/backup.tgz`、`.codeartsdoer/.codebase/`、`.codeartsdoer/temp/`、`*.log`；④凭据证书 `.env`、`.env.*`、`!.env.example`、`*.pem`、`*.key`、`*.pfx`、`*.p12`、`deploy/certs/`；⑤答案 `eval/`、`verifix-target/ground_truth.json`、`.evidence/redteam-baseline/gt.txt`；⑥临时调试 `/dom.txt`、`/err.txt`、`/.patch_fix*.py`。
  - 完成判定：六段齐备、每段有注释；不含 `*`、`*.py`、目录级 `backend/`、`docs/`、`sandbox/`、`.codeartsdoer/`；`!.env.example` 位于 `.env.*` 之后（顺序生效）。
  - 依赖：2.4…2.13 全部登记完成。

- [ ] **3.2 新增根 `.gitattributes`**
  - 动作：内容 `* -text` + 中文注释。
  - 完成判定：文件仅含注释与 `* -text` 一行规则；与本地 `core.autocrlf=false` 双保险说明可检索。
  - 依赖：3.1。

- [ ] **3.3 固化本地仓库配置（只写配置，不改文件内容）**
  - 动作：设定 `core.autocrlf=false`、`core.quotepath=false`；`user.name` / `user.email` 沿用本机既有值，缺失则中止并要求填写。
  - 完成判定：`git config --get` 三项值可回读；**明确记录"未设置 `GIT_AUTHOR_DATE`/`GIT_COMMITTER_DATE`、未修改 `core.autocrlf` 之外的全局配置"**。
  - 依赖：3.2。**不可调换：必须早于组 6 的暂存。**

- [ ] **3.4 编制 D-01 override 清单并落成文件**
  - 动作：生成 `.evidence/git-baseline/override-paths.txt`，逐行列出：`.codeartsdoer/specs/**`（展开为实际文件或逐行路径）、`.codeartsdoer/agents/**`、`.codeartsdoer/rule/**`、`.codeartsdoer/skills/**`、`.codeartsdoer/mcp/**`、`.codeartsdoer/package.json`、`mem-exp-config.json`、`.codeartsdoer/.gitignore`、`eval/.gitignore`。
  - 明确不 override：`.codeartsdoer/.codebase/**`、`.codeartsdoer/temp/**`、`eval/**` 内容（`eval/.gitignore` 除外）。
  - 完成判定：清单逐行可核对，无通配目录级的 `-f` 目标（每行路径可定位到确定文件或已审子集）；`eval/` 下 override 目标计数 = 1。
  - 依赖：3.1。

- [ ] **3.5 暂存命令约束：禁止 `git add -f .` / `git add -f <目录>`**
  - 动作：规定 override 只能按 3.4 清单逐条 `git add -f <path>`，或 `git add --pathspec-from-file=...override-paths.txt -f`；普通文件用 `git add -A` 前必须先用 `git check-ignore -v` 抽样 5 项确认判定。
  - 完成判定：暂存操作单中不出现裸 `git add -f .`、`git add -f backend/` 等宽泛形式；抽样 5 项（依赖目录 / 字节码 / 浏览器目录 / 答案目录 / 源码目录）判定与清单 `tracked` 一致（spec 4.4-1）。
  - 依赖：3.4。

- [ ] **3.6 六类 reason 归口核对表**
  - 动作：把 `.gitignore` 每条映射到"依赖缓存 / 用户目录 / 运行产物 / 凭据证书 / 答案 / 临时调试"六类之一，并对齐 `excluded[].reason`。
  - 完成判定：无条目落在六类之外；不存在"以排除规避证据审查"的条目（spec 4.3-4）。
  - 依赖：3.1。

---

## 4. pre-VCS 追溯清单生成（⛔ 必须早于 `git init`）

- [ ] **4.1 实现 `manifest --phase pre|post` 子命令骨架**
  - 动作：按 design 2.2.2 I-01 实现 CLI；`--phase pre` 时若检测到 `.git` 存在，直接以 `EXIT_PRECONDITION_FAILED(4)` 拒绝。
  - 完成判定：`--phase pre` 在有 `.git` 的临时目录上被拒且退出码为 4；无 `.git` 时可正常产出；不写任何工作区文件（除 `--out` 目标）。
  - 依赖：3.5。

- [ ] **4.2 实现 `manifest_digest` 序列化规范**
  - 动作：`files[]` 按 `path` 字节序升序；逐条 `path\0sha256\0size\0role\0("1"|"0")\n`，UTF-8；整体 SHA-256 小写十六进制；**不含** `generated_at` / `root` / `excluded`。
  - 完成判定：同状态连续两次生成的 `manifest_digest` 逐字相等；修改任一文件内容后 digest 必变。
  - 依赖：4.1。

- [ ] **4.3 实现 L2 目录聚合（D-03）**
  - 动作：`frontend/node_modules`、`edgeprofile`、`edgeprofile2`、`edgeprofile3` 各产出 1 条聚合条目：`path`=目录、`sha256`=目录摘要、`size`=总字节、`role=derived`、`tracked=false`。
  - 完成判定：这 4 条在清单中恰好各出现 1 次；不逐文件展开（清单总条目数应显著小于 4000）；聚合条目 `tracked=false`。
  - 依赖：4.2。

- [ ] **4.4 实现 role/tracked 判定顺序**
  - 动作：按 design 2.3.2 的短路顺序实现：①`role ∈ {secret,answer}` → `tracked=false`；②命中 override 清单 → `tracked=true`；③命中根或嵌套 `.gitignore` → `tracked=false` 并取对应 reason；④其余 `tracked=true`。
  - 完成判定：抽取 8 类样本（每个 role 一条）验证判定符合规则表；`secret`/`answer` 强制为 false（spec 6.1-6）。
  - 依赖：3.6、4.3。

- [ ] **4.5 生成 `pre-vcs-manifest.json`**
  - 动作：`python scripts/vcs_baseline.py manifest --phase pre --out .evidence/git-baseline/pre-vcs-manifest.json`。
  - 完成判定：文件含 `schema_version="1"`、`generated_at`（带时区）、`root`（相对标识、无盘符）、`files[]`（path/sha256/size/role/tracked 五字段）、`excluded[]`（pattern_or_path/reason）、`manifest_digest`、`cross_check` 占位；路径统一为 `/`；中文与含空格路径可原样还原。
  - 依赖：4.4。**不可调换：此任务完成后才允许执行 6.2 `git init`。**

- [ ] **4.6 规模预检（AC-03 前置）**
  - 动作：统计 `tracked=true` 的条目数、总体积、最大单文件体积。
  - 完成判定：文件数 ≤1500、总体积 ≤40MB、单文件 ≤5MB；超限则输出"超限清单（路径/体积/类别）+ 待确认"，**不得自动裁剪源码**。
  - 依赖：4.5。

- [ ] **4.7 复核清单自洽（AC-08 前置）**
  - 动作：随机抽 10 项（含 3 个 `tracked=false`，分别来自 `secret`、`answer`、`derived`）复算 sha256 与 size。
  - 完成判定：10 项误差数 = 0；3 个排除项均取自 L1 条目而非只取自 L2 聚合。
  - 依赖：4.5。

---

## 5. 与 `.merkle-snapshot.json` 的交叉校验（D-02 口径）

- [ ] **5.1 实现 `cross-check` 的 C1–C6**
  - 动作：C1 只读 `rootHash`/`fileCount`/`timestamp`；C2 路径反斜杠归一后求交/差（`only_in_snapshot[]` / `only_in_manifest[]`）；C3 交集比 `size`（`size_mismatch[]`）；C4 `content_comparable=false`、`hash_algorithm=unavailable`；C5 差异归因分组（口径差异 / 时间差异）；C6 `consistent=(fileCount 相等 且 两组差异均空)`。
  - 完成判定：六阶段均有对应输出字段；快照缺失/解析失败时以 `EXIT_SNAPSHOT_UNREADABLE(5)` 报错，**不得**以 `consistent=true` 兜底。
  - 依赖：4.5。

- [ ] **5.2 生成 `cross-check.json` 与差异明细**
  - 动作：产出 `.evidence/git-baseline/cross-check.json`（含 `merkle_root_hash`、`merkle_file_count`、`consistent`、`differences`）+ `.evidence/git-baseline/cross-check-differences.json`（完整明细）。
  - 完成判定：主文件四字段齐备；预期 `consistent=false` 且 `differences` 非空、含分组与代表路径；差异归因至少区分"快照仅覆盖代码域 + 部分证据"与"快照时间 2026-11-17 19:59 之后新增文件"。
  - 依赖：5.1。

- [ ] **5.3 口径表述核对（P-4）**
  - 动作：检查所有产物、报告、修订说明中的措辞。
  - 完成判定：检索 `content_comparable=false` 存在；检索"内容完全一致""内容级一致"命中数 = 0；`fileCount=334` 与清单范围不同处已标注"口径差异"而非失败（spec 5.4.3-1）。
  - 依赖：5.2。

- [ ] **5.4 冻结快照三项元数据**
  - 动作：记录 `rootHash=e7aefa1dd8b076d5d9cfa5439766cb599e385988df533c2ee5532ebf00c4571e`、`fileCount=334`、`timestamp=1794916749441`，并复算该文件 sha256。
  - 完成判定：三项值与 Git 化前逐字一致；文件 sha256 在组 7 的双采集核对中差异为 0；同名文件无第二次写入。
  - 依赖：5.2。

---

## 6. `git init` 与单基线提交（⛔ 进入条件：组 2 已拍板、组 4 已完成、组 8/9 已修订）

- [ ] **6.1 提交前预检（幂等入口）**
  - 动作：确认根目录无 `.git`；`git --version` 可用（实测 2.45.1）；`user.name`/`user.email` 可读；确认 `pre-vcs-manifest.json` 已存在且 `generated_at` 早于当前时刻。
  - 完成判定：五项全部为真；任一为假则中止并输出原因，不产生任何 `.git`。
  - 依赖：4.5、2.2。

- [ ] **6.2 初始化本地仓库**
  - 动作：`git init -b main`。
  - 完成判定：仅存在 `main` 一个分支；无 remote、无 tag、无其他分支。
  - 依赖：6.1。**不可调换：必须晚于 4.5。**

- [ ] **6.3 暂存前敏感与答案扫描（AC-04 前置）**
  - 动作：复跑 `python scripts/check_permissions.py --json`，并对 `role=secret/answer` 的条目断言 `tracked=false`；扫描 `.env` 实体、私钥、`.env.*`（非 `.example`）。
  - 完成判定：`blocking_total=0`、`passed=true`；命中数 = 0；`**/.env.example` 全部 `tracked=true` 且仅含占位值。命中 >0 时拒绝提交并输出命中清单。
  - 依赖：6.2。

- [ ] **6.4 暂存（普通 + override 逐条）**
  - 动作：先 `git add -A`，再按 3.4 清单逐条 `git add -f`；随后 `git status --porcelain` 复核。
  - 完成判定：`git ls-files` 条目集合与清单 `tracked=true` 集合完全一致（双向差集为空）；`git status --porcelain` 无 `frontend/node_modules`、`edgeprofile*`、`__pycache__` 等噪声；`eval/` 下仅 `.gitignore` 1 项。
  - 依赖：6.3、3.4、3.5。

- [ ] **6.5 暂存后负向断言（AC-02）**
  - 动作：对以下模式逐一断言 `git ls-files | grep` 命中 0：`frontend/node_modules`、`__pycache__`、`*.pyc`、`edgeprofile`、`eval/expected`、`.env$`、`*.pem`、`*.key`、嵌套 `.git`。
  - 完成判定：上述每项命中数均为 0；`backend/`、`frontend/src/`、`mcp/`、`scripts/`、`sandbox/spec.json`、`docs/devlog/`、`.codeartsdoer/specs/`、`.merkle-snapshot.json`、`deliverables/` 全部命中数 ≥1（100% 纳入抽样项）。
  - 依赖：6.4。

- [ ] **6.6 规模终检（AC-03）**
  - 动作：统计暂存条目数、总体积、最大单文件。
  - 完成判定：≤1500 / ≤40MB / ≤5MB，且三项数值写入 `baseline-meta` 与 AC 报告。
  - 依赖：6.5。

- [ ] **6.7 生成 post 清单（提交前，与暂存内容一致）**
  - 动作：`manifest --phase post --out .evidence/git-baseline/post-commit-manifest.json`，比对 `manifest_digest` 与提交信息将写入的值。
  - 完成判定：post 清单的 `tracked=true` 集合与 `git ls-files` 完全一致；`manifest_digest` 可复算（两次相等）。
  - 依赖：6.6。

- [ ] **6.8 构造基线提交信息（中性 + 三要素 + 无时间回填）**
  - 动作：主题 `[vcs-baseline] initialize repository baseline`；正文三行 `tracked=<入库文件数>` / `excluded=<排除条目数>` / `manifest=<64 位十六进制>`。
  - 完成判定：主题不命中 `[step-1/requirement]`、`[step-2/codegen]`、`[step-3/build]`、`[step-4/bootstrap]`、`[step-5/release]` 任一；三项值与清单实际一致；不含 token/口令/内网地址/绝对盘符路径；执行环境中未出现 `GIT_AUTHOR_DATE`、`GIT_COMMITTER_DATE`、`--date`（P-10）。
  - 依赖：6.7。

- [ ] **6.9 执行单次提交并断言唯一性（AC-01）**
  - 动作：`git commit`（仅 1 次）；记录 `commit_id`、`committed_at`；断言 `git rev-list --count HEAD = 1`、`git rev-parse HEAD^` 失败、`git log --format=%s` 无五前缀。
  - 完成判定：三项同时成立；若因 E-02 采用方案①，amend 后复算仍为 `count=1`、无父提交、提交信息逐字未变。
  - 依赖：6.8。

- [ ] **6.10 写 `baseline-meta.json`（7 字段）**
  - 动作：`commit_id`、`branch="main"`、`committed_at`、`tracked_count`、`excluded_count`、`manifest_digest`、`baseline_label="vcs-baseline/<前 12 位>"`。
  - 完成判定：`committed_at` 不早于清单 `generated_at`；`tracked_count`/`excluded_count` 与清单一致；`baseline_label` 不命中 `v1`–`v4` 或 `definition_version` 命名空间。
  - 依赖：6.9。

- [ ] **6.11 幂等复跑验证（spec 4.2-1）**
  - 动作：对已初始化工作区再次执行 `init`。
  - 完成判定：返回既有 `commit_id` 与提示"已存在版本控制基线"，`git rev-list --count HEAD` 仍为 1，未新增提交、未修改文件。
  - 依赖：6.10。

- [ ] **6.12 断点恢复判定（spec 4.2-2）**
  - 动作：核对 design 2.6.1 的四行判定（无 `.git` / `.git` 无提交 / 1 个基线提交 / 多提交），并验证"`.git` 存在、无提交"分支的处理是删 `.git/index` 后重算重试，而非删 `.git`。
  - 完成判定：四种断点均有明确判定条件与动作；"多提交"分支明确停止并转人工，**不得自动 reset**。
  - 依赖：6.10。

---

## 7. 双采集差异核对（pre vs post）

- [ ] **7.1 实现 `diff --before --after --waive-tier`**
  - 动作：比对 `path + sha256 + size`，输出 `added / changed / deleted` 三类；豁免路径单独归组。
  - 完成判定：输出含"非豁免差异数"字段；任一侧清单缺失时以 `EXIT_MANIFEST_UNREADABLE(3)` 报错。
  - 依赖：6.7。

- [ ] **7.2 生成 `pre-post-diff.json`**
  - 动作：`--waive-tier` 传入 Tier A（3 路径）与 Tier B（8 个文件路径）清单，并叠加 E-01 白名单。
  - 完成判定：文件可解析，三类差异分组清晰，非豁免差异数可计算。
  - 依赖：7.1。

- [ ] **7.3 断言非豁免差异为 0（AC-05）**
  - 动作：核对 `changed`、`deleted` 的非豁免数。
  - 完成判定：非豁免 `changed = 0`、非豁免 `deleted = 0`；`added` 仅出现 E-01 白名单内路径（`.gitignore`、`.gitattributes`、`.evidence/git-baseline/**`、`docs/devlog/vcs-baseline.md`）；白名单外 `added` 也判不通过。
  - 依赖：7.2。

- [ ] **7.4 断言 Tier A/B 仅新增行、无数值变动**
  - 动作：对 15 处修订做"仅新增/替换限定语"检查，确认未出现删除行或阈值数字变化。
  - 完成判定：Tier A/B 文件中被修订处不出现验收阈值、数量、sha256 的改动；出现删除既有数值即回退该处改为追加标注（spec 5.3.4-1）。
  - 依赖：7.3。

- [ ] **7.5 复算 `m5-eval-report.md` 指纹**
  - 动作：独立复算 sha256。
  - 完成判定：等于 `931d20442673b0922a32cfb42de1dcc9996925836607f6ddedbc5e8b1f165502`。
  - 依赖：7.3。

- [ ] **7.6 断言 Tier C 12 文件差异为 0**
  - 动作：与 1.3 采集的 sha256 逐一比对。
  - 完成判定：12 项差异数 = 0；`04-bootstrap.md`、`05-release.md` 内容未变（二者是自检输入，改动会改变判定）。
  - 依赖：7.3、1.3。

---

## 8. Tier A 文档修订（必须修订，⛔ 必须先于组 6 暂存）

- [ ] **8.1 修订 `docs/devlog/00-conventions.md` §3（行 30-32）为三段**
  - 动作：原位拆为 **3.1 版本控制基线**（初始化日期 2026-11-18、`vcs-baseline/<短标识>`、分支 `main`、入库/排除计数、`manifest_digest`）、**3.2 前版本控制期留痕**（区间 = D1 留痕起至基线提交前；留存方式 = 文件 + 归档副本 + 内容指纹；"禁止以提交时间推断证据产生时间"）、**3.3 自基线起的提交要求**（后续变更须新增提交；基线提交豁免步骤前缀）；原句作为 3.2 的"历史事实"引述保留。
  - 完成判定：§3 第一段含基线标识与初始化日期；第二段明确标注"前版本控制期"及其时间边界；原句完整出现在 3.2 引述中且未被删除；章节未重排、未动 §4 及之后内容。
  - 依赖：1.2。**不可调换：必须先于 6.4。**

- [ ] **8.2 修订 `docs/devlog/00-conventions.md` §2（行 22-28）追加第 6 条**
  - 动作：1–5 条**逐字保留**（含第 3 条"禁止脚本批量伪造提交时间"）；追加第 6 条："基线提交（`[vcs-baseline]`）不归属任何步骤，不计入步骤提交计数；步骤提交要求自基线提交之后生效。"
  - 完成判定：第 6 条存在；1–5 条逐字未变；"禁止伪造提交时间"语义未减弱（spec 5.3-6）。
  - 依赖：1.2。

- [ ] **8.3 修订 `.codeartsdoer/specs/sandbox_realscan/tasks.md` C8（行 21）**
  - 动作：约束列改为"工作区已 Git 化（基线 `vcs-baseline/<短标识>`）：允许只读 git 查询用于追溯（白名单：`rev-parse`/`log`/`show`/`status`/`ls-files`/`check-ignore`/`cat-file`/`config --get`/`for-each-ref`）；仍禁止依赖分支/提交/回滚作为交付手段；回滚继续以 staging + 文件替换实现；基线提交不计入五步留痕"；验收列改为"验收命令不出现写类 git 操作；只读查询命中须在任务记录中说明用途并可回溯"。
  - 完成判定：C8 同时满足"允许只读追溯"与"禁止写类 git 操作"（`add`/`commit`/`reset`/`checkout`/`switch`/`branch -d`/`push`/`remote`/`tag`/`clean`/`stash` 均列为禁止）；未新增或删除表格列；C9/C10 等其他行未变。
  - 依赖：1.2。

- [ ] **8.4 为 Tier A 补 3 条修订记录**
  - 动作：在组 1.5 骨架中填写 `original_text`（完整原句）、`revised_text`（若为追加须标"追加"）、`revised_at`、`basis`（引用 spec 条目 + 基线标识）。
  - 完成判定：3 条记录与文件内实际改动一一对应；`original_text` 与 1.2 采集值逐字一致；无重复、无缺失（spec 5.3-5）。
  - 依赖：8.1、8.2、8.3。

- [ ] **8.5 修订前指纹复核（防止覆盖他人改动）**
  - 动作：修订前后各算一次 sha256，与 1.2 的 `pre_sha256` 比对。
  - 完成判定：修订前指纹与 1.2 一致；若不一致则停止修订、输出差异并转人工（spec 5.3.4-2），不得覆盖。
  - 依赖：8.4。

---

## 9. Tier B 文档修订（12 处，只追加标注，禁改结论，⛔ 必须先于组 6 暂存）

> 统一要求：只追加一行"**前提变更（2026-11-18）**"标注；不删除原文、不改数值、不改探针、不改 `fixture=true`。每条修订后补 1 条修订记录（`tier=B`）。

- [ ] **9.1 B-1：`eval_leak_hardening/tasks.md:16`（C3）**
  - 追加："前提变更（2026-11-18）：工作区已 Git 化，C3 的'非 Git'限定不再成立；'拆分与发布回滚只能用 staging + 文件替换'的约束仍然有效。"
  - 完成判定：只新增 1 行；C3 原句与 C4/C5 未变。

- [ ] **9.2 B-2：`metrics_recalc/design.md:6`（前言环境约束）**
  - 追加："前提变更（2026-11-18）：此句中的'非 Git 仓库'已由版本控制基线取代；'无 Docker、无华为云凭据'两项前提不变。"
  - 完成判定：仅追加标注；`design.md:189`、`design.md:1438` 的同类"非 Git"短语**只登记不改**（属验收条件正文）。

- [ ] **9.3 B-3：`metrics_recalc/tasks.md:33`（第 4 条）**
  - 追加："前提变更（2026-11-18）：本条'不安排任何 git 命令'的适用范围截至基线提交；此后只读 git 查询可用于追溯，分支守卫断言仍由模型层校验。"
  - 完成判定：仅追加；第 4 条原句保留。

- [ ] **9.4 B-4：`sandbox_realscan/spec.md:6`（前提修正段）**
  - 追加："前提变更（2026-11-18）：'非 Git 仓库'于本日被版本控制基线取代；'无华为云凭据、无 pytest'不变。"
  - 完成判定：仅追加；该行原有"Docker 已可用"等结论未变。

- [ ] **9.5 B-5：`sandbox_realscan/design.md:56`（§0.2 事实表行）**
  - 追加："〔2026-11-18 前提变更：现已成为 Git 仓库；P4-01 仍以合成夹具为准，`fixture=true` 结论不升级。〕"
  - 完成判定：表格结构未变（行列数一致）；`fixture=true` 未被改写。

- [ ] **9.6 B-6：`sandbox_realscan/design.md:520` 与 `design.md:1311`（§2.6）**
  - 追加："〔2026-11-18：已成为 Git 仓库；同一视图规则继续排除真实 `.git`，探针无需改动；不得表述为'已验证真实仓库 `.git`'。〕"
  - 完成判定：两处均有标注；**位置纠偏声明已写入修订记录**：spec 所述"`sandbox_realscan/tasks.md` 第 5.4.1"实为 `design.md:520`（"5.4.1"是 spec 章节号）（P-5）。

- [ ] **9.7 B-7：`sandbox_realscan/design.md:1454`（§2.8 第 10 条）**
  - 追加："〔2026-11-18 前提变更：本条的'工作区非 Git 仓库'不再成立；'不使用分支/提交/回滚作为交付手段'仍然有效。〕"
  - 完成判定：标注落在 `design.md:1454`；未误改 `tasks.md`；修订记录 `section` 字段同时标注 spec 原表述与实际位置。

- [ ] **9.8 B-8：`sandbox_realscan/design.md:1871`（§5.3 O-02 表）**
  - 追加："〔2026-11-18：O-02 的环境前提已变化；选项'要求真实 `.git`'仍不在本轮范围，合成夹具结论保持。〕"
  - 完成判定：表格未变形；O-02 原判定未改。

- [ ] **9.9 B-9：`sandbox_realscan/tasks.md:233`（"明确不做"第 6 条）**
  - 追加："〔2026-11-18：本条由后续 Git 化轮次取代；本轮已完成基线初始化，本条对 `sandbox_realscan` 阶段仍然有效。〕"
  - 完成判定：仅追加；该条原有"不执行 `git init`"的历史表述保留。

- [ ] **9.10 B-10：`sandbox_realscan/tasks.md:650`（T-SBX-20 `basis` 项）**
  - 追加："〔2026-11-18：`basis` 原文不改写；工作区已 Git 化，但'不得表述为已验证真实仓库 `.git`'仍然有效。〕"
  - 完成判定：`basis` 原句未被替换；仅新增标注。

- [ ] **9.11 B-11：`selfcheck_harness/design.md:160`（§1.2.4 约束）**
  - 追加："〔2026-11-18：自基线提交起，本约束改为'提交前缀缺失'阻塞；全局阻塞由 1 条变为 5 条、阻塞合计由 3 条变为 7 条，须如实转述。〕"
  - 完成判定：标注中同时出现"全局 1→5"与"合计 3→7"（P-1/P-2）；原"3 个阻塞"表述保留且未被改写。

- [ ] **9.12 B-12：`selfcheck_harness/tasks.md:661`（8.6 验收行）**
  - 追加："〔2026-11-18：该'非 Git 阻塞结果不得被抵消'的表述适用范围截至基线提交；基线后以'五步前缀缺失'阻塞为准，同样不得抵消。〕"
  - 完成判定：标注只落验收行；8.6 其他条目与其数值未变。

- [ ] **9.13 为 Tier B 补 12 条修订记录**
  - 动作：逐条填写 7 字段，含 9.2 中"只登记不改"的 `design.md:189/1438` 说明与 9.6/9.7 的"位置纠偏"声明。
  - 完成判定：12 条与文件内标注一一对应，无重复无缺失；`revised_text` 明确标"追加"。
  - 依赖：9.1…9.12。

---

## 10. Tier C 登记（零改动，仅登记）

> 统一要求：**不触碰任何字节**；仅在 `docs/devlog/vcs-baseline.md` 登记"文件 / 原句 / 行号 / 时间边界 / sha256"。

- [ ] **10.1 C-1 `docs/devlog/m5-eval-report.md`** — 全文只读，sha256 恒为 `931d2044…f165502`；完成判定：文件 sha256 未变且登记存在。
- [ ] **10.2 C-2 `docs/devlog/m9-stage-anchors-review.md:45`** — 原句"`check_devlog.py` 当前如实返回阻塞（04/05 未执行 + 非 Git），未通过文案绕过。"；完成判定：行号与原句登记可复读，文件 sha256 未变。
- [ ] **10.3 C-3 `docs/devlog/m12-closure-and-blockers.md:17`** — 原句"`check_devlog.py` 返回 **3 个阻塞**（④⑤ 未执行 + 非 Git），如实"；完成判定：登记并注明该"3"为前版本控制期合计口径。
- [ ] **10.4 C-4 `docs/devlog/m13-selfcheck-report.md`** — 前置结论段含"非 Git"表述，按实际检索原句登记；完成判定：登记行号与原句。
- [ ] **10.5 C-5 `docs/devlog/m13-analysis-plan.md`** — 方案正文同类表述；完成判定：登记行号与原句（注意该文件在 `selfcheck_harness` 8.6 有"末尾追加实施状态"的历史任务，本轮不得触发该改动）。
- [ ] **10.6 C-6 `docs/devlog/m11-coverage-report.md`** — 结论段环境前提表述；完成判定：登记行号与原句。
- [ ] **10.7 C-7 `docs/devlog/03-build.md:68`** — 原句"提交前缀 \| 非 Git 仓库，无 `[step-3/build]` 提交；`check_devlog.py` 列为全局阻塞"；完成判定：登记且文件 sha256 未变。
- [ ] **10.8 C-8 `docs/devlog/02-codegen.md:9`、`:66`** — "尚未初始化为 Git 仓库"、"全局仍因'非 Git 仓库'阻塞"；完成判定：两处均登记。
- [ ] **10.9 C-9 `docs/devlog/metrics-report.md:56`** — "无 Docker/无云凭据/非 Git 环境可执行"；完成判定：登记且数值未变。
- [ ] **10.10 C-10 `docs/devlog/04-bootstrap.md:15`** — "工作区**不是 Git 仓库**，无法创建分支、提交与 PR"（D-07 增补）；完成判定：登记且**文件字节未变**（自检输入，禁止改动）。
- [ ] **10.11 C-11 `docs/devlog/m6-sandbox-constraint-report.md:67`** — "工作区非 Git 仓库，使用合成 `.git` 夹具……"（D-07 增补）；完成判定：登记且字节未变。
- [ ] **10.12 C-12 `docs/devlog/sandbox-realscan-index.md:124`** — "未初始化真实 Git 仓库（P4-01 用合成夹具）"（D-07 增补）；完成判定：登记且字节未变。
- [ ] **10.13 汇总断言** — 完成判定：12 个文件在组 7.6 的差异数 = 0；修订说明中 12 条记录的 `tier=C` 且 `revised_text="未改动（仅登记）"`；`05-release.md` 亦未变。

---

## 11. 自检与门禁行为变化核对（⛔ 必须晚于组 6）

- [ ] **11.1 证明脚本零改动**
  - 动作：对 `scripts/check_devlog.py`、`scripts/check_permissions.py` 做 sha256 比对（与 1.2 采集或 `git show HEAD:scripts/...` 比对）。
  - 完成判定：两脚本差异数 = 0；`--strict` 仍为"声明未参与判定"的既有事实，未被顺手修复。
  - 依赖：6.9。

- [ ] **11.2 复跑 `check_devlog.py --json` 并核对双口径**
  - 动作：`python scripts/check_devlog.py --json`。
  - 完成判定：`steps` 阻塞 = 2（`04-bootstrap.md`、`05-release.md` 仍"未执行（阻塞）"）；`global_blocking` = 5；`blocking_total` = **7**；`git_commits` 为 5 键且全为 0；`passed=false`；退出码 = 2。
  - 依赖：11.1。

- [ ] **11.3 转述口径核对（P-1/P-2）**
  - 动作：对 `docs/devlog/vcs-baseline.md`、AC 报告及所有对外文本做检索。
  - 完成判定：合计口径一律写 **3 → 7**；仅"全局"语境出现 **1 → 5**，且与合计并列；任何孤立出现的单个阻塞数字（如只写"5 条"）均判不合格，须能追溯到对照表。
  - 依赖：11.2。

- [ ] **11.4 `--skip-git-check` 语义核对**
  - 动作：`python scripts/check_devlog.py --skip-git-check --json`。
  - 完成判定：阻塞 = 2 条且无任何 Git 相关全局阻塞；与 Git 化前一致；参数仍仅用于脚本自测。
  - 依赖：11.2。

- [ ] **11.5 复跑 `check_permissions.py --json` 并逐字段比对（AC-11）**
  - 动作：复跑并与 Git 化前冻结的 JSON 逐字段比较。
  - 完成判定：`blocking_total=0`、`passed=true`、`branch_guard.problems` 为空；差异字段数为 0；若有变化则登记为独立环境/代码问题，**不得归因于 Git 化**。
  - 依赖：11.2。

- [ ] **11.6 `.git` 存在但 `git log` 失败的回退路径说明（spec 5.5.3-1）**
  - 动作：核对脚本行为（返回码非 0 / `OSError` / 30s 超时 → `{}` → 回退 1 条非 Git 口径），并在修订说明中写明该诊断路径。
  - 完成判定：说明文本存在且与代码路径一致；未修改脚本。
  - 依赖：11.5。

- [ ] **11.7 禁"留痕通过"表述检索**
  - 动作：检索"留痕已通过""五步留痕验收通过""已 Git 化，留痕通过"等模式。
  - 完成判定：命中数 = 0；存在标准句"仓库已 Git 化 ≠ 五步留痕已通过"。
  - 依赖：11.3。

---

## 12. 修订说明成文：`docs/devlog/vcs-baseline.md`

- [ ] **12.1 章节 1 摘要**
  - 内容：基线标识、初始化时间、分支 `main`、入库/排除计数、`manifest_digest`、自检双口径（合计 3→7；全局 1→5）。
  - 完成判定：双口径并列出现；未出现孤立数字。

- [ ] **12.2 章节 2 前提变更登记表**
  - 内容：Tier A 3 条、Tier B 12 条、Tier C 12 条，每条 7 字段。
  - 完成判定：27 条齐全；Tier A/B 每条在对应文件中有实际标注；Tier C 每条 `revised_text="未改动（仅登记）"`（AC-07）。

- [ ] **12.3 章节 3 排除规则对照**
  - 内容：`.gitignore` 六段 ↔ `excluded[].reason` 一一对应表；附 override 清单与"不 override"清单。
  - 完成判定：类别数量与内容一致（spec 5.2.1-10）；任一文件可据表在 2 分钟内判断是否入库（spec 4.4-1）。

- [ ] **12.4 章节 4 交叉校验结果**
  - 内容：快照三项元数据转述、`consistent` 判定、差异分组、`content_comparable=false`。
  - 完成判定：无"完全一致"表述；差异给出分组归因（AC-09）。

- [ ] **12.5 章节 5 明确不做**
  - 内容：1.1 的 8 条。
  - 完成判定：8 条逐条存在，含"未修复 8 个编码 error / 未处理 PERF-02 / 未接入远端云"（AC-14）。

- [ ] **12.6 章节 6 标准表述**
  - 内容：逐字引用标准句——
    > Git 化前：留痕自检未通过，阻塞合计 3 条（④⑤ 未执行 2 条 + "非 Git 仓库"全局 1 条）。
    > Git 化后：留痕自检仍未通过，阻塞合计 7 条（④⑤ 未执行 2 条 + 五步提交前缀缺失全局 5 条）。
    > 基线提交不计入任何步骤；"仓库已 Git 化"不等于"五步留痕已通过"。
  - 完成判定：三句逐字存在，无改写。

- [ ] **12.7 附录：OQ / D / E 决策表**
  - 内容：OQ-1…OQ-7（含"采用默认值，待确认"）、D-01…D-10、E-01…E-03。
  - 完成判定：共 20 条，编号连续无缺；每条含"事实 / 取法 / 影响 / 状态"。

- [ ] **12.8 命名空间与评测绑定声明（AC-12）**
  - 内容：`vcs-baseline/<短标识>`、自检口径 `v1`–`v4`、`definition_version=v2` 三者互不混用；`eval/eval_set.sha256` 绑定关系未变。
  - 完成判定：文档中三类标识可仅凭前缀区分；无"v4 即第四个提交"类表述；`definition_version` 仍为 `v2`。

- [ ] **12.9 证据引用格式统一**
  - 动作：新增修订说明中所有证据引用采用"路径 + 64 位十六进制指纹（+ 可选提交标识）"。
  - 完成判定：检索该文档中所有证据引用，缺少 64 位指纹的条数 = 0（spec 5.4.1-8）。

---

## 13. AC-01…AC-14 验收映射与签发

- [ ] **13.1 实现 `verify` 子命令（只读白名单）**
  - 动作：实现 AC 机器可判部分；git 调用仅限 `rev-parse`、`log`、`show`、`status`、`ls-files`、`check-ignore`、`cat-file`、`config --get`、`for-each-ref`。
  - 完成判定：`verify` 执行期间无写类 git 操作；`git` 不可用时以 `EXIT_GIT_UNAVAILABLE(9)` 输出并标记"未验证"，不得默认通过。
  - 依赖：12.9。

- [ ] **13.2 生成 AC 对照报告**
  - 逐项判据（每条须附实测证据指针，禁止代填）：

    | AC | 判据 | 证据来源 |
    |---|---|---|
    | AC-01 | `rev-list --count=1`、`rev-parse HEAD^` 失败、无五前缀 | 6.9 |
    | AC-02 | 源码/文档/规格/定稿证据 100%；`node_modules`、`__pycache__`、`edgeprofile*`、`eval/expected`、`.env`、私钥、嵌套 `.git` 命中 0 | 6.5、4.7 |
    | AC-03 | ≤1500 / ≤40MB / 单文件 ≤5MB | 6.6 |
    | AC-04 | 敏感扫描命中 0；`.env.example` 入库且占位 | 6.3 |
    | AC-05 | 非豁免差异 0；`m5` = `931d2044…f165502` | 7.3、7.5 |
    | AC-06 | §3 三段式、§2 第 6 条、C8 新语义 | 8.1–8.3 |
    | AC-07 | Tier A/B 每项有标注 + 1 条记录；Tier C 零改动且全部登记 | 8.4、9.13、10.13 |
    | AC-08 | 抽样 10 项误差 0；`manifest_digest` 可复算 | 4.7、4.2 |
    | AC-09 | 四字段齐备；`consistent=false` 时差异非空且分组 | 5.2、5.3 |
    | AC-10 | `blocking_total=7`、`global_blocking=5`、`passed=false`、退出码 2；`--skip-git-check` 为 2 | 11.2、11.4 |
    | AC-11 | `blocking_total=0`、`branch_guard.problems` 空 | 11.5 |
    | AC-12 | `vcs-baseline/` 与 `v1`–`v4`、`v2` 可区分；评测摘要绑定未变 | 12.8 |
    | AC-13 | 无"已验证真实 `.git`"表述；`fixture=true` 保留 | 9.5–9.10 |
    | AC-14 | 无源码/缺陷修复改动；无远端/云配置 | 7.3、9.13 |

  - 完成判定：14 项每项均给出 `pass/fail + 证据文件与行号`；`fail` 项不得写成"可接受"，须登记为未完成并给出后续动作。
  - 依赖：13.1。

- [ ] **13.3 性能验收**
  - 动作：记录初始化总耗时（步骤 0–10，不含人工确认）；连续 3 次 `git status` 计时。
  - 完成判定：初始化 ≤60 秒；3 次 `git status` 均 ≤3 秒且输出无"未跟踪派生产物"噪声；三个数值写入报告。
  - 依赖：6.9。

- [ ] **13.4 评审抽样复核（AC-08）**
  - 动作：评审者按抽样 10 项复算（3 个排除项分别来自 `secret`、`answer`、`derived`）。
  - 完成判定：误差 0；评审者签署"数值未变、结论未改"核对结论；签名缺失则 AC-07/AC-08 不得判 pass。
  - 依赖：4.7。

- [ ] **13.5 签发条件**
  - 动作：维护者在 `docs/devlog/vcs-baseline.md` 摘要段签署时间与责任人。
  - 完成判定：仅当 AC-01…AC-14 全部 pass 才签发并可进入下一收尾路线项；存在 `fail` 时明确写"本轮不通过"。
  - 依赖：13.2、13.3、13.4。

---

## 14. 回滚方案与失败恢复（只出方案与隔离演练，⛔ 不真实回滚工作区）

- [ ] **14.1 编制断点恢复判定表**
  - 内容：无 `.git` / `.git` 无提交 / 1 个基线提交 / 多提交 四行的判定条件、动作、是否触碰工作区文件。
  - 完成判定：四行齐全；"多提交"明确"停止并转人工，不得自动 reset"。
  - 依赖：6.12。

- [ ] **14.2 编制主动回滚操作单 R1–R5**
  - 内容：R1 删除 `.git/`；R2 删除新增文件（`.gitignore`、`.gitattributes`、`.evidence/git-baseline/*`、`docs/devlog/vcs-baseline.md`）；R3 按 `original_text` 逐条还原 Tier A/B 共 15 处改动并与 `pre_sha256` 对账；R4 Tier C 与 `m5` 无需动作（sha256 仍应为 `931d2044…f165502`）；R5 复跑 `check_devlog --json`，应回到 `blocking_total=3`、`git_commits={}`。
  - 完成判定：每条含"动作 / 校验 / 误删防护"；R2 的删除清单与 E-01 白名单完全一致（不得多删既有文件，R-05）。
  - 依赖：7.3。

- [ ] **14.3 在隔离副本上演练 R1 可逆性**
  - 动作：把仓库目录复制到临时位置后演练"删除 `.git` → 按 `pre-vcs-manifest.json` 复算"，**不在真实工作区执行**。
  - 完成判定：副本复算差异数 = 0；真实工作区 `.git` 未被删除、未被执行回滚动作；演练记录含副本路径与复算结果。
  - 依赖：14.2。

- [ ] **14.4 编制部分失败处置**
  - 内容：暂存后提交失败（删 `.git/index` 重试，工作区不变）；文件不可读（提交前中止，不产生部分提交）；提交成功但 `verify` 失败（**不回滚提交**，属入库范围错误才按 14.2 全量回滚，不得用追加提交掩盖）。
  - 完成判定：三类均有判定条件与动作；"用追加提交掩盖失败"被明确禁止。
  - 依赖：14.1。

- [ ] **14.5 回滚方案自检**
  - 动作：核对回滚方案与"仓库不可逆操作禁令"的一致性。
  - 完成判定：方案中不含 `push --force`、`reset --hard`、`clean -fdx` 等破坏性命令；所有删除动作限定在本轮新增路径内。
  - 依赖：14.2。

---

## 15. 完成标准与勾选规则（收尾）

- [ ] **15.1 产物清单核对**
  - 清单：`scripts/vcs_baseline.py`（新增）、`.gitignore`、`.gitattributes`、`.evidence/git-baseline/{pre-vcs-manifest,post-commit-manifest,cross-check,cross-check-differences,pre-post-diff,baseline-meta}.json`、`docs/devlog/vcs-baseline.md`、Tier A 3 处、Tier B 12 处、Tier C 12 个零改动。
  - 完成判定：每项存在且归属与 design 附录 A 一致；未出现清单外的新增/修改文件（除 E-01 白名单）。

- [ ] **15.2 勾选规则与未完成项登记**
  - 动作：仅对"完成判定已被实测证据满足"的任务勾选；未满足者保持 `- [ ]` 并在报告登记阻塞原因。
  - 完成判定：不存在"先勾选后补证据"；未勾选项均有原因与后续动作；**本轮不预勾选任何条目**。

- [ ] **15.3 收尾结论**
  - 动作：输出"本轮完成/未完成 + AC 汇总 + 阻塞项"。
  - 完成判定：结论只陈述实测结果；不得把"工作区成为 Git 仓库"表述为"五步留痕验收通过"；不得声称已修复任何缺陷或已接入远端/云。

---

### 覆盖对照（需求 → 任务）

| spec 能力 | 覆盖任务 |
|---|---|
| 5.1 仓库初始化与基线提交 | 6.1–6.12 |
| 5.2 入库范围与 `.gitignore` | 3.1–3.6、6.4–6.6 |
| 5.3 "非 Git 仓库"前提修订（Tier A/B/C） | 8.1–8.5、9.1–9.13、10.1–10.13 |
| 5.4 历史留痕兼容与追溯口径 | 4.1–4.7、5.1–5.4、7.1–7.6、12.8–12.9 |
| 5.5 自检与门禁行为变化 | 11.1–11.7 |
| 6. 数据约束（清单/元数据/修订记录/`.gitignore` 条目） | 4.2、4.5、6.10、8.4、9.13、3.1 |
| 7. OQ-1…OQ-7 | 1.4、12.7 |
| design 2.4.2 D-01…D-10 | 2.4–2.13、12.7 |
| design 2.6 回滚与失败恢复 | 14.1–14.5 |
| spec 第 8 章 AC-01…AC-14 | 13.1–13.5 |