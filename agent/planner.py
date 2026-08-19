"""显式规划（P1-3 + STORM 路线升级）：Researcher 动笔前先产出一份规划。

两档实现：
1. 规则模板（build_plan）：确定性、零成本——大纲来自模板分节 + 每节检索建议 + 两条数字硬约束；
2. LLM 多视角大纲（build_plan_llm，STORM 1.1/1.2）：一次 LLM 调用，模拟读者视角生成
   章节（title/focus/search_queries），失败自动回落规则模板——大纲是"检索之后"的规划，
   每节带推荐检索词，驱动"分节写作 + 段落级引用"。

企业认可改法 §5-P1-3 允许"一次便宜的 LLM 调用，或规则模板"——这里是两者组合。
"""
from __future__ import annotations

import json
import re

PLANNER_PROMPT = """你是研报规划师。给定选题与模板分节要求，输出一份写作大纲（仅 JSON）。

要求：
1. 先模拟 3 类读者视角（行业分析师 / 投资者 / 技术研究者），分别想 1-2 个关键问题；
2. 基于这些视角问题生成 4~6 个章节，尽量贴合模板分节；
3. 每章包含：title（章节标题）、focus（本节要回答的核心问题）、search_queries（2-3 个推荐检索词，中英混合，供检索工具使用）。

只输出 JSON，不要任何其他文字：
{"sections": [{"title": "...", "focus": "...", "search_queries": ["...", "..."]}]}
"""


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
        "",
        "段落引用纪律：**每个段落结尾必须带 [来源](url) 链接**；没有来源的段落不允许出现。",
    ]
    return "\n".join(lines)


def _extract_plan_json(text: str) -> dict | None:
    """从 LLM 输出里取第一个完整 JSON 对象（花括号配对，同质检解析策略）。"""
    if isinstance(text, dict):
        return text
    if not isinstance(text, str):
        return None
    for start in [m.start() for m in re.finditer(r"\{", text)]:
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    return None


def build_plan_llm(topic: str, template: dict | None, model) -> dict | None:
    """LLM 多视角大纲（STORM 路线）：一次调用生成章节 + 检索词。

    返回 {"sections": [...]}；任何失败返回 None（调用方回落规则模板）。
    注意：model 应为裸模型（不经 BudgetedModel 包装，规划一次调用成本极低）。
    """
    template = template or {}
    try:
        resp = model.generate(
            [
                {"role": "system", "content": PLANNER_PROMPT},
                {
                    "role": "user",
                    "content": f"选题：{topic}\n模板分节要求：{template.get('sections', '') or '自行拟定'}",
                },
            ]
        )
        text = getattr(resp, "content", None) or str(resp)
        data = _extract_plan_json(text)
        if not data or not isinstance(data.get("sections"), list) or not data["sections"]:
            return None
        for s in data["sections"]:
            if not s.get("title"):
                return None
        return data
    except Exception:  # noqa: BLE001 —— 规划失败不阻塞任务
        return None


def format_plan(plan: dict, topic: str) -> str:
    """把 LLM 大纲转成注入 Researcher 的规划文本。"""
    lines = [
        "## 撰写规划（LLM 多视角大纲，先规划后执行）",
        "",
        f"- 选题：{topic}",
        f"- 大纲（{len(plan['sections'])} 节）：" + " → ".join(s["title"] for s in plan["sections"]),
        "",
        "分节写作要求：逐节撰写——每节先按 search_queries 完成检索，再写该节；",
        "写完一节再进入下一节；**每个段落结尾必须带 [来源](url)**。",
        "",
    ]
    for i, s in enumerate(plan["sections"], 1):
        lines.append(f"{i}. **{s['title']}**：{s.get('focus', '')}")
        lines.append(f"   推荐检索词：{' / '.join(s.get('search_queries', []))}")
    lines += [
        "",
        "两条硬约束（违反会被质检判不通过）：",
        "1. **精确财务数字（金额/百分比/增速）必须来自 query_filings 或 search_knowledge 的 SEC 语料，并附来源链接**；",
        "2. **禁止出现无来源的精确数字**——检索不到就写定性表述或明确说明数据缺失。",
    ]
    return "\n".join(lines)


def _rule_sections(template: dict | None) -> list[dict]:
    """规则模板的章节结构（title/focus/queries），供分节执行使用。"""
    template = template or {}
    titles = [s.strip() for s in str(template.get("sections", "")).split("/") if s.strip()]
    if not titles:
        titles = ["概述", "关键动态", "数据透视", "展望"]
    sections = []
    for t in titles:
        if "财务" in t or "业绩" in t or "营收" in t or "数据" in t or "资产负债表" in t:
            queries = ["{公司} 财报 营收 毛利率", "SEC 财报 披露"]
        elif "概况" in t or "背景" in t or "竞争力" in t or "护城河" in t or "风险" in t:
            queries = ["{公司} 竞争力 行业地位", "半导体 产业链"]
        elif "展望" in t or "趋势" in t or "开放问题" in t:
            queries = ["半导体 展望 趋势 2026", "行业 预测"]
        else:
            queries = ["半导体 行业动态", "半导体 新闻"]
        sections.append({"title": t, "focus": "", "search_queries": queries})
    return sections


def build_plan_structured(topic: str, template: dict | None, model) -> tuple[str, list[dict]]:
    """规划 + 结构化章节（分节独立 run 用）。

    返回 (plan_text, sections)；sections = [{"title", "focus", "search_queries"}]。
    优先 LLM 多视角大纲（失败回落规则模板）。
    """
    llm_plan = build_plan_llm(topic, template, model)
    if llm_plan:
        return format_plan(llm_plan, topic), llm_plan["sections"]
    return build_plan(topic, template), _rule_sections(template)
