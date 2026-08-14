# 生产部署指南（Docker 单机方案）

## 架构决策

**单机单进程 + 线程池任务队列**：本产品负载特征（单用户/团队、每日几份报告、长任务 3~5 分钟）
下，线程池足够且运维最简；SSE 事件总线无需跨进程。
规模化路径（多 worker + Redis + Pub/Sub）已在代码预留（`APP_QUEUE=rq`，`requirements-prod.txt`，
docker-compose 中注释配置）。

## 一键部署（云服务器，以腾讯云轻量 2C4G 为例）

```bash
# 1. 装 Docker（一次）
curl -fsSL https://get.docker.com | sh

# 2. 拉代码（或 scp 上传项目目录）
git clone <你的仓库> semiconductor-agent && cd semiconductor-agent

# 3. 配置密钥（不要提交到 git）
cat > .env <<'EOF'
DEEPSEEK_API_KEY=sk-xxx
API_TOKEN=换成强随机串
EOF

# 4. 构建并启动（首次会构建镜像 + 下载 embedding/reranker 模型，约 10 分钟）
docker compose up -d --build

# 5. 验证
curl http://127.0.0.1:8000/api/health
curl -H "X-API-Token: $API_TOKEN" http://127.0.0.1:8000/api/v1/sessions
```

## HTTPS（Caddy 反代，自动证书）

```bash
# docker-compose.yml 中加：
#   caddy:
#     image: caddy:2-alpine
#     ports: ["80:80", "443:443"]
#     volumes: ["./Caddyfile:/etc/caddy/Caddyfile", "caddy_data:/data"]
# Caddyfile:
#   your-domain.com {
#       reverse_proxy api:8000
#   }
```

## 压测基线（本地开发机实测，spikes/loadtest.py）

| 指标 | 值 |
|---|---|
| 场景 | 20 并发 × 50 请求/worker（health + sessions 列表），共 1000 请求 |
| 错误 | 0 |
| QPS | 1273 |
| P50 / P95 / P99 | 11.8ms / 14.0ms / 77.2ms |
| 研报生成耗时基线 | ~4.5 分钟（含首次知识库构建 ~1 分钟；后续任务 ~3.5 分钟） |

## 运维要点

- `./data` 与 `./reports` 挂载为卷 → 文章库/向量库/模型/研报全部持久化，容器重建不丢
- 模型走 hf-mirror（镜像内已设 `HF_ENDPOINT`）；DeepSeek API 直连
- 定时采集：容器内 `python scripts/collect.py --schedule --hour 8`（或宿主机 cron 调 --once）
- 日志：docker compose logs -f api
