"""多 Agent 研报编排（M3）：研究 Agent → 质检 Agent → 修订循环。

- 研究 Agent（CodeAgent）：检索知识库 + 财报库，撰写带引用的 Markdown 报告
- 质检 Agent（CodeAgent）：校验事实一致性，输出 JSON 结论
- 编排器：质检不过 → 把问题反馈给研究 Agent 修订（最多 2 轮），最终落盘
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from smolagents import CodeAgent, OpenAIModel, tool  # noqa: E402

MODEL = OpenAIModel(
    model_id=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    api_base=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    api_key=os.environ["DEEPSEEK_API_KEY"],
)

RESEARCHER_INSTRUCTIONS = (
    "你是半导体行业资深研究员。只能基于工具检索到的资料撰写报告，禁止编造。\n"
    "要求：1) 用 Markdown 分节（概述/关键动态/数据透视/展望）；2) 每个关键数字或论断"
    "必须注明来源链接；3) 中文，正文不少于 400 字。"
)

QA_INSTRUCTIONS = (
    "你是事实质检员。校验给定报告的每个数字与论断是否能被检索结果支持。\n"
    "只输出一个 JSON 对象，格式：{\"passed\": true/false, \"issues\": [\"问题1\",\"问题2\"]}"
    "，不要输出其他任何内容。"
)


def _extract_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


class ReportPipeline:
    def __init__(self, retriever, store):
        self.retriever = retriever
        self.store = store

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

    def _build_agents(self):
        search_knowledge, query_filings = self._make_tools()
        researcher = CodeAgent(
            tools=[search_knowledge, query_filings],
            model=MODEL,
            max_steps=12,
            instructions=RESEARCHER_INSTRUCTIONS,
        )
        qa = CodeAgent(
            tools=[search_knowledge, query_filings],
            model=MODEL,
            max_steps=8,
            instructions=QA_INSTRUCTIONS,
        )
        return researcher, qa

    def generate(self, topic: str, output_dir: str | Path | None = None) -> dict:
        researcher, qa = self._build_agents()

        draft = researcher.run(f"撰写研报：{topic}")
        verdict: dict | None = None
        rounds = 0
        for rounds in range(1, 3):  # 质检不过最多修订 2 轮
            verdict = _extract_json(qa.run(f"请校验以下报告：\n\n{draft}"))
            if verdict is None:
                verdict = {"passed": False, "issues": ["质检输出不可解析"]}
            if verdict.get("passed"):
                break
            draft = researcher.run(
                f"质检反馈的问题：{json.dumps(verdict.get('issues', []), ensure_ascii=False)}"
                "。请修订报告并重新输出完整 Markdown 报告。",
                reset=False,
            )

        out_dir = Path(output_dir) if output_dir else ROOT / "reports" / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / f"report_{stamp}.md"
        out_path.write_text(draft, encoding="utf-8")

        return {
            "report_path": str(out_path),
            "report": draft,
            "verdict": verdict,
            "revision_rounds": rounds,
        }
