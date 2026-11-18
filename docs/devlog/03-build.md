# 03 · 项目构建留痕

- 记录时间：2026-11-11
- 最后更新：2026-11-14
- 阶段：赛题 1 CodeArts 五步留痕第 ③ 步
- 对应提交前缀：`[step-3/build]`
- 状态：已归档（构建为真实执行，产物摘要可复算）

> 说明：仓库未初始化 Git，本章不伪造 `[step-3/build]` 提交；构建命令、耗时与产物标识均来自 2026-11-13 / 2026-11-14 的真实执行输出。

## 1. 构建入口

| 构建目标 | 命令 | 说明 |
|---|---|---|
| 后端全量回归 | `python -m unittest discover -s backend/tests -p "test_*.py"` | 589 用例 |
| 靶场自测 | `python -m unittest discover -s verifix-target/tests` | 靶场 SQLite 初始化与 15 项真值 |
| 沙箱镜像 | `python scripts/build_sandbox_images.py --build-network on` | `Dockerfile.sandbox` |
| 靶场镜像 | 同上（同一脚本第二项） | `Dockerfile.target` |
| API 镜像定义 | `deploy/Dockerfile.api` | 供 compose / ECS / CCE 使用 |
| 一键编排 | `docker-compose -f docker-compose.yml config`（Compose v2.26.1） | 校验 compose 结构 |

## 2. 真实构建执行记录（2026-11-14）

| 产物 | 镜像 ID | 构建耗时 | 仓库摘要 |
|---|---|---|---|
| `verifix-sandbox:1.0.0` | `sha256:9b090181ca17d65bda27764178b10b6f0bdbe8cf6b610a1b6964c31fca80a645` | 100045 ms | 无（本地构建） |
| `verifix-target:1.0.0` | `sha256:5d0b0a32cd4c1c7f0a9d758e7c4a6b76c860f2ae2696a2f02a6373ee5b096c69` | 184365 ms | 无（本地构建） |

- 构建期网络：`on`（仅构建期使用；运行期容器 `--network=none`）。
- 基础镜像：`python:3.12-slim`。
- 运行身份：`USER 10001:10001`；`ENTRYPOINT ["python"]`。
- 构建日志与镜像 ID 同时登记在 `.evidence/sandbox-realscan/VER-20261114T164934+0800-a691/records/capability.json` 与 `manifest.json`。

## 2.1 编排结构校验（2026-11-14）

| 项 | 结果 |
|---|---|
| 工具 | Docker Compose `v2.26.1-4`（WSL2 Debian） |
| 服务 | `api` / `mcp` / `sandbox` / `gateway` |
| 端口 | `gateway` 发布 `8443`（未使用 80/443） |
| 卷 | `evidence` / `workspace` |
| 退出码 | 0（仅结构校验；服务启动与云上部署未实测） |
| 方式 | 在 `/tmp` 临时目录用 `.env.example` 校验，不改动 `deploy/` |

## 3. 回归执行记录（2026-11-14）

| 项 | 结果 |
|---|---|
| 全量用例数 | 690（2026-11-14 末次；含上述 685 条 + 配置变更入口 5 条） |
| 功能性失败 | 0 |
| 唯一非功能失败 | `PERF-02` 单次 0.2799s > 0.2s（抖动），单跑 `OK` |
| 基线口径 | ≥690 用例、功能性失败 0（旧基线 502 → … → 680 → 685 → 690） |
| 目标文件 SHA 复核 | 9 项历史留痕摘要全部一致 |

## 4. 产物摘要（可复算）

| 产物 | 摘要 |
|---|---|
| 约束验证证据包 | `VER-20261114T164934+0800-a691` → `19ca051998546ff4f11f979fee8d1f6abb77c23cfcd4c4b8b40778d1602e1b71` |
| 真扫证据包 | `SCAN-20261114T164852+0800-9dfe` → `5268b062a8d992920c5ffefad46d3d89351b5587f8101cb02df745a5fbe4f91d` |
| 隔离证据包 | `ISO-20261114T164822+0800-3c37` → `840d112b34e664c6054e1957b31f1b83f5dbb4baaab2f2877f3b4d8a679a7fed` |
| 证据索引 | `.evidence/sandbox-realscan/INDEX.json`（9 个包，逐文件回读一致） |

## 5. 缺口（阻塞，不视为完成）

| 项 | 说明 |
|---|---|
| 提交前缀 | 非 Git 仓库，无 `[step-3/build]` 提交；`check_devlog.py` 列为全局阻塞 |
| wheel / sdist | 未产出 Python 打包产物（当前交付形态为源码 + 容器镜像） |
| CI 构建 | 未接入 CodeArts Pipeline 真实构建任务，构建为本机执行 |

## 6. 复现

```text
python -m unittest discover -s backend/tests -p "test_*.py"
python scripts/build_sandbox_images.py --build-network on
```

镜像为本地构建、无远程仓库摘要；镜像更新后必须重跑 M6/M7/M8 三类验证，不得沿用旧证据。