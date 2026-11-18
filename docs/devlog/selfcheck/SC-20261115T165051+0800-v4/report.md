# M13 自检报告

- 生成时间：2026-11-15T16:50:51.485556+08:00
- 运行标识：SC-20261115T165051+0800-v4
- 基线：ec8ff770ab0dd5511a8f9b24a8696882af3e333055f26a676df395d01ab5047d
- 范围：全量
- 退出码：3
- 执行域：本机默认环境（不预设 PYTHONUTF8）
- 只读状态：全量只读成立
- 指纹：e092b331b36340375e8174090cd12c212e1e1acc9c8339c1eb41bd019296f237
- 口径版本：v2
- 口径修订：R1 D4-1 载体四类 → 三类文字载体（演示材料移交 D5-2）；R2 D5-1 去除 D4-1 依赖；definition_version v1 → v2

## 1. 总体结论

- 结论：**不通过**（退出码 3）
- 实质阻塞：7 项
- 人工待填：6 项（与实质阻塞分列，不混计）
- 警告：0 项；未验证：3 项
- 推导依据：按“全局阻塞/阻塞 → 人工待填 → 警告 → 未验证 → 全通过”顺序命中即停，不以通过项数量判定。

## 2. 五维度汇总

| 维度 | 通过 | 警告 | 阻塞 | 未验证 | 人工待填 |
|---|---|---|---|---|---|
| D1 可复现性 | 3 | 0 | 1 | 2 | 0 |
| D2 能力真实性 | 2 | 0 | 0 | 1 | 3 |
| D3 证据完整性 | 5 | 0 | 2 | 0 | 0 |
| D4 口径一致性 | 3 | 0 | 3 | 0 | 0 |
| D5 交付完整性 | 1 | 0 | 1 | 0 | 3 |

## 3. 三问必答

- 最弱环节：D4 口径一致性（阻塞 3 项，未验证 0 项）
- 评委高危提问：真实：4 项（D3-1, D3-6, D4-3, D4-4）
- 评委高危提问：边界：2 项（D4-2, D5-2）
- 评委高危提问：复现：1 项（D1-2）
- 工期与顺序：人工待填（自检不推断）

## 4. 检查项明细

