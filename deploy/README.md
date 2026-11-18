# VeriFix 部署说明

## 阶段一：ECS 单机（docker compose）

1. 准备主机：2 vCPU / 4 GiB，Ubuntu 22.04，开放 8443（不使用 80/443）。
2. 生成证书：`bash scripts/gen_self_signed_cert.sh`（生产替换为 Let's Encrypt 证书）。
3. 填写环境：复制 `deploy/.env.example` 为 `deploy/.env`，至少设置 `VERIFIX_WEBHOOK_SECRET`。
4. 启动：`docker compose -f deploy/docker-compose.yml up -d --build`。
5. 验证：`https://<IP>:8443/healthz`、`https://<IP>:8443/readyz`、`https://<IP>:8443/`（控制台）。
6. 本地无 Docker 时的等价验证：`python scripts/verify_8443.py`（uvicorn 直接监听 8443 TLS）。

## 阶段二：CCE（Kubernetes）

按顺序应用 `deploy/cce/01..07`：

```
kubectl apply -f deploy/cce/01-config.yaml
kubectl apply -f deploy/cce/02-secret.yaml
kubectl apply -f deploy/cce/03-api-deployment.yaml
kubectl apply -f deploy/cce/04-mcp-deployment.yaml
kubectl apply -f deploy/cce/05-service.yaml
kubectl apply -f deploy/cce/06-ingress.yaml
kubectl apply -f deploy/cce/07-hpa.yaml
```

不变式：

- 运行状态全部外置（空态 Pod 可替换），事件与证据落独立存储/卷。
- MCP 作为独立 Deployment，与 API 解耦，可单独替换。
- Ingress 仅暴露 8443，`/healthz` 与 `/readyz` 不走缓存。
- Secret 不落盘到镜像；镜像内不含任何凭据。

## 依赖连通性

`/readyz` 探测 RDS / Redis / OBS / MaaS / CodeArts 五项：
未配置为 `not_configured`，连接失败为 `unavailable`，任一不可用整体为 `degraded`。

## 灰度与回滚

`python scripts/gray_release.py` 演练 5% → 50% → 100% 与失败回滚（本地模拟，不依赖云资源）。
