# W2 技术预研报告（RAG 检索 / SSE 流式 / 任务队列选型）

## 1. RAG 检索链路（已实测）

**组件选型**（预研方案，W4 落地 M2）：
- Embedding：fastembed + BAAI/bge-small-zh-v1.5（ONNX 推理，CPU 即可，模型 94MB；生产可切 bge-m3 API）
- 向量库：Chroma 1.5.9（本地持久化 `data/vectorstore/`，生产可平滑迁移 pgvector/Milvus）
- BM25：rank-bm25 + 自研字符 bigram 分词（jieba 在 Python 3.10 构建失败，零依赖替代）
- 融合：RRF（k=60）

**评测数据**：`data/raw/` 真实采集样本 45 篇（13 新闻 + 32 财报披露），5 条中文查询，Recall@5 / MRR。

**结果**（`spikes/results/rag_eval.json`）：

| 方式 | Recall@5 | MRR | 平均延迟 |
|---|---|---|---|
| BM25-only | **0.65** | 0.70 | 0.1ms |
| Vector-only | 0.425 | 0.40 | 9.1ms |
| Hybrid-RRF | 0.575 | 0.70 | 4.6ms |

**结论与解释**：
1. 短文档 + 关键词型查询下，BM25 领先；语义向量在查询与文档用词不一致时才有优势
2. RRF 简单平均稀释了 BM25 强信号 → W4 计划：加权 RRF（BM25:vector = 0.7:0.3）+ bge-reranker 重排
3. 评测集局限：粗粒度关键词标注、SEMI 查询在语料中零相关文档（recall 恒 0）→ W4 换文章正文语料重测

**踩坑记录**：chromadb 拒绝 numpy float32 → `.tolist()`；HF 直连超时 → `HF_ENDPOINT=https://hf-mirror.com`。

## 2. SSE 流式（已跑通，代码在 backend/app/main.py）

验证链路：`POST /api/agent/stream` → `agent.run(task, stream=True)` 生成器 → sse-starlette `EventSourceResponse`。
实测事件序列：`task → step(ToolCall) → step(ActionOutput) → step(ActionStep) → step(FinalAnswerStep) → done`，前端工作台（M6）将直接消费这个协议。
W5 落地时：队列模式下改用 `step_callbacks` → Redis Pub/Sub → SSE 推送。

## 3. 任务队列选型（结论：RQ + Redis；开发态 ThreadPool 适配）

| 维度 | Celery | RQ |
|---|---|---|
| 复杂度 | 高（beat/worker/broker 全套） | 低（enqueue/worker 两个概念） |
| 监控 | Flower 面板 | 自带 rq-dashboard（轻） |
| 适合场景 | 多服务、复杂路由 | **单服务、少任务类型（我们的场景）** |
| Python 风格 | 面向框架配置 | 函数即任务，更 Pythonic |

**决策**：生产用 **RQ + Redis**（Docker Compose 起 Redis，本机无 Docker 不影响开发）；
开发态实现 `TaskQueue` 接口 + ThreadPoolExecutor 适配器（无 Redis 跑通全链路，W5 落地）。
定时采集独立用 APScheduler，不引入 Celery beat。

## 4. W2 → W3 衔接

- M1（W3）：把 Day 6 的两个采集器重构为统一适配器接口 + APScheduler 定时 + SQLite 入库
- M2（W4）：按本报告结论实现加权 RRF + reranker，用文章正文语料重测