| 编号 | 状态 | 方式 | 命令/依据 | 输出摘要 | 耗时(s) | 基线变化 | 证据 |
|---|---|---|---|---|---|---|---|
| D1-1 | 通过 | AUTO | python -c "<load_config 并打印 config ok>"（CLEAN 环境，清空 PYTHON*） | 干净环境下配置加载成功（无隐式 PYTHON* 依赖）。 | 0.25 | UNCHANGED | 无 |
| D1-2 | 阻塞 | AUTO | python -m unittest discover -s backend/tests -p "test_*.py"（默认环境） | Ran 793 tests；errors=0；failures=1；test_perf02_thousand_issues_and_twelve_thousand_events | 51.33 | UNCHANGED | 无 |
| D1-3 | 通过 | AUTO | python scripts/smoke_m0.py | 空转闭环成立（chain_valid=True）。 | 0.55 | UNCHANGED | 无 |
| D1-4 | 未验证 | AUTO | README §3 五步链路前提检测（默认不执行链路、不写盘） | 默认不执行 15 分钟链路（会写 eval/runs 与指标报告），仅完成前提检测：README §3=存在；如需计时请显式 --allow-writes。 | 0.00 | UNCHANGED | 无 |
| D1-5 | 通过 | AUTO | node node_modules/vue-tsc/bin/vue-tsc.js --noEmit；node node_modules/vite/bin/vite.js build --outDir <tmp>/dist | 类型检查与构建通过，产物落临时目录（4 项）。 | 2.22 | UNCHANGED | 无 |
| D1-6 | 未验证 | AUTO | 容器能力探测（docker / WSL docker）+ 最近 VER 包摘要校验（只读，不重跑） | 容器运行时不可用（两次探测均失败），未执行沙箱校验；最后返回：ed while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock: Get "http://%2Fvar%2Frun%2Fdocker.sock/v1.… | 5.70 | UNCHANGED | 无 |
| D2-1 | 人工待填 | MANUAL | CLAIM_UNREGISTERED | 可声称 6 条，已登记 6 条，未登记/未确认 6 条。 | 0.00 | UNCHANGED | 无 |
| D2-2 | 人工待填 | MANUAL | NOT_CONFIRMED | 6 条缺级别：CLM-001, CLM-002, CLM-003, CLM-004, CLM-005；6 条未填 `确认：是`：CLM-001, CLM-002, CLM-003, CLM-004, CLM-005 | 0.00 | UNCHANGED | 无 |
| D2-3 | 未验证 | AUTO | NO_INPUT | 人工输入中没有 L4 条目，本项无输入可校验。 | 0.00 | UNCHANGED | 无 |
| D2-4 | 通过 | AUTO | — | 未发现 L2 桩能力被表述为“已集成/已打通/已上线”。 | 0.00 | UNCHANGED | 无 |
| D2-5 | 通过 | AUTO | — | 未发现同段混级合并表述。 | 0.02 | UNCHANGED | 无 |
| D2-6 | 人工待填 | AUTO | DEPENDENCY_FAILED | 依赖项未通过：D2-2 | 0.00 | UNCHANGED | 无 |
| D3-1 | 阻塞 | AUTO | CLAIM_WITHOUT_EVIDENCE | 6 条可声称中 6 条未给出可解析证据标识：690 用例、功能性失败 0；四类缺陷（C01/C02/C03/C05）静态+动态链路可跑通；容器域约束在 WSL2 内核实测：断网、只读、能力集、uid 10001、60s 硬终止、P4-05 62237ms 无残留；靶场真扫 15/15、动态 10/10、对账 15/15… | 0.02 | UNCHANGED | ISO-20261114T164822+0800-3c37, SCAN-20261114T123405+0800-c60… |
| D3-2 | 通过 | AUTO | — | 证据包 9 个，孤儿 0 个，孤儿率 0.0%（阈值 10%）。 | 0.06 | UNCHANGED | 无 |
| D3-3 | 通过 | AUTO | — | 9 个证据包逐文件摘要 100% 一致。 | 0.09 | UNCHANGED | ISO-20261114T164822+0800-3c37, SCAN-20261114T123405+0800-c60… |
| D3-4 | 通过 | AUTO | — | 9 个证据包索引、清单、重算摘要三方一致。 | 0.12 | UNCHANGED | 无 |
| D3-5 | 通过 | AUTO | — | 9 个证据引用全部可在索引中唯一定位。 | 0.06 | UNCHANGED | 无 |
| D3-6 | 阻塞 | AUTO | EVIDENCE_INCOMPLETE | 5 个证据包四类内容不完备：ISO-20261114T164822+0800-3c37:缺 runtime_facts.json；SCAN-20261114T123405+0800-c604:缺 runtime_facts.json,raw/；SCAN-20261114T123510+0800-5b8f:缺 runti… | 0.12 | UNCHANGED | 无 |
| D3-7 | 通过 | AUTO | — | 历史基线 9 项摘要不变；已登记归档 3 个摘要不变。 | 0.00 | UNCHANGED | 无 |
| D4-1 | 通过 | AUTO | — | 三类文字载体齐全可读：README（README.md）、收尾与阻塞文档（docs/devlog/m12-closure-and-blockers.md）、交付方案文档（deliverables/CodeArts方案.md） | 0.00 | UNCHANGED | 无 |
| D4-2 | 阻塞 | AUTO | VALUE_CONFLICT | 2 个字段跨载体取值不一致：连续运行时长（24h / 24h / 72h）；缺陷类别数（12 / 3） | 0.00 | UNCHANGED | 无 |
| D4-3 | 阻塞 | AUTO | SAMPLE_MISSING | 11 处百分比无样本量、0 处模糊数值表述；docs/devlog/m12-closure-and-blockers.md:80%；docs/devlog/m12-closure-and-blockers.md:54.5%；deliverables/CodeArts方案.md:80% | 0.00 | UNCHANGED | 无 |
| D4-4 | 阻塞 | AUTO | SINGLE_CALIBER | 覆盖率双口径不完整：缺“全模块口径”（自检未重跑度量）。 | 0.00 | UNCHANGED | 无 |
| D4-5 | 通过 | AUTO | — | 不可声称清单 4 项在各载体均无完成类表述。 | 0.00 | UNCHANGED | 无 |
| D4-6 | 通过 | AUTO | — | 合并目标分支表述统一为：release/auto。 | 0.02 | UNCHANGED | 无 |
| D5-1 | 人工待填 | MANUAL | NEED_CONFIRM | 已自动定位模板 10 项；其中 1 项缺章节位置，覆盖度需负责人确认并填写缺口等级。 | 0.00 | UNCHANGED | 无 |
| D5-2 | 阻塞 | AUTO | DELIVERY_GAP | 模板外必交三件不完备：演示文稿缺失、演示视频缺失 | 0.00 | UNCHANGED | 无 |
| D5-3 | 人工待填 | MANUAL | MANUAL_INPUT_MISSING | 人工输入中没有已确认的缺口等级与补齐成本，按待填处理。 | 0.00 | UNCHANGED | 无 |
| D5-4 | 通过 | AUTO | — | 交付方案可打开，正文 19657 字符，无占位特征。 | 0.00 | UNCHANGED | 无 |
| D5-5 | 人工待填 | MANUAL | NEED_CONFIRM | 自动检索到 54 处痕迹线索，充分性需负责人确认。 | 0.00 | UNCHANGED | 无 |

