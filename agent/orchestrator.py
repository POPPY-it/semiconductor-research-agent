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

        return search_knowledge, query_filings

    def _build_agents(self, model, report_type: str = "weekly"):
        search_knowledge, query_filings = self._make_tools()
        template = REPORT_TEMPLATES.get(report_type, REPORT_TEMPLATES["weekly"])
        extra = (
            f"4) 按「{template['sections']}」分节；"
            f"5) 正文不少于 {template['min_words']} 字。"
        )
        researcher = CodeAgent(
            tools=[search_knowledge, query_filings],
            model=model,
            max_steps=12,
            instructions=RESEARCHER_INSTRUCTIONS.format(extra=extra),
        )
        qa = CodeAgent(
            tools=[search_knowledge, query_filings],
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

        draft = guarded_run(researcher, f"撰写研报：{topic}")
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

    def answer_question(self, question: str) -> dict:
        """财报/行业数据问答（W8 新入口）：轻量 Agent + 直接检索附加参考来源。

        问答预算为任务预算的 1/10，独立熔断。
        """
        search_knowledge, query_filings = self._make_tools()
        model = BudgetedModel(
            build_model(), budget_chars=max(100_000, settings.TOKEN_BUDGET_CHARS // 10)
        )
        qa_agent = CodeAgent(
            tools=[search_knowledge, query_filings],
            model=model,
            max_steps=4,
            instructions=(
                "你是半导体行业数据助手。只能依据检索工具的结果回答，禁止编造。\n"
                "要求：1) 中文回答，简明扼要（300 字内）；2) 关键数字后标注来源链接；"
                "3) 检索不到就明确回答「知识库中没有相关数据」，不要猜测。"
            ),
        )
        answer = str(qa_agent.run(question))
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
