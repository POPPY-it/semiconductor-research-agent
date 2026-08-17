# P1-2 工具治理整改报告

> 依据：[企业认可改法.md §4.5/§5-P1-2](./企业认可改法.md)（"工具层收成可治理"）
> 完成时间：2026-08；测试：`tests/test_tools_governance.py`（14 例，全绿；全仓 60 例全绿）

## 1. 改了什么（4 条硬要求逐条对应）

### 1.1 每个工具一份 schema 元信息

新增 `agent/tools.py::TOOL_META`：7 个工具各自的**必填字段 / 取值范围 / 超时 / 来源 / 降级策略**：

| 工具 | 必填 | 范围 | 超时 | 来源 |
|---|---|---|---|---|
| search_knowledge | keywords | limit 1~10 | 本地 | 知识库（BM25+向量+精排） |
| query_filings | company | limit 1~10 | 本地 | SEC 财报索引 |
| search_arxiv | query | max_results 1~10 | 15s | arXiv API（官方限速 ≥3s/请求） |
| search_semantic_scholar | query | limit 1~10 | 15s | Semantic Scholar Graph API |
| search_pubmed | query | limit 1~10 | 20s | NCBI E-utilities |
| search_graph | 无 | — | 本地 | 实体共现图 |
| generate_chart | chart_type/data/title | bar/line/pie | 本地 | matplotlib |

### 1.2 参数校验失败回给模型，不抛到编排器外面

所有工具开头做校验（`_check_range` / `_check_nonempty`），失败直接 `return "参数错误：…"`，
由模型读到后自行改用其他工具；极端输入（None、"abc"、非法 JSON）也不会把异常抛到编排器。

### 1.3 外部 API 统一：超时、429 退避、降级文案

`agent/tools.py::external_get()` 统一收口：

- **连接类/超时错误**（ConnectionError/Timeout）：不重试，立即返回降级文案
  （企业验收点：单源故障不炸整单）；
- **429/5xx**：指数退避重试最多 3 次（S2 匿名限流重，退避基数 4s；arXiv 3s 限速前置等待）；
- 全部失败返回「XX 暂不可用：…可改用 search_knowledge / query_filings」式文案；
- **故障注入钩子** `SIMULATED_API_FAILURES=arxiv`（逗号分隔 URL 域名片段）：
  命中即模拟失败，用于可复现地演示降级行为。

### 1.4 MCP 拆成独立 Tool

`agent/mcp_client.py` 重写：`build_mcp_tools(specs) -> list[Tool]`——

- 每个 MCP 工具映射成一个独立 smolagents Tool，名字/描述/inputs 直接来自
  MCP `inputSchema`（必填字段 required → nullable=False，其余 nullable=True）；
- 模型不再需要「先背工具名再拼 JSON」；
- forward 内统一兜底：异常返回「MCP 工具 XX 调用失败…可改用 search_knowledge」；
- 删除了 `mcp_call(tool_name, json)` 调度器（README/PLAN 同步更新）。

### 1.5 写稿/问答检索统一

问答证据面板从 `search_hybrid` 改为 `search_reranked`（与写稿 `search_knowledge` 完全同一套
「混合召回 + bge-reranker 精排」），修复 §4.5 指出的「一处 reranked 一处 hybrid」。

## 2. 验收（照抄 §5-P1-2 的验收标准）

> **验收**：人为把 arXiv 超时，任务仍能用知识库+SEC 出一版带 caveat 的报告，而不是整单炸掉。

演示方法（可复现）：

```powershell
$env:SIMULATED_API_FAILURES='arxiv'
.venv\Scripts\python scripts\run_harness.py --limit 13   # t13 是"存内计算调研"，必用 search_arxiv
```

故障注入下 t13 的实际表现（2026-08-17 实测，`reports/output/report_survey_20260817_145234.md`）：

- ✅ 任务**成功完成**：产出 5,545 字学术调研报告，质检 `{"passed": true, "issues": []}`（2 轮修订）；
- ✅ 轨迹中多次出现「arXiv 暂不可用：故障注入（SIMULATED_API_FAILURES 命中 ['arxiv']）。可改用 search_knowledge / query_filings…」——降级文案确实到达模型；
- ✅ Agent 自动改用知识库（含已入库 arXiv 论文存档）、PubMed、GitHub MCP 等替代源完成检索与写作；
- ✅ 报告含完整参考文献列表（12 条，arXiv/PubMed/GitHub 链接），无整单炸掉。

额外发现并修复（P1-1 遗留问题）：真实 CodeAgent 轨迹里代码在 `python_interpreter` 的
`arguments` 中而非 `model_output`，导致 P1-1 基线 3 条的 `required_tools` 全被误标 missing。
修复：`collect_agent_steps` 同时扫描两处（去重），`serialize_step` 用 `observations`
回退补全工具返回内容（降级文案可回放）——新增 2 个回归测试锁定。

## 3. 测试与回归

- 新增 `tests/test_tools_governance.py` 14 例：schema 完整性、连接错误立即降级、
  429 退避时序（2s/4s）、重试耗尽降级、故障注入钩子、三个外部工具降级文案、
  参数校验文案（10+ 种非法输入）、MCP 独立 Tool 映射与降级、问答检索统一断言
  （`search_reranked` 被调用且 `search_hybrid` 不再被调用）。
- 全仓 60 例测试全绿；`spikes/mcp_demo.py` 同步改为独立 Tool 调用并实测通过
  （GitHub 搜索返回真实 star 数据、fetch 返回真实网页正文）。

## 4. 面试口径（如实）

- 「工具治理」是**自研**部分：`TOOL_META` / `external_get` / 校验兜底 /
  MCP 工具映射都是本仓库代码，不依赖 smolagents 内核；
- 仍如实说明：MCP 调用时按需拉起 stdio 子进程（演示规模；生产级长驻会话池未做）；
- 故障注入钩子是企业化验收手段，不是测试造假——README 与代码注释均明示。