## 5. 阻塞与警告清单

| 编号 | 状态 | 原因 | 解除条件 |
|---|---|---|---|
| D1-2 | 阻塞 | TEST_FAILED | Ran 793 tests；errors=0；failures=1；test_perf02_thousand_issues_and_twelve_thousand_events |
| D3-1 | 阻塞 | CLAIM_WITHOUT_EVIDENCE | 6 条可声称中 6 条未给出可解析证据标识：690 用例、功能性失败 0；四类缺陷（C01/C02/C03/C05）静态+动态链路可跑通；容器域约束在 WSL2 内核实测：断网、只读、能力集、uid 10001、60s 硬终止、P4-05 62237ms 无残留；靶场真扫 15/15、动态 10/10、对账 15/15… |
| D3-6 | 阻塞 | EVIDENCE_INCOMPLETE | 5 个证据包四类内容不完备：ISO-20261114T164822+0800-3c37:缺 runtime_facts.json；SCAN-20261114T123405+0800-c604:缺 runtime_facts.json,raw/；SCAN-20261114T123510+0800-5b8f:缺 runti… |
| D4-2 | 阻塞 | VALUE_CONFLICT | 2 个字段跨载体取值不一致：连续运行时长（24h / 24h / 72h）；缺陷类别数（12 / 3） |
| D4-3 | 阻塞 | SAMPLE_MISSING | 11 处百分比无样本量、0 处模糊数值表述；docs/devlog/m12-closure-and-blockers.md:80%；docs/devlog/m12-closure-and-blockers.md:54.5%；deliverables/CodeArts方案.md:80% |
| D4-4 | 阻塞 | SINGLE_CALIBER | 覆盖率双口径不完整：缺“全模块口径”（自检未重跑度量）。 |
| D5-2 | 阻塞 | DELIVERY_GAP | 模板外必交三件不完备：演示文稿缺失、演示视频缺失 |
| D2-1 | 人工待填 | CLAIM_UNREGISTERED | 可声称 6 条，已登记 6 条，未登记/未确认 6 条。 |
| D2-2 | 人工待填 | NOT_CONFIRMED | 6 条缺级别：CLM-001, CLM-002, CLM-003, CLM-004, CLM-005；6 条未填 `确认：是`：CLM-001, CLM-002, CLM-003, CLM-004, CLM-005 |
| D2-6 | 人工待填 | DEPENDENCY_FAILED | 依赖项未通过：D2-2 |
| D5-1 | 人工待填 | NEED_CONFIRM | 已自动定位模板 10 项；其中 1 项缺章节位置，覆盖度需负责人确认并填写缺口等级。 |
| D5-3 | 人工待填 | MANUAL_INPUT_MISSING | 人工输入中没有已确认的缺口等级与补齐成本，按待填处理。 |
| D5-5 | 人工待填 | NEED_CONFIRM | 自动检索到 54 处痕迹线索，充分性需负责人确认。 |

