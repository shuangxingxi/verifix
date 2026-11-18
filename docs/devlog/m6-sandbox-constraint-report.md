# M6 沙箱约束实测报告（容器域真实执行）

- 生成时间：2026-11-14
- 结论：**PASS**（容器层约束 10 类判定 + 5 条逃逸用例全部 PASS）
- 证据：`.evidence/sandbox-realscan/VER-20261114T164934+0800-a691`
- 证据 sha256：`19ca051998546ff4f11f979fee8d1f6abb77c23cfcd4c4b8b40778d1602e1b71`
- 验证来源：`REAL_EXECUTION`（非单元测试推断）

## 1. 执行域声明

| 项 | 值 |
|---|---|
| 宿主 | Windows 11，无 docker CLI |
| 执行层 | WSL2 Debian 13，Docker `26.1.5+dfsg1`，overlay2，cgroup v2 |
| 传输 | `WslDockerTransport`（`wsl.exe -d Debian -u root -- docker`） |
| `exec_domain` | `RUNTIME_ROOT` |
| `privilege_route` | `WSL_DISTRO_ROOT`（只记录类别，不保存口令，不执行 sudo 交互） |
| 容器内身份 | `uid=10001,gid=10001`（identity 探针实测） |
| 策略文件 | `sandbox/spec.json`，sha256 `bd62277bbae9d6ed146e92231b36bc2a3e5462e5aca715144ad8332384e36168` |
| 策略版本 | `1.0.0` |

> `capability.runtime.user = root` 表示**调用容器运行时的执行身份**，不是容器内进程身份；容器内进程身份由 identity 探针实测为 `10001:10001`。

## 2. 环境能力（六项）

| 能力 | 状态 | 说明 |
|---|---|---|
| `docker_cli` | AVAILABLE | `docker version` client 段可读 |
| `daemon` | AVAILABLE | `docker version` server 段 `26.1.5+dfsg1` |
| `socket_permission` | AVAILABLE | 配置身份执行 `docker ps` 成功 |
| `image_availability` | AVAILABLE | 策略镜像与靶场镜像均可解析 |
| `egress_network` | AVAILABLE | 构建期宿主可出网（运行期容器仍禁出） |
| `loopback` | AVAILABLE | 禁网容器内 bind/listen/connect 三动作成功 |

- 六项探测总耗时约 6.5s（≤15s 预算）。
- `runtime_driver` / `cgroup_version` 在本轮记录为 `unknown`：`docker info --format` 未返回预期字段，未做本地推断，如实记为未知。M0 报告中 overlay2 / cgroup v2 的事实仍成立，但本报告不据此声称字段已采集。

## 3. 判定类别（11 键 → 10 类，缺项 0）

| 类别 | 策略键 | 实测事实 | 判定 |
|---|---|---|---|
| 网络隔离 | `network` | 容器内连接外网 `OSError: Network is unreachable`；`HostConfig.NetworkMode=none` | PASS |
| 源树只读 | `source_mount` | `/src` 写入失败（OSError），`/src/app/main.py` 正例可读 | PASS |
| 文件系统可写面 | `root_filesystem` + `tmpfs` | 根写入失败；`/tmp`、`/workspace` 可写（tmpfs `mode=1777`） | PASS |
| 超时终止 | `timeout_seconds` | P4-05 `terminated_ms=62237`，`leaked=False` | PASS |
| 内存上限 | `memory_mb` | inspect `Memory=1073741824` | PASS |
| CPU 上限 | `cpu` | inspect `NanoCpus=1000000000` | PASS |
| 执行用户 | `user` | `uid=10001,gid=10001` | PASS |
| 能力集 | `cap_drop` | `CapEff=0000000000000000`，inspect `CapDrop=["ALL"]` | PASS |
| 禁止提权 | `no_new_privileges` | `NoNewPrivs=1`，`setuid(0)` 被拒，`SecurityOpt` 含 `no-new-privileges` | PASS |
| 进程上限 | `pids_limit` | inspect `PidsLimit=128` | PASS |

