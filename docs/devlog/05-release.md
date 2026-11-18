# 05 · 部署上线留痕

- 记录时间：2026-11-14
- 最后更新：2026-11-14
- 阶段：赛题 1 CodeArts 五步留痕第 ⑤ 步
- 对应提交前缀：`[step-5/release]`
- 状态：**未执行（阻塞）**

> 本章**没有**发布单、灰度/回滚演练记录与可访问 Demo 地址。未接入云资源，**不伪造**发布记录或 Demo 链接。

## 1. 未执行原因

| 阻塞项 | 实情 |
|---|---|
| 云凭据 | 无华为云账号凭据，无法创建 ECS / CCE / OBS 资源 |
| `CodeArtsDeployPort` | 仅有接口定义与录制桩，未真实对接发布/回滚 |
| 域名与证书 | 无弹性 IP、无 DNS、无 Let's Encrypt 签发环境 |
| 演示地址 | 无公网可达地址 |

## 2. 已就绪的部署资产（本机可校验）

| 资产 | 路径 | 状态 |
|---|---|---|
| 容器编排 | `deploy/docker-compose.yml` | 已提供 |
| API 镜像定义 | `deploy/Dockerfile.api` | 已提供 |
| CCE 清单 | `deploy/cce/` | 已提供（未部署） |
| Nginx / 证书目录 | `deploy/nginx/`、`deploy/certs/` | 已提供（未签发） |
| SQL 初始化 | `deploy/sql/` | 已提供 |
| 评测权限声明 | `deploy/eval-permissions.json` | 已提供 |

## 3. 待执行清单（凭据到位后）

1. ECS 单机：弹性 IP + 8443（不使用 80/443）+ 自签或 Let's Encrypt 证书，启动主服务 + MCP + 沙箱。
2. CCE：主服务 2 副本 + MCP 1 副本 + 独立沙箱节点池（禁特权、独立污点），会话状态外置 Redis。
3. 校验 ECS 与 CCE 两种形态的 API / 鉴权 / SSE 语义一致。
4. `CodeArtsDeployPort` 真实对接：至少一次灰度发布 + 一次回滚演练，记录归档。
5. 产出发布单：版本、镜像 ID、变更清单、回滚点、观察窗口。
6. 提供可访问 Demo 地址（与本地复现方式同时给出）。

## 4. 当前可用的本地运行方式（不构成上线）

```text
docker compose -f deploy/docker-compose.yml up -d
python scripts/smoke_m0.py
```

本地 compose 只能证明编排结构可解析与容器可启动，**不能**替代发布记录、灰度演练与公网 Demo。

## 5. 自检

```text
python scripts/check_devlog.py
```

本章因"未执行"状态被列为阻塞项，不得以说明文字替代真实发布记录。