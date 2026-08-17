"""显式规划（P1-3）：Researcher 动笔前先产出一份短规划。

企业认可改法 §5-P1-3：「在 Researcher 跑之前，先产出一份短规划（可用一次便宜的
LLM 调用，或规则模板）」——本实现用**规则模板**（确定性、零成本、可评测）：

- 大纲来自 REPORT_TEMPLATES 的分节定义；
- 每节给出检索建议（工具 + 数据源纪律）；
- 明示「数字必须来自 SEC / 知识库」「禁止无来源精确数字」两条硬约束，
  与 Harness 的「无引用数字率」指标口径一致。

规划注入 Researcher 的任务前缀，并随轨迹落盘（trace.meta.plan），可回放。
"""
from __future__ import annotations


def build_plan(topic: str, template: dict | None = None) -> str:
    """规则模板生成撰写规划；template 为 REPORT_TEMPLATES[report_type]。"""
    template = template or {}
    sections = [s.strip() for s in str(template.get("sections", "")).split("/") if s.strip()]
    if not sections:
        sections = ["概述", "关键动态", "数据透视", "展望"]

    lines = [
        "## 撰写规划（先规划，后执行）",
        "",
        f"- 选题：{topic}",
        f"- 大纲（{len(sections)} 节）：{' → '.join(sections)}",
        "",
        "每节检索建议（按需调整，但每个数字必须能回溯到工具返回）：",
    ]
    for i, sec in enumerate(sections, 1):
        if "财务" in sec or "业绩" in sec or "营收" in sec or "数据" in sec or "资产负债表" in sec:
            hint = "优先 query_filings（SEC 财报披露），再用 search_knowledge 补新闻语境"
        elif "概况" in sec or "背景" in sec or "竞争力" in sec or "护城河" in sec or "风险" in sec:
            hint = "search_knowledge（知识库全文）+ search_graph（实体关联）"
        elif "展望" in sec or "趋势" in sec or "开放问题" in sec:
            hint = "search_knowledge + 可选 search_arxiv / search_semantic_scholar（定性引用）"
        else:
            hint = "search_knowledge（知识库全文）"
        lines.append(f"{i}. 「{sec}」：{hint}")
    lines += [
        "",
        "两条硬约束（违反会被质检判不通过）：",
        "1. **精确财务数字（金额/百分比/增速）必须来自 query_filings 或 search_knowledge 的 SEC 语料，并附来源链接**；",
        "2. **禁止出现无来源的精确数字**——检索不到就写定性表述或明确说明数据缺失。",
    ]
    return "\n".join(lines)