- 口径差异 `D-01`（**采用默认值，待确认**）：策略文件实际 11 个隔离键，`root_filesystem` 与 `tmpfs` 合并为一个"文件系统可写面"判定类别，因此 `policy_keys=11 / judgement_classes=10 / missing=0`。
- 附加检查 `loopback_available` PASS（不属于 10 类，仅证明回环可用）。

## 4. P4 逃逸用例矩阵

| 编号 | 目标 | 期望 | 实测 | 判定 |
|---|---|---|---|---|
| P4-01 | read_dot_git | denied | 视图内 `.git` 不存在（`FileNotFoundError`），正例 `app/main.py` 可读 | PASS |
| P4-02 | write_source_tree | denied | `/src` 写入 OSError | PASS |
| P4-03 | outbound_network | denied | `Network is unreachable` | PASS |
| P4-04 | privilege_escalation | denied | `CapEff=0`，`setuid(0)` 被拒，`NoNewPrivs=1` | PASS |
| P4-05 | infinite_loop | killed_at_60s | `terminated_ms=62237`，`leaked=False` | PASS |

- **P4-05 口径**：具名容器 `vf-loop-*` + 宿主 60s 预算 + `docker kill` + `docker rm -f`；终止耗时 62237ms 落在 55–75s 判定窗口内，残留检查在清理之后执行。
- **P4-01 纠偏**：`:ro` 挂载**不能**阻止进程读取挂载源中的 `.git`；本轮改为挂载面裁剪，工作区非 Git 仓库，使用合成 `.git` 夹具（`fixture=true`），不声称已验证真实仓库的 `.git`。

## 5. 镜像摘要

| 项 | 值 |
|---|---|
| 策略镜像名 | `verifix-sandbox:1.0.0` |
| 镜像 ID | `sha256:9b090181ca17d65bda27764178b10b6f0bdbe8cf6b610a1b6964c31fca80a645` |
| 仓库摘要 | 无（`local_build=true`，本机构建） |
| 构建期网络 | on（仅构建期；运行期 `--network=none`） |

> 本地构建、无仓库摘要，需在镜像重建后复测；不得把本结论外推为"云上已构建/已验证"。

## 6. 与 M0 报告对照

| 项 | M0（2026-11-13） | 本轮 M6 |
|---|---|---|
| 网络/只读/能力集/用户 | PASS | PASS |
| P4-01 | 以 `:ro` 挂载作依据 | 改为挂载面裁剪 + 夹具 |
| P4-05 | **未测** | **PASS（62237ms）** |
| 判定类别 | 未落 10 类 | 10 类全部落地，缺项 0 |
| 证据 | `.evidence/sandbox/M0-SANDBOX-20261113T171337.txt` | `.evidence/sandbox-realscan/VER-*` |

历史报告 `docs/devlog/m0-sandbox-verification.md` 保持只读，sha256 `35b0c79267427a13041d431b14d4a3f9408621cd5c11e04af88e7aef24a68d30` 未变。

## 7. 边界声明（不得外推）

1. 本报告证明的是**容器层约束在 WSL2 内核上生效**，不证明华为云 CCE 节点内核同样生效；云侧需复测。
2. 运行期禁止外网这一结论来自容器 `--network=none`；宿主构建期可出网的事实不得写成"运行期容器可出网"。
3. 镜像为本地构建、无仓库摘要，镜像更新后须重跑本报告。
4. 历史 M1 的 10/10 为录制桩派生，与本报告无关，不得混算。

## 8. 复现命令

```text
python scripts/build_sandbox_images.py --build-network on
python scripts/run_sandbox_verify.py --policy sandbox/spec.json --p4-05 on --evidence-root .evidence/sandbox-realscan
```

退出码：0=PASS、2=UNVERIFIED、3=FAIL、4=证据归档失败。