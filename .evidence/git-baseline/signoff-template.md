# 人工签署模板（signoff）

> 生成日期：2026-11-18
> 基线提交：`ecfcad3d8fcaef085e280f70a245546b870eb4d8`
> **说明**：机器已完成复算与检索。本文件为签署底稿。
> **状态**：已于 2026-11-18 由**张李焱**按申请人授权签署（同一人兼任评审/复核/签发），正式记录见 `docs/devlog/vcs-baseline.md` §1"人工签署"；按维护者选择采用**写法 B**，结论为**通过（附注）**——以工作区修正版 `vcs_baseline.py` 重跑 14/14 pass，基线提交内版本存在 AC-13 检索缺陷。下方空位保留为签署痕迹，不再重复填写。

## 1. AC-08 抽样复算结果（机器已完成，待评审者独立复核）

来源：`.evidence/git-baseline/ac08-sample.json`；10 项，误差 **0**。

| # | 路径 | role | tracked | 机器复算 |
|---|---|---|---|---|
| 1 | `backend/app/main.py` | source | true | 匹配 |
| 2 | `README.md` | docs | true | 匹配 |
| 3 | `docs/devlog/00-conventions.md` | history | true | 匹配 |
| 4 | `.codeartsdoer/specs/git_adoption/spec.md` | spec | true | 匹配 |
| 5 | `.evidence/git-baseline/pre-vcs-manifest.json` | evidence | true | 匹配 |
| 6 | `scripts/check_devlog.py` | source | true | 匹配 |
| 7 | `deliverables/能力边界说明书.pdf` | source | true | 匹配 |
| 8 | `deploy/certs/server.key` | secret | **false** | 匹配 |
| 9 | `eval/cases/EVAL-0001.json` | answer | **false** | 匹配 |
| 10 | `.codeartsdoer/.codebase/baseline_info.json` | derived | **false** | 匹配 |

评审者独立复算命令：

```bash
python - <<'PY'
import json, hashlib
m=json.load(open('.evidence/git-baseline/post-commit-manifest.json',encoding='utf-8'))
idx={f['path']:f for f in m['files']}
for p in ['backend/app/main.py','README.md','docs/devlog/00-conventions.md',
 '.codeartsdoer/specs/git_adoption/spec.md','.evidence/git-baseline/pre-vcs-manifest.json',
 'scripts/check_devlog.py','deliverables/能力边界说明书.pdf',
 'deploy/certs/server.key','eval/cases/EVAL-0001.json','.codeartsdoer/.codebase/baseline_info.json']:
    f=idx[p]; d=hashlib.sha256(open(p,'rb').read()).hexdigest()
    print('OK ' if d==f['sha256'] else 'MISMATCH', p)
PY
```

**评审者签署（请手填）**

```
抽样复核结论：10 项误差 ___ 项；数值未变：是/否；结论未改：是/否
评审者：____________________   日期：____________________
```

> 未签署前，AC-07 / AC-08 只能记"机器 pass、人工待签"，不得判为完整通过。

## 2. AC-13 复核（机器检索已完成，待人确认）

机器检索 `git grep -n "已验证真实仓库" -- docs .codeartsdoer` 共命中 13 行，逐行判定：

- 全部为**否定句或规范条文**（"不得表述为…"、"不声称…"、"命中数必须为 0"），无肯定声称；
- 沙箱报告原文：`docs/devlog/m6-sandbox-constraint-report.md:67` 为"合成 `.git` 夹具（`fixture=true`），不声称已验证真实仓库的 `.git`"；
- `fixture=true` 在 7 个文件中保留（含 `m6` 与 `sandbox-realscan-index.md`）。

人工确认要点（逐项打勾）：

```
[ ] 无任何"已验证真实仓库 .git"的肯定断言
[ ] P4-01 仍以合成夹具为准，fixture=true 保留
[ ] 未把"工作区已 Git 化"表述为"已验证真实 .git"
复核者：____________________   日期：____________________
```

## 3. 签发（已由维护者完成）

机器判定：以工作区修正版 `vcs_baseline.py` 重跑 AC-01…AC-14 为 **14/14 pass**；基线提交内版本 AC-13 fail（检索未区分否定语境）。

**本轮采用写法 B（2026-11-18）**：

```
通过（附注）：以工作区修正版 vcs_baseline.py 重跑得 14/14；基线提交内版本存在 AC-13 检索缺陷，已登记于 final-report 第 6 节。
维护者：张李焱   日期：2026-11-18
```

备选写法 A（未采用，保留以备改用）：

```
本轮不通过：AC-13 机器项 fail（验收工具为基线提交内 vcs_baseline.py），其余 13 项 pass；
修正版待下一轮提交后重签。
维护者：____________________   日期：____________________
```

> 无论 A 还是 B，都不得写成无附注的"通过"，也不得表述为"五步留痕已通过"。

## 4. 签完后要落的位置

- 抽样与 AC-13 结论：追加到 `docs/devlog/vcs-baseline.md` 摘要段（会形成该文件的 later 版本，已在 final-report 登记）；
- 签名原件：保留本文件作为签署底稿；
- 签完后复跑 `python scripts/vcs_baseline.py verify --manifest .evidence/git-baseline/post-commit-manifest.json --meta .evidence/git-baseline/baseline-meta.json`，确认无新增失败项。