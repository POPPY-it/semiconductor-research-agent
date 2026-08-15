# 市场岗位要求分析：JD 反推项目进化方向

> 来源：2026 大厂/中厂 AI Agent、大模型应用、RAG 岗位招聘信号
> （DeepSeek 一次性放出 17 个 Agent 岗、阿里云 AI Agent 研发岗、上海AI实验室智能体平台岗、Zoom AI Agent Engineer、涂鸦/飞雁等中厂 AI 应用岗）。

## 1. JD 高频技能要求 → 我们的覆盖情况

| 市场要求 | 出现频率 | 我们项目现状 | 差距 |
|---|---|---|---|
| Python 熟练 | 必备 | ✅ 全程 Python | — |
| LLM 应用开发（Prompt/RAG/Agent） | 必备 | ✅ | — |
| RAG：向量库 + Embedding + 检索优化 + rerank | 必备 | ✅ Chroma + 混合检索 + reranker + 实测选型 | — |
| Agent：ReAct/工具调用/多智能体 | 必备 | ✅ CodeAgent + 研究/质检 + 5 工具 | — |
| FastAPI / Docker / 部署上线 | 必备 | ✅ + 压测 + CI | — |
| 评测（RAGAS / 模型评测） | 高频 | ⚠️ 自研离线评测，无 RAGAS 回归 | 部分 |
| **MCP（Model Context Protocol）** | **极高（2026 最热）** | ❌ | **缺** |
| **GraphRAG / 知识图谱** | **高频** | ❌ | **缺** |
| 记忆系统（Mem0/跨会话记忆） | 高频 | ⚠️ 仅会话内多轮 | 部分 |
| 多模态（图表/图片理解） | 中高频 | ❌ | 缺 |
| 可观测（tracing/Langfuse） | 中频 | ⚠️ 有指标，无 tracing 面板 | 部分 |
| LangChain/LangGraph 框架经验 | 常写 | ⚠️ 用 smolagents（可补对比经验） | 部分 |
| 微调 LoRA/SFT | 部分岗位 | ❌ | 可选 |

## 2. 结论：市场要什么、我们缺什么

市场核心画像 = **"能做 RAG+Agent 生产级应用，懂评测，会用 MCP，最好懂 GraphRAG 和记忆"**。

我们**已覆盖必备项**，缺口集中在 2026 的**加分热点**：
1. MCP（最高频，最该补）
2. GraphRAG / LightRAG（技术深度 + 高频）
3. RAGAS 评测回归（生产级收尾）
4. 跨会话记忆（Mem0）
5. 多模态（可选）

## 3. 进化路线（按市场价值排序）

| 优先级 | 功能 | 对应 JD 关键词 | 成本 |
|---|---|---|---|
| P1 | MCP 客户端集成 | MCP、工具调用 | 低 |
| P2 | LightRAG 图谱混合检索 | GraphRAG、知识图谱 | 中 |
| P3 | RAGAS 评测回归进 CI | 评测、质量 | 低 |
| P4 | 跨会话记忆（Mem0） | 记忆、个性化 | 中 |
| P5 | 多模态（财报图表解析） | 多模态、文档理解 | 中高 |

## 4. 面试话术升级

做完 MCP + GraphRAG + RAGAS 后，项目简介可从"全栈 Agent 产品"升级为：
> "覆盖 2026 大模型应用岗位全栈能力：RAG（向量+图谱混合）、多 Agent、MCP 工具生态、
> 评测回归、企业级部署，并有 6 篇系列博客与 GitHub 仓库佐证。"
