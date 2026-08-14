# 半导体行业研报 Agent（Semiconductor Research Agent）

> 秋招项目：基于 [smolagents](https://github.com/huggingface/smolagents)（Apache-2.0）内核二次开发的
> **行业研报自动生成系统**——从数据采集、RAG 知识库、多 Agent 协作，到研报产出与上线部署的全栈产品。
>
> 内核复用开源，其余（数据层 / RAG / 编排 / 服务层 / 前端 / 部署）全部自研。

## 目标与可量化成果

- 接入 ≥5 个真实公开数据源（SEC EDGAR 财报、行业新闻 RSS 等）
- 每日自动产出 1 份行业日报、每周 1 份深度研报（人工约 2h → Agent ≤15min）
- 报告所有数字带引用溯源，质检 Agent 交叉校验
- 服务压测报告（QPS / P95 延迟 / 失败率）

## 技术栈

| 层 | 选型 |
|---|---|
| Agent 内核 | smolagents 1.26.0（CodeAgent） |
| LLM | DeepSeek `deepseek-chat`（OpenAI 兼容协议） |
| 服务层 | FastAPI + Celery/Redis + SSE（W5） |
| 知识层 | RAG：Chroma + bge-m3，混合检索（W4） |
| 前端 | React + Vite + TS + Ant Design（W6） |
| 部署 | Docker Compose + Nginx + HTTPS（W7） |

## 目录结构

```
semiconductor-agent/
├── PLAN.md                # 8 周施工计划
├── docs/                  # 日志 / 架构笔记 / 技术博客
├── examples/              # 可运行 demo
├── data/                  # 数据层（采集 → 清洗 → 入库）
│   └── collectors/        #   数据源适配器
├── agent/                 # Agent 编排层（研究/数据/质检）
├── backend/               # FastAPI 服务层（W5）
├── frontend/              # React 工作台（W6）
├── tests/                 # 测试
└── smolagents-src/        # 内核源码 clone（精读参考，不入库）
```

## 快速开始

```powershell
# 依赖：Python 3.10+
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 配置 .env（已 gitignore）：
#   DEEPSEEK_API_KEY=sk-xxx
#   DEEPSEEK_BASE_URL=https://api.deepseek.com
#   DEEPSEEK_MODEL=deepseek-chat

# 运行第一个 Agent
.venv\Scripts\python examples\01_hello_agent.py

# 数据采集（3 个数据源，SQLite 去重入库）
.venv\Scripts\python scripts\collect.py --once
# 每日定时采集（常驻）
.venv\Scripts\python scripts\collect.py --schedule --hour 8
```

> 注意：Google News RSS 在本机需走代理（见 `docs/day1-log.md`）；SEC EDGAR 请求必须带自定义 User-Agent。

## 进度

- [x] W1D1 环境搭建 + 第一个 Agent 跑通（`docs/day1-log.md`）
- [x] W1D2-3 内核精读（`docs/architecture-notes.md`）
- [x] W1D4 技术博客①（`docs/blog-01-smolagents-internals.md`）
- [x] W1D5 项目骨架 + git init
- [x] W1D6 数据源验证（SEC EDGAR + Google News RSS + IT之家）
- [x] **博客①已发布**：[1800 行读懂一个 Agent 引擎：smolagents 内核剖析](https://juejin.cn/post/7673531977241247744)
- [x] W2 技术预研（RAG 评测 `docs/w2-spike-report.md`、SSE 流式 `backend/app/main.py`、队列选型）
- [x] **博客②已发布**：[RAG 检索链路实测：BM25 vs 向量 vs 混合](https://juejin.cn/post/7673810995882524672)
- [x] W3 M1 数据管道：适配器接口 + 重试 + SQLite 去重入库 + 采集日志 + APScheduler 定时
- [ ] W4 M2 RAG 落地（加权 RRF + reranker）+ M3 多 Agent 编排 → W5-7 服务层/前端/上线

详细计划见 [PLAN.md](PLAN.md)。
