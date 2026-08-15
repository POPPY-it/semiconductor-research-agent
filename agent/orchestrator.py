"""多 Agent 研报编排（M3/W8 企业级版）：研究 → 质检 → 修订循环。

W8 加固：
- token 预算熔断（BudgetedModel，超限即停）
- 备用 LLM 自动切换（连接/超时类错误触发一次）
- 质检交付策略在服务层执行（见 report_service._apply_qa_policy）
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.llm import (  # noqa: E402
    BudgetExceededError,
    BudgetedModel,
    build_fallback_model,
    build_model,
    is_connection_error,
)
from backend.app.core import settings  # noqa: E402
from smolagents import CodeAgent, tool  # noqa: E402

RESEARCHER_INSTRUCTIONS = (
    "你是半导体行业资深研究员。只能基于工具检索到的资料撰写报告，禁止编造。\n"
    "要求：1) 用 Markdown 分节；2) 每个关键数字或论断必须注明来源链接；3) 中文。"
    "{extra}"
)

QA_INSTRUCTIONS = (
    "你是事实质检员。校验给定报告的每个数字与论断是否能被检索结果支持。\n"
    "最终必须调用 final_answer 并直接传入 dict（不要输出任何文字说明），例如：\n"
    "final_answer({\"passed\": true, \"issues\": [\"问题1\",\"问题2\"]})"
)

REPORT_TEMPLATES = {
    "daily": {
        "label": "日报",
        "sections": "今日要闻/关键数据/一句话点评",
        "min_words": 300,
    },
    "weekly": {
        "label": "周报",
        "sections": "概述/关键动态/数据透视/展望",
        "min_words": 400,
    },
    "deep": {
        "label": "深度研报",
        "sections": "摘要/行业背景/公司分析/数据透视/风险与展望",
        "min_words": 600,
    },
    "survey": {
        "label": "学术调研",
        "sections": "研究背景/代表工作与方法对比/趋势与开放问题/参考文献列表",
        "min_words": 500,
        "cite_format": "参考文献格式：[n] 论文标题（作者，年份）链接",
    },
}


def _extract_json(text) -> dict | None:
    """质检输出可能是 dict（final_answer 直接传对象）或包裹在文字里的 JSON 字符串。"""
    if isinstance(text, dict):
        return text
    if not isinstance(text, str):
        text = str(text)
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _extract_budget_error(exc: Exception) -> BudgetExceededError | None:
    """沿异常链找到 BudgetExceededError（smolagents 会把它包进 AgentGenerationError）。"""
    cur: BaseException | None = exc
    while cur is not None:
        if isinstance(cur, BudgetExceededError):
            return cur
        cur = cur.__cause__ or cur.__context__
    return None


class ReportPipeline:
    def __init__(self, retriever, store):
        self.retriever = retriever
        self.store = store
        self._mcp_tool = None
        self._memory = None
        self._memory_client = None

    def _get_memory_store(self):
        if self._memory is None:
            from agent.memory import MemoryStore

            embedder = getattr(self.retriever, "embedder", None)
            vector_dir = settings.VECTOR_DIR.parent / "memories"
            self._memory = MemoryStore(settings.MEMORY_DB, embedder=embedder, vector_dir=vector_dir)
        return self._memory

    def _get_memory_client(self):
        if self._memory_client is None:
            from openai import OpenAI

            self._memory_client = OpenAI(base_url=settings.LLM_BASE_URL, api_key=settings.LLM_API_KEY)
            self._memory_client.model_id = settings.LLM_MODEL
        return self._memory_client

    def _extract_and_store_memories(self, question: str, answer: str) -> None:
        """对话后抽取长期记忆并入库（失败不阻断）。"""
        try:
            mem = self._get_memory_store()
            from agent.memory import MemoryStore

            facts = MemoryStore.extract(self._get_memory_client(), f"问：{question}\n答：{answer}")
            for f in facts:
                mem.add(f)
        except Exception:  # noqa: BLE001
            pass

    def _get_mcp_tool(self):
        """懒加载 MCP 工具（首次调用时连接各 MCP Server 发现工具）。"""
        if self._mcp_tool is None:
            import mcp_servers
            from agent.mcp_client import build_mcp_tool

            names = [n.strip() for n in settings.MCP_SERVERS.split(",") if n.strip()]
            specs = [mcp_servers.build_spec(n) for n in names]
            self._mcp_tool = build_mcp_tool(specs) if specs else None
        return self._mcp_tool

    def rebuild(self) -> None:
        """重建知识库索引（新文档入库后调用）。"""
        from agent.knowledge.loader import build_retriever

        self.retriever = build_retriever(
            settings.ARTICLES_DB, settings.VECTOR_DIR, settings.MODEL_DIR, reset=True
        )

    def _make_tools(self):
        retriever = self.retriever

        @tool
        def search_knowledge(keywords: str, limit: int = 5) -> str:
            """在行业知识库（新闻与财报全文）中检索相关内容。

            Args:
                keywords: 空格分隔的中文或英文关键词。
                limit: 返回条数，默认 5。
            """
            hits = retriever.search_reranked(keywords, top_k=limit)
            lines = []
            for doc_id, score in hits:
                doc = retriever.documents[doc_id]
                lines.append(
                    f"[相关度 {score:.2f}] {doc.text[:240]}... (来源: {doc.meta.get('url', '')})"
                )
            return "\n---\n".join(lines) or "（无结果）"

        @tool
        def query_filings(company: str, limit: int = 3) -> str:
            """查询指定公司最近的 SEC 财报披露记录。

            Args:
                company: 公司名，如 NVIDIA / TSMC / Intel / ASML。
                limit: 返回条数，默认 3。
            """
            rows = self.store.query_articles(source="SEC_EDGAR", keyword=company, limit=limit)
            return json.dumps(
                [
                    {"title": r["title"], "date": r["published_at"], "url": r["url"]}
                    for r in rows
                ],
                ensure_ascii=False,
            )

        @tool
        def search_arxiv(query: str, max_results: int = 5) -> str:
            """实时检索 arXiv 学术论文（学术调研用）。

            Args:
                query: 英文检索词或短语，如 "LLM agent" 或 "chip design"。
                max_results: 返回条数，默认 5。
            """
            import re as _re
            import time as _time

            import requests as _requests

            _time.sleep(3.2)  # arXiv 官方限速：请求间隔 ≥ 3 秒
            url = (
                "https://export.arxiv.org/api/query?"
                f"search_query=all:{_requests.utils.quote(query)}"
                f"&sortBy=relevance&max_results={max_results}"
            )
            resp = _requests.get(url, timeout=20)
            resp.raise_for_status()
            import xml.etree.ElementTree as _ET

            ns = {"a": "http://www.w3.org/2005/Atom"}
            root = _ET.fromstring(resp.content)
            lines = []
            for e in root.findall("a:entry", ns):
                title = _re.sub(r"\s+", " ", e.findtext("a:title", "", ns)).strip()
                link = e.findtext("a:id", "", ns)
                year = e.findtext("a:published", "", ns)[:4]
                authors = ", ".join(
                    a.findtext("a:name", "", ns) for a in e.findall("a:author", ns)[:4]
                )
                summary = _re.sub(r"\s+", " ", e.findtext("a:summary", "", ns)).strip()[:400]
                lines.append(f"[{title}] ({authors}, {year}) {link}\n摘要: {summary}")
            return "\n---\n".join(lines) or "（无结果）"

        @tool
        def generate_chart(chart_type: str, data: str, title: str) -> str:
            """生成统计图表 PNG 并返回 Markdown 图片引用（用于在报告中嵌入可视化）。

            Args:
                chart_type: 图表类型，可选 bar（柱状）/ line（折线）/ pie（饼图）。
                data: JSON 字符串，形如 [{"label":"Q1","value":88}, ...]。
                title: 图表标题。
            """
            import json as _json
            import uuid as _uuid

            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as _plt

            _plt.rcParams["font.sans-serif"] = [
                "Microsoft YaHei",
                "SimHei",
                "Arial Unicode MS",
                "DejaVu Sans",
            ]
            _plt.rcParams["axes.unicode_minus"] = False

            rows = _json.loads(data)
            labels = [r.get("label", "") for r in rows]
            values = [float(r.get("value", 0)) for r in rows]
            fig, ax = _plt.subplots(figsize=(8, 4))
            if chart_type == "bar":
                ax.bar(labels, values)
            elif chart_type == "line":
                ax.plot(labels, values, marker="o")
            elif chart_type == "pie":
                ax.pie(values, labels=labels, autopct="%1.1f%%")
            else:
                raise ValueError(f"不支持的图表类型: {chart_type}")
            ax.set_title(title)
            _plt.tight_layout()

            out_dir = settings.CHART_DIR
            out_dir.mkdir(parents=True, exist_ok=True)
            fname = f"{_uuid.uuid4().hex[:10]}.png"
            _plt.savefig(out_dir / fname, dpi=120)
            _plt.close(fig)
            return f"![{title}](/charts/{fname})"

        @tool
        def search_semantic_scholar(query: str, limit: int = 5) -> str:
            """检索学术论文并返回被引次数（引文影响力，学术调研用）。

            Args:
                query: 英文检索词或短语，如 "LLM agent"。
                limit: 返回条数，默认 5。
            """
            import time as _time

            import requests as _requests

            url = "https://api.semanticscholar.org/graph/v1/paper/search"
            params = {
                "query": query,
                "limit": limit,
                "fields": "title,year,citationCount,abstract,url",
            }
            headers = {}
            if settings.SEMANTIC_SCHOLAR_API_KEY:
                headers["x-api-key"] = settings.SEMANTIC_SCHOLAR_API_KEY
            for attempt in range(3):
                resp = _requests.get(url, params=params, headers=headers, timeout=20)
                if resp.status_code == 429:  # 官方限流：指数退避重试
                    _time.sleep(4 * (attempt + 1))
                    continue
                resp.raise_for_status()
                papers = resp.json().get("data", [])
                lines = []
                for p in papers:
                    lines.append(
                        f"[{p.get('title')}] ({p.get('year')}) 被引 {p.get('citationCount')} 次 "
                        f"{p.get('url', '')}\n摘要: {(p.get('abstract') or '')[:300]}"
                    )
                return "\n---\n".join(lines) or "（无结果）"
            return "（Semantic Scholar 暂时限流，请稍后重试）"

        @tool
        def search_graph(entity: str) -> str:
            """查询知识图谱（GraphRAG）：返回与某实体相关的实体及关联强度；传空字符串返回全局核心实体。

            Args:
                entity: 实体名，如 "台积电" / "HBM" / "RAG"；传 "" 查全局核心实体。
            """
            graph = getattr(self.retriever, "graph", None)
            if graph is None:
                return "（知识图谱未构建）"
            if not entity or not entity.strip():
                top = graph.centrality(15)
                return "全局核心实体（按关联度）：\n" + "\n".join(f"- {e}（{w}）" for e, w in top)
            ents = graph.related_entities(entity.strip(), 10)
            if not ents:
                return f"（图谱中未找到与「{entity}」相关的实体）"
            return f"「{entity}」的关联实体（按共现强度）：\n" + "\n".join(
                f"- {e}（共现 {w}）" for e, w in ents
            )

        return (
            search_knowledge,
            query_filings,
            search_arxiv,
            search_semantic_scholar,
            generate_chart,
            search_graph,
        )

    def _build_agents(self, model, report_type: str = "weekly"):
        search_knowledge, query_filings, search_arxiv, search_semantic_scholar, generate_chart, search_graph = self._make_tools()
        template = REPORT_TEMPLATES.get(report_type, REPORT_TEMPLATES["weekly"])
        extra = (
            f"4) 按「{template['sections']}」分节；"
            f"5) 正文不少于 {template['min_words']} 字；"
            f"6) 若报告含可量化对比数据（营收/增速/市场份额等），调用 generate_chart 生成图表嵌入对应小节。"
        )
        if template.get("cite_format"):
            extra += f"7) {template['cite_format']}。"
        mcp_tool = self._get_mcp_tool()
        base_tools = [search_knowledge, query_filings, search_arxiv, search_semantic_scholar, search_graph]
        if mcp_tool is not None:
            base_tools.append(mcp_tool)
        researcher = CodeAgent(
            tools=base_tools + [generate_chart],
            model=model,
            max_steps=12,
            instructions=RESEARCHER_INSTRUCTIONS.format(extra=extra),
        )
        qa = CodeAgent(
            tools=base_tools,
            model=model,
            max_steps=8,
            instructions=QA_INSTRUCTIONS,
        )
        return researcher, qa

    def generate(
        self, topic: str, output_dir: str | Path | None = None, report_type: str = "weekly"
    ) -> dict:
        primary = BudgetedModel(build_model(), budget_chars=settings.TOKEN_BUDGET_CHARS)
        fallback_base = build_fallback_model()
        researcher, qa = self._build_agents(primary, report_type)
        used_fallback = [False]

        def switch_to_fallback() -> None:
            fb = BudgetedModel(fallback_base, budget_chars=settings.TOKEN_BUDGET_CHARS)
            nonlocal researcher, qa
            researcher, qa = self._build_agents(fb, report_type)
            used_fallback[0] = True

        def guarded_run(agent, task, reset: bool = True):
            try:
                return agent.run(task, reset=reset)
            except Exception as e:  # noqa: BLE001
                budget_err = _extract_budget_error(e)
                if budget_err is not None:
                    raise budget_err  # 熔断错误干净抛出，SSE/前端显示可读原因
                if (
                    fallback_base is not None
                    and not used_fallback[0]
                    and is_connection_error(e)
                ):
                    switch_to_fallback()
                    return agent.run(task, reset=reset)
                raise

        mem_ctx = ""
        try:
            memories = self._get_memory_store().search(topic, top_k=3)
            if memories:
                mem_ctx = (
                    "用户长期关注方向（可据此调整报告侧重）：\n"
                    + "\n".join(f"- {m}" for m in memories)
                    + "\n\n"
                )
        except Exception:  # noqa: BLE001
            pass
        draft = guarded_run(researcher, mem_ctx + f"撰写研报：{topic}")
        verdict: dict | None = None
        rounds = 0
        for rounds in range(1, 3):  # 质检不过最多修订 2 轮
            verdict = None
            for _attempt in range(2):  # 解析失败重试一次
                verdict = _extract_json(guarded_run(qa, f"请校验以下报告：\n\n{draft}", reset=False))
                if verdict is not None:
                    break
            if verdict is None:
                verdict = {"passed": False, "issues": ["质检输出不可解析"]}
            if verdict.get("passed"):
                break
            draft = guarded_run(
                researcher,
                f"质检反馈的问题：{json.dumps(verdict.get('issues', []), ensure_ascii=False)}"
                "。请修订报告并重新输出完整 Markdown 报告。",
                reset=False,
            )

        out_dir = Path(output_dir) if output_dir else ROOT / "reports" / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / f"report_{report_type}_{stamp}.md"
        out_path.write_text(draft, encoding="utf-8")

        return {
            "report_path": str(out_path),
            "report": draft,
            "verdict": verdict,
            "revision_rounds": rounds,
            "model_used": ("fallback" if used_fallback[0] else "primary"),
            "budget_used_chars": primary.used_chars,
        }

    def answer_question(self, question: str, history: list[dict] | None = None) -> dict:
        """财报/行业/学术问答（P1：多轮上下文）。

        问答预算为任务预算的 1/10，独立熔断；history 提供最近几轮 Q/A 用于指代消解。
        """
        search_knowledge, query_filings, search_arxiv, search_semantic_scholar, _generate_chart, search_graph = self._make_tools()
        model = BudgetedModel(
            build_model(), budget_chars=max(100_000, settings.TOKEN_BUDGET_CHARS // 10)
        )
        qa_tools = [search_knowledge, query_filings, search_arxiv, search_semantic_scholar, search_graph]
        mcp_tool = self._get_mcp_tool()
        if mcp_tool is not None:
            qa_tools.append(mcp_tool)
        qa_agent = CodeAgent(
            tools=qa_tools,
            model=model,
            max_steps=4,
            instructions=(
                "你是半导体行业与学术研究助手。只能依据检索工具的结果回答，禁止编造。\n"
                "要求：1) 中文回答，简明扼要（300 字内）；2) 关键数字后标注来源链接；"
                "3) 检索不到就明确回答「知识库中没有相关数据」，不要猜测；"
                "4) 若问题含指代（如「它」「那家」「继续」），结合对话历史理解其指向。"
            ),
        )
        context = ""
        if history:
            lines = []
            for h in history[-8:]:
                role = h.get("role")
                content = str(h.get("content", ""))[:300]
                if role == "user":
                    lines.append(f"问：{content}")
                elif role == "assistant":
                    lines.append(f"答：{content}")
            if lines:
                context = "对话历史（仅用于理解上下文与指代，不得重复历史答案）：\n" + "\n\n".join(lines) + "\n\n"
        # 跨会话长期记忆（Mem0-style）：召回相关偏好注入上下文
        try:
            memories = self._get_memory_store().search(question, top_k=4)
            if memories:
                context = (
                    "用户长期记忆（相关偏好/关注方向，可用于个性化，但不得编造用户没说过的话）：\n"
                    + "\n".join(f"- {m}" for m in memories)
                    + "\n\n"
                    + context
                )
        except Exception:  # noqa: BLE001
            pass
        task = context + f"当前问题：{question}"
        answer = str(qa_agent.run(task))
        self._extract_and_store_memories(question, answer)
        sources = []
        seen = set()
        for doc_id, _score in self.retriever.search_hybrid(question, top_k=5):
            doc = self.retriever.documents.get(doc_id)
            if not doc or doc.meta.get("url") in seen:
                continue
            seen.add(doc.meta.get("url"))
            sources.append(
                {
                    "title": str(doc.meta.get("title", ""))[:80],
                    "url": str(doc.meta.get("url", "")),
                }
            )
        return {"question": question, "answer": answer, "sources": sources[:5]}
