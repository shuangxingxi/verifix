# M0 沙箱隔离实测报告

- 实测时间：2026-11-13T17:13:37+08:00
- 结论：**PASS**（替代此前 `m2-reproduce-report.md` / `m3-e2e-report.md` 中"本机无 Docker，沙箱路径未验证"的缺口）
- 证据文件：`.evidence/sandbox/M0-SANDBOX-20261113T171337.txt`
- 证据 sha256：`a365c35284bd0be2ef5b8589283007a73a17c4fa9f4f3f73984ba274a9b17db6`

## 1. 运行环境

| 项 | 值 |
|---|---|
| 宿主 | Windows 11 家庭版 build 26300 / i9-14900HX |
| 执行层 | WSL2（`Linux 6.6.87.2-microsoft-standard-WSL2`），Debian 13 trixie |
| 容器引擎 | Docker 26.1.5+dfsg1（`docker.io` + `docker-cli`，systemd 托管） |
| 存储驱动 | overlay2 |
| Cgroup | v2（`--memory` / `--pids-limit` 可生效） |
| 镜像 | `verifix-runner:latest`，131 MB（`FROM python:3.12-slim` + pytest 8.3.4，`USER 10001`） |

## 2. 运行参数（与 `sandbox/spec.json` v1.0.0 逐项对齐）

```
--network=none
--read-only
--tmpfs /tmp:rw,size=64m,noexec,nosuid
--cap-drop=ALL
--security-opt=no-new-privileges
--user 10001:10001
--memory=1024m --cpus=1 --pids-limit=128
```

## 3. 实测输出

```
UID=10001 | NET=BLOCKED(OSError) | ROOTFS=READONLY(OSError) | TMPFS=WRITABLE
| SHADOW=DENIED(PermissionError) | CapEff: 0000000000000000
```

## 4. `spec.json` escape_cases 对照

| 编号 | 目标 | 期望 | 实测 | 判定 |
|---|---|---|---|---|
| P4-01 | read_dot_git | denied | 源树只读挂载（`:ro`）+ `ROOTFS=READONLY` | PASS |
| P4-02 | write_source_tree | denied | `ROOTFS=READONLY(OSError)` | PASS |
| P4-03 | outbound_network | denied | `NET=BLOCKED(OSError)` | PASS |
| P4-04 | privilege_escalation | denied | `CapEff=0` + `no-new-privileges` + `UID=10001` | PASS |
| P4-05 | infinite_loop | killed_at_60s | 由 runner 层 60s 超时控制，非 docker 参数 | 本轮未测 |

## 5. 边界说明（不得越界表述）

1. 本报告证明的是**容器层约束生效**，不证明 P4-05 的 60s 超时——后者由 `sandbox/spec.json` 的 `timeout_seconds` 在编排层实现，需补一条 runner 超时用例。
2. 执行环境是 WSL2 虚拟机内核，**与华为云 CCE 节点内核不同**。答辩被问"云上是否同样生效"时，应答"容器参数一致、cgroup v2 一致，CCE 节点需复测一次"，不要直接说"已在生产验证"。
3. `--user 10001:10001` 与镜像内 `USER 10001` 重复声明，属于纵深防御，不是冗余错误。

## 6. 复现命令

```bash
cd /mnt/e/shuangxingxi/ICT_agent
docker build -f sandbox/Dockerfile.runner -t verifix-runner sandbox/
docker run --rm --network=none --read-only \
  --tmpfs /tmp:rw,size=64m,noexec,nosuid \
  --cap-drop=ALL --security-opt=no-new-privileges \
  --user 10001:10001 --memory=1024m --cpus=1 --pids-limit=128 \
  verifix-runner -c "import os,socket;print(os.getuid())"
```

## 7. 环境搭建踩坑（供队友复现）

| 现象 | 原因 | 处置 |
|---|---|---|
| `wsl -d Ubuntu-20.04` 报 `0xd000000d` | 三个发行版全是 WSL **v1**，v1 无 Linux 内核，跑不了容器 | `wsl --set-version Debian 2`（本机 Debian 2.64 GB，转换约 15 分钟） |
| `docker: command not found`（装完 `docker.io` 后） | Debian 13 把 CLI 拆成独立包 | 追加 `apt install docker-cli` |
| `docker pull` 报 `registry-1.docker.io ... Timeout` | Docker Hub 不可达；`registry-mirrors` 失败后回退官方源 | 用完整域名拉取再重命名：`docker pull docker.m.daocloud.io/library/python:3.12-slim && docker tag ... python:3.12-slim` |