## 6. 修复优先级

- [D1-2] 全量回归：TEST_FAILED；依据：errors=0 且 failures=0，记录用例数
- [D3-1] 声称→证据映射：CLAIM_WITHOUT_EVIDENCE；依据：每条声称 ≥1 个证据且摘要通过
- [D3-6] 证据包四类内容完备：EVIDENCE_INCOMPLETE；依据：commands/raw/runtime_facts/摘要四类齐备
- [D4-2] 同数同值：VALUE_CONFLICT；依据：同一字段跨载体取值集合大小 = 1
- [D4-3] 样本量随行：SAMPLE_MISSING；依据：百分比结论均随附样本量，且无模糊数值表述
- [D4-4] 覆盖率双口径：SINGLE_CALIBER；依据：并列全模块/判定函数双口径且保留未达标表述
- [D5-2] 模板外必交三件：DELIVERY_GAP；依据：演示文稿、视频、可访问入口三项齐备
- 工期判断：人工待填（由负责人填写，不由自检推断）

## 7. 声称来源追溯表

| 编号 | 声称 | 载体 | 真实来源 | 级别 | 证据 | 确认 | 可否对外 |
|---|---|---|---|---|---|---|---|
| CLM-001 | 690 用例、功能性失败 0；四类缺陷（C01/C02/C03/C05）静态+动态链路可跑通 | docs/devlog/m12-closure-and-blockers.md | — | — | 无 | 待确认 | 不可 |
| CLM-002 | 容器域约束在 WSL2 内核实测：断网、只读、能力集、uid 10001、60s 硬终止、P4-05 62237ms 无残留 | docs/devlog/m12-closure-and-blockers.md | — | — | 无 | 待确认 | 不可 |
| CLM-003 | 靶场真扫 15/15、动态 10/10、对账 15/15、扫描期真值读取 0 | docs/devlog/m12-closure-and-blockers.md | — | — | 无 | 待确认 | 不可 |
| CLM-004 | 容器域答案隔离 `publishable=true`、`exec_success_count=0` | docs/devlog/m12-closure-and-blockers.md | — | — | 无 | 待确认 | 不可 |
| CLM-005 | 指标复算 60/60，M9 未验证如实标注 | docs/devlog/m12-closure-and-blockers.md | — | — | 无 | 待确认 | 不可 |
| CLM-006 | 五步留痕 ①②③ 归档；④⑤ 未执行 | docs/devlog/m12-closure-and-blockers.md | — | — | 无 | 待确认 | 不可 |

## 8. 口径冲突清单

核对载体：三类文字载体（README / 收尾与阻塞文档 / 交付方案文档）；演示材料不参与 D4 数值比对。

| 字段 | 各载体取值 | 样本量 | 一致性 | 冲突级别 | 处置建议 |
|---|---|---|---|---|---|
| 覆盖率 | docs/devlog/m12-closure-and-blockers.md=54.5% / 80% | — | 一致 | — | 保持现状并复核 |
| 用例数 | README.md=690；docs/devlog/m12-closure-and-blockers.md=690 | — | 一致 | — | 保持现状并复核 |
| 连续运行时长 | docs/devlog/m12-closure-and-blockers.md=24h；deliverables/CodeArts方案.md=24h / 72h | — | 不一致 | 阻塞 | 先统一口径，禁止只改口径不改数值 |
| 缺陷类别数 | README.md=12；deliverables/CodeArts方案.md=3 | — | 不一致 | 阻塞 | 先统一口径，禁止只改口径不改数值 |
| 支出口径 | deliverables/CodeArts方案.md=release/auto | — | 一致 | — | 保持现状并复核 |
| 样本量 | 未出现 | — | 无法比较 | 未验证 | 保持现状并复核 |

## 9. 证据完整性明细

