# 多领域研究助手：半导体研报 + 学术调研 + 生物医药（Research Agent）

> GitHub：https://github.com/POPPY-it/semiconductor-research-agent
> 秋招项目：基于 [smolagents](https://github.com/huggingface/smolagents)（Apache-2.0）内核二次开发的
> **多领域研究助手**——输入选题，自动完成数据采集、混合检索、多 Agent 协作撰写、事实质检，产出带引用溯源的研究报告。
>
> 三领域：**行业研报**（SEC 财报 + 行业新闻）、**学术调研**（arXiv）、**生物医药**（PubMed），实时检索 + 参考文献列表。
> 内核复用开源，其余（数据层 / RAG / 编排 / 服务层 / 前端 / 部署）全部自研。

## 目标与可量化成果

- 接入 ≥6 个真实公开数据源（SEC EDGAR 财报、arXiv 论文、PubMed 生物医药文献、行业新闻 RSS 等）
- 报告所有数字带引用溯源，质检 Agent 交叉校验
- 服务压测报告（QPS / P95 延迟 / 失败率）

## 技术栈

| 层 | 选型 |
|---|---|
| Agent 内核 | smolagents 1.26.0（CodeAgent） |
| LLM | DeepSeek `deepseek-chat`（OpenAI 兼容协议，可配备用模型） |
| 服务层 | FastAPI + 任务队列 + SSE + Cookie 鉴权 + 限流 |
| 知识层 | RAG：分块 + BM25/向量加权 RRF + bge-reranker（Chroma） |
| 前端 | React + Vite + TS + Ant Design |
| 部署 | Docker Compose（单机；RQ+Redis 规模化路径预留） |

## 报告类型

| 类型 | 场景 |
|---|---|
| daily / weekly / deep | 行业研报（SEC 财报 + 行业新闻） |
| survey | 学术调研（arXiv + PubMed 实时检索 + 参考文献列表） |
| medical_survey | 医学综述（PubMed + PICO 框架 + 证据等级 + 免责声明） |

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

# 启动完整产品（后端 API + 前端工作台，需先构建前端）
cd frontend; npm install --registry=https://registry.npmmirror.com; npm run build; cd ..
.venv\Scripts\python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
# 浏览器打开 http://127.0.0.1:8000 （前端开发模式：frontend 下 npm run dev）

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
- [x] W4 M2 RAG 落地（长文档语料 + 分块 + 加权 RRF + reranker，评测见 `docs/w4-m2m3-report.md`）
- [x] W4 M3 多 Agent 编排（研究/质检/修订循环，实测生成带引用周报）
- [x] **博客③已发布**：[多 Agent 协作与质检链路](https://juejin.cn/post/7673807945507242018)
- [x] W5 M4 研报模板 + M5 服务层（任务队列/会话/SSE/鉴权，冒烟实测）
- [x] W6 M6 前端工作台（React+antd，浏览器 E2E 验证通过）
- [ ] W7 生产化上线（Docker/HTTPS/压测）+ 博客④ → W8 面试打磨

详细计划见 [PLAN.md](PLAN.md)。
