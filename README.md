# 半导体研究 Agent（Semiconductor Research Agent）

> GitHub：https://github.com/POPPY-it/semiconductor-research-agent
>
> **一句话定位**：给定一个半导体行业选题，用工具检索公开财报与论文，按规划写出带引用的报告，
> 并用可复现的评测集衡量「引用是否站得住、工具有没有乱调」。
>
> 基于 [smolagents](https://github.com/huggingface/smolagents)（Apache-2.0）内核二次开发；
> **内核复用开源，自研部分 = 编排（研究/质检双角色）+ 检索与治理 + 可评测 Harness**。
> 学术（arXiv）、医学（PubMed）、问答、MCP 等均为**扩展点**，不是主叙事。

## 主链路（README 口径 = 代码实现）

```
采集适配器（SEC 财报 / arXiv / PubMed / 新闻 RSS）
  → SQLite 文章库 → 分块 / 混合检索（BM25+向量+加权 RRF）/ bge-reranker / 实体共现图
  → 研究 Agent（CodeAgent，工具：知识库 / SEC / arXiv / S2 / PubMed / 图谱 / 图表 / MCP）
  → 质检 Agent（按「数字必须带出处」卡关，输出 JSON）
  → 修订 ≤2 轮（失败只修订问题段落）→ 质检交付策略（caveat 横幅 / reject 拒交）
  → 报告落盘 + 轨迹 JSONL + FastAPI/SSE 工作台
```

## 可验证的硬点（每一条都能指到代码/文档）

1. **检索有实验依据**：加权 RRF（BM25 0.7 / 向量 0.3）来自 W2 实测（`docs/w2-spike-report.md`）；char-bigram 替代 jieba 是环境约束下的工程选择。
2. **质检有产品策略**：`caveat` 打横幅、`reject` 拒交；质检是"可验证性门槛"而非真伪判定（`docs/w4-m2m3-report.md`）。
3. **服务层不是空壳**：Cookie 鉴权、限流、中断会话恢复、任务重试、索引与生成互斥、Prometheus 指标（`tests/test_enterprise.py` 覆盖）。
4. **评测有方法论反思**：真实语料 Recall@5=0.127 已归因到粗粒度标注；faithfulness 偏低归因到 judge 上下文（`docs/p3-eval-report.md`）。
5. **MCP 是真接上的**：`github` / `fetch` 两个 stdio Server，网页端可增删管理；每个 MCP 工具映射为**独立 Tool**（schema 来自 MCP inputSchema），不再用 `mcp_call` 调度器。支持 **HTTP 传输的 MCP 端点**（如搜索代理网关）：`.env` 配置 `MCP_HTTP_URL` + `MCP_HTTP_TOKEN`（不进 git）+ `MCP_HTTP_TOOLS`（后缀白名单，避免一次挂 24 个工具），默认挂 `serper_news` / `tavily_search` / `serper_scholar` / `serper_patents` 四个实时搜索工具（实测：`serper_news` 返回中文行业新闻、`tavily_search` 命中台积电 7 月营收公告）。
6. **工具层可治理**：每个工具一份 schema 元信息（必填/范围/超时，`agent/tools.py` 的 `TOOL_META`）；外部 API（arXiv/S2/PubMed）统一超时 + 429/5xx 指数退避 + 降级文案——**人为注入故障（`SIMULATED_API_FAILURES`）任务仍能用知识库+SEC 出报告**；参数校验失败回给模型「哪错了」，不抛到编排器外面；写稿与问答检索统一走 `search_reranked`。
7. **合规边界写进模板**：`basic_research`（研投）禁止目标价/估值/买卖建议、财务数字强制 SEC 来源、自动追加免责声明；`medical_survey` 禁止诊疗建议并声明证据等级（`tests/test_orchestrator_units.py` 断言）。
8. **先规划后执行（P1-3）**：Researcher 动笔前注入规则模板规划（大纲分节 + 每节检索建议 + 「数字必须来自 SEC/知识库、禁止无来源精确数字」两条硬约束，`agent/planner.py`），规划随轨迹落盘可回放；质检要求问题注明所属小节。

## 技术栈

| 层 | 选型（与代码一致） |
|---|---|
| Agent 内核 | smolagents 1.26.0（CodeAgent，仅复用内核） |
| LLM | DeepSeek `deepseek-chat`（OpenAI 兼容；可配备用模型） |
| 任务队列 | **ThreadPoolQueue**（默认；RQ+Redis 为预留扩展，未启用） |
| 鉴权 | **共享 API Token → HttpOnly Cookie**（单用户；非多租户 JWT） |
| 知识层 | 分块 + BM25/向量加权 RRF + bge-reranker（Chroma）+ **实体共现图**（词典匹配 + 共现边） |
| 记忆 | **跨会话偏好记忆**（LLM 抽取 → SQLite + 向量召回） |
| 服务层 | FastAPI + SSE + 限流 + 预算熔断 + 指标 |
| 前端 | React + Vite + TS + Ant Design |
| 部署 | Docker Compose（单机） |

## 数据源（实际接入的 6 个）

SEC EDGAR 财报（32 篇全文）、arXiv 论文（49 篇）、PubMed 生物医药文献（32 篇）、新浪科技 / IT之家 / Google News RSS。
> 说明：SEMI / SIA / 集微网等曾在计划中提及，实际未接入——以本清单为准。

## 报告类型

| 类型 | 场景 | 定位 |
|---|---|---|
| daily / weekly / deep | 半导体行业研报（财报 + 新闻） | **主线** |
| basic_research | 基本面分析（研投：财务表现/竞争力，仅研究不构成投资建议，SEC 来源强制） | **主线** |
| survey | 学术调研（arXiv + PubMed 实时检索） | 扩展点 |
| medical_survey | 医学综述（PICO + 证据等级 + 免责声明） | 扩展点 |

## 评测（Harness 路线）

- 检索指标：Recall@k / MRR / Precision（`agent/eval.py`，CI 回归用 mini 语料）
- LLM-judge：faithfulness / answer_relevance
- 方法论反思：见 `docs/p3-eval-report.md`
- **Agent 级评测（成功率 / 无引用数字率 / 步数 / 成本）**：24 条任务集（`eval/tasks.json`，含研投基本面 t21~t24）+ `agent/harness.py`；合并指标见 `eval/metrics.md`（成功率 0.652 / 无引用率 0.577，2026-08-17）
- 工具治理测试：超时降级 / 退避重试 / 参数校验文案 / MCP 独立 Tool / 检索统一（`tests/test_tools_governance.py`，P1-2）

## 工具治理（P1-2）

- **schema 元信息**：`agent/tools.py` 的 `TOOL_META`——每个工具的必填字段、取值范围、超时、来源、降级策略。
- **参数校验**：越界/空值/非法 JSON 等返回「参数错误：…」给模型，由模型自行改用其他工具，不抛到编排器外面。
- **外部 API 统一治理**：`external_get()`——连接类错误立即降级（不重试），429/5xx 指数退避最多 3 次，全部失败返回降级文案（含替代工具提示）；`SIMULATED_API_FAILURES=arxiv` 可注入故障做验收演示。
- **MCP 独立 Tool**：`build_mcp_tools()` 把每个 MCP 工具映射成独立 Tool（名字/描述/inputs 直接来自 MCP inputSchema，必填字段 required），模型不再需要背工具名拼 JSON。
- **检索统一**：写稿 `search_knowledge` 与问答证据面板都走 `search_reranked`（混合召回 + bge-reranker 精排）。

## 快速开始

```powershell
# 依赖：Python 3.10+
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 配置 .env（已 gitignore）：DEEPSEEK_API_KEY / API_TOKEN 等

# 启动完整产品（需先构建前端）
cd frontend; npm install --registry=https://registry.npmmirror.com; npm run build; cd ..
.venv\Scripts\python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
# 浏览器打开 http://127.0.0.1:8000

# 数据采集（SQLite 去重入库） / 定时
.venv\Scripts\python scripts\collect.py --once
.venv\Scripts\python scripts\collect.py --schedule --hour 8
```

## 进度与对齐说明

- 博客系列 6 篇已发布（掘金）；测试 43 个全绿；CI 三流水线（pytest + 前端构建 + Docker 构建）
- `docs/企业认可改法.md`：第三方审阅整改建议（已修复：fallback 切换、记忆向量错位、JSON 解析；P0-1 口径统一见本 README）
- `PLAN.md` 为原始施工图，架构以本 README 为准