| 证据 | 索引摘要 | 完整性 | 被引用位置 | 不一致项 |
|---|---|---|---|---|
| ISO-20261114T164822+0800-3c37 | 840d112b34e664c6… | 通过 | docs/devlog/03-build.md:61, docs/devlog/m8-isolation-bridge-report.md:5, docs/devlog/m8-isolation-bridge-report.md:19, d… | 无 |
| SCAN-20261114T123405+0800-c604 | d8d822d3169a89a1… | 通过 | docs/devlog/sandbox-realscan-index.md:34 | 无 |
| SCAN-20261114T123510+0800-5b8f | 02d102d5974cfe0d… | 通过 | docs/devlog/sandbox-realscan-index.md:35 | 无 |
| SCAN-20261114T164810+0800-95ac | 82487258a117f855… | 通过 | docs/devlog/sandbox-realscan-index.md:36 | 无 |
| SCAN-20261114T164852+0800-9dfe | 5268b062a8d99292… | 通过 | docs/devlog/03-build.md:60, docs/devlog/m7-target-realscan-report.md:5, docs/devlog/sandbox-realscan-index.md:21 | 无 |
| VER-20261114T122909+0800-31af | 58215b20e98677a2… | 通过 | docs/devlog/sandbox-realscan-index.md:31 | 无 |
| VER-20261114T123024+0800-3c52 | 28538e5895b0b44e… | 通过 | docs/devlog/sandbox-realscan-index.md:33 | 无 |
| VER-20261114T123224+0800-6984 | 059932e18eb35411… | 通过 | docs/devlog/sandbox-realscan-index.md:32 | 无 |
| VER-20261114T164934+0800-a691 | 19ca051998546ff4… | 通过 | docs/devlog/03-build.md:32, docs/devlog/03-build.md:59, docs/devlog/m6-sandbox-constraint-report.md:5, docs/devlog/sandb… | 无 |

## 10. 交付缺口清单

清单范围：模板十项 + 模板外必交三件（演示文稿 / 演示视频 / 可访问演示入口）。

| 模板项 | 映射文件 | 映射章节 | 缺口等级 | 补齐方式 |
|---|---|---|---|---|
| 作品名称与一句话 | deliverables/CodeArts方案.md | ## 0. 一页速览 | 待人工确认 | — |
| 背景与价值 | deliverables/CodeArts方案.md | ## 1. 项目背景与价值 | 待人工确认 | — |
| 创新性解读 | deliverables/CodeArts方案.md | ## 2. 创新性解读 | 待人工确认 | — |
| 方案设计 | deliverables/CodeArts方案.md | ## 3. 系统设计 | 待人工确认 | — |
| 数据集与处理 | deliverables/CodeArts方案.md | ## 5. 数据集与处理 | 待人工确认 | — |
| 关键代码解读 | deliverables/CodeArts方案.md | ## 6. 关键代码解读 | 待人工确认 | — |
| 可量化指标 | deliverables/CodeArts方案.md | ## 7. 可量化指标 | 待人工确认 | — |
| CodeArts 使用说明 | deliverables/CodeArts方案.md | ## 4. CodeArts 使用设计（本文档核心） | 待人工确认 | — |
| 部署与演示 | deliverables/CodeArts方案.md | ## 8. 部署方案 | 待人工确认 | — |
| 团队分工与排期 | deliverables/CodeArts方案.md | 缺 | 待人工确认 | — |

## 11. 未执行与未验证说明

| 编号 | 原因 | 说明 |
|---|---|---|
| D1-4 | PRECONDITION_UNMET | 默认不执行 15 分钟链路（会写 eval/runs 与指标报告），仅完成前提检测：README §3=存在；如需计时请显式 --allow-writes。 |
| D1-6 | RUNTIME_UNAVAILABLE | 容器运行时不可用（两次探测均失败），未执行沙箱校验；最后返回：ed while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock: Get "http://%2Fvar%2Frun%2Fdocker.sock/v1.… |
| D2-3 | NO_INPUT | 人工输入中没有 L4 条目，本项无输入可校验。 |

## 12. 口径与执行域声明

- 本报告只诊断“声称是否有证据支撑”与“口径是否一致”，不修复被检问题、不补造证据、不代填人工判定。
- 标注“未验证”的项表示环境不可用或执行条件未成立，不得外推为通过。

## 13. 报告自摘要
- sha256：c465797874f31a309ba123fd6a6fb1ad17a7c2d0d74e0dee7c5e0c5245418e17
- 归档路径：SC-20261115T165051+0800-v4/report.md
