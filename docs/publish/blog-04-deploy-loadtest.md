# 技术博客④：从 0 到上线——一个行业 Agent 产品的部署与压测（初稿）

> 系列收官篇。前三篇讲了内核、检索、多 Agent；这一篇讲怎么把一个跑在笔记本上的
> demo 变成可以给面试官打开链接的产品：部署决策、压测数据、上线清单。

## 部署前先回答一个问题：要不要上分布式

我的产品形态是"单用户提交选题 → 3~5 分钟生成研报"。很多教程上来就是
Celery + Redis + 消息队列全家桶，但我先算了一笔账：

- 负载特征：每天几次任务、每次任务 3~5 分钟、并发几乎为 1
- 分布式收益：多 worker 并行、任务不丢
- 分布式成本：Redis 运维、跨进程 SSE 事件推送（内存事件总线失效，要上 Pub/Sub）、
  部署复杂度翻倍

结论：**单机单进程 + 线程池队列**。但代码里我把队列做成了双实现——`ThreadPoolQueue`
（开发/单机）和 `RQQueue`（生产规模化），切换只改一个环境变量 `APP_QUEUE=rq`。
**先按真实负载做最小可用，再留好规模化开关**，比一上来就堆架构诚实得多。

## Docker：一个镜像装下前后端

多阶段构建：Node 阶段 `vite build` 前端产物 → Python slim 运行时阶段，
FastAPI 直接托管 `frontend/dist`（同源部署，免 CORS 免反代）。

```dockerfile
FROM node:20-alpine AS frontend-build
# ... vite build

FROM python:3.10-slim
COPY --from=frontend-build /build/dist ./frontend/dist
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

`docker compose up -d --build` 一条命令上线；`data/` 和 `reports/` 挂载为卷，
文章库、向量索引、模型、研报产物全部持久化，容器重建不丢。

## 压测：先测轻端点，长任务是另一条基线

我写了 20 并发的 asyncio 压测脚本，打 health 和会话列表两个轻端点，1000 请求：

| 指标 | 值 |
|---|---|
| 错误数 | 0 |
| QPS | **1273** |
| P50 / P95 / P99 | 11.8ms / 14.0ms / 77.2ms |

研报生成走的是另一条基线：约 4.5 分钟（含首次知识库构建约 1 分钟，之后约 3.5 分钟），
大头是 LLM 多步推理，不是我的服务框架。**压测的意义不是数字好看，而是找到瓶颈在哪
一层**——瓶颈在 LLM 调用，那优化的方向就是提示词工程、步数裁剪和模型分级，而不是
给 FastAPI 加缓存。

## 上线清单（照抄可用的那种）

1. 云服务器（腾讯云轻量 2C4G 足够）装 Docker
2. `.env` 配好 `DEEPSEEK_API_KEY` 和强随机的 `API_TOKEN`（**别提交 git**）
3. `docker compose up -d --build`，curl health 验证
4. HTTPS 用 Caddy 反代（自动续证书，5 行配置）
5. 定时采集：`python scripts/collect.py --schedule --hour 8` 常驻

## 系列复盘

四篇文章写下来，这个项目给我的最大收获是：**"把开源内核变成自己的产品"不是改改
名字，而是把每一层都亲手搭过一遍**——内核我精读了 1800 行、检索我测了 5 种方案、
质检链路我跑了真实报告、部署我写了 Dockerfile 还压了测。现在面试官问任何一层，
我都有代码、有数据、有故事。

共勉。

---
*系列文章：① 内核剖析 · ② RAG 实测 · ③ 多 Agent 与质检 · ④ 本文*
