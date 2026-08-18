"""P1-3 显式规划测试：规则模板规划内容 + generate 注入规划 + 轨迹落盘。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.planner import build_plan  # noqa: E402


def test_build_plan_contains_outline_and_constraints():
    template = {
        "sections": "摘要/公司分析/财务表现/风险与展望",
        "min_words": 600,
    }
    plan = build_plan("台积电基本面", template)
    # 大纲分节
    assert "大纲（4 节）" in plan
    assert "摘要" in plan and "财务表现" in plan
    # 财务节建议优先 SEC
    assert "query_filings" in plan
    # 两条硬约束（与 Harness 无引用数字率口径一致）
    assert "精确财务数字" in plan and "SEC" in plan
    assert "禁止出现无来源的精确数字" in plan


def test_build_plan_default_sections_when_template_empty():
    plan = build_plan("任意选题", None)
    assert "大纲（4 节）" in plan
    assert "数据透视" in plan


def test_build_plan_includes_paragraph_citation_rule():
    plan = build_plan("台积电", {})
    assert "每个段落结尾必须带 [来源](url)" in plan


class _FakeModel:
    """生成指定文本的假模型（LLM 规划测试）。"""

    def __init__(self, text):
        self._text = text

    def generate(self, messages, **kw):
        return type("M", (), {"content": self._text})()


def test_build_plan_llm_parses_json_and_format():
    from agent.planner import build_plan_llm, format_plan

    fake = _FakeModel(
        '{"sections": [{"title": "行业背景", "focus": "存储周期位置", '
        '"search_queries": ["存储芯片 周期", "memory cycle 2026"]}, '
        '{"title": "公司分析", "focus": "台积电财务", '
        '"search_queries": ["台积电 营收", "TSMC revenue"]}]}'
    )
    plan = build_plan_llm("存储行业", {"sections": "行业背景/公司分析"}, fake)
    assert plan is not None
    assert len(plan["sections"]) == 2
    assert plan["sections"][0]["title"] == "行业背景"

    text = format_plan(plan, "存储行业")
    assert "LLM 多视角大纲" in text
    assert "行业背景" in text and "台积电 营收" in text
    assert "每个段落结尾必须带 [来源](url)" in text


def test_build_plan_llm_falls_back_on_garbage():
    from agent.planner import build_plan_llm

    assert build_plan_llm("x", {}, _FakeModel("不是 JSON")) is None
    assert build_plan_llm("x", {}, _FakeModel('{"sections": []}')) is None

    class _Boom:
        def generate(self, messages, **kw):
            raise RuntimeError("llm down")

    assert build_plan_llm("x", {}, _Boom()) is None  # 失败不阻塞任务


def test_citation_density_metric():
    from agent.traces import citation_density

    md = (
        "第一段有引用 [来源](https://a.com)\n\n"
        "第二段带裸链接 https://b.com\n\n"
        "第三段没有任何来源，只有文字描述，这算未引用段落\n\n"
        "第四段结尾 300 字符内有链接 https://c.com（稍远的距离）"
    )
    d = citation_density(md)
    assert d == 0.75  # 4 段中 3 段带链接（第三段无）
    assert citation_density("") == 0.0


def test_generate_injects_plan_into_researcher_task(tmp_path, monkeypatch):
    """回归：Researcher 首轮任务必须带规划前缀；轨迹 meta 记录 plan。"""
    from agent import orchestrator as orch

    calls: dict[str, list[str]] = {"tasks": []}

    class FakeModel:
        def __init__(self, tag="m"):
            self.tag = tag

    class FakeResearcher:
        def __init__(self, model):
            self.model = model

        def run(self, task, reset=True):
            calls["tasks"].append(task)
            return "# 报告\n\n正文"

    class FakeQA:
        def __init__(self, model):
            self.model = model

        def run(self, task, reset=True):
            return {"passed": True, "issues": []}

    class FakeRetriever:
        documents = {}

        def search_reranked(self, q, top_k=5):
            return []

    class FakeStore:
        def query_articles(self, **kw):
            return []

    monkeypatch.setattr(orch, "build_model", lambda: FakeModel())
    monkeypatch.setattr(orch, "build_fallback_model", lambda: None)
    monkeypatch.setattr(orch.settings, "TOKEN_BUDGET_CHARS", 1000000)
    monkeypatch.setattr(orch.settings, "MEMORY_DB", tmp_path / "mem.db")
    monkeypatch.setattr(orch.settings, "VECTOR_DIR", tmp_path / "vec")
    monkeypatch.setattr(orch.settings, "TRACE_DIR", tmp_path / "traces")
    monkeypatch.setattr(orch, "CodeAgent", lambda **kw: None)  # 不会被用到
    monkeypatch.setattr(
        orch.ReportPipeline,
        "_build_agents",
        lambda self, model, report_type="weekly": (FakeResearcher(model), FakeQA(model)),
    )
    monkeypatch.setattr(orch.ReportPipeline, "_get_mcp_tools", lambda self: [])

    pipe = orch.ReportPipeline(FakeRetriever(), FakeStore())
    result = pipe.generate("台积电基本面", report_type="basic_research")

    first_task = calls["tasks"][0]
    assert "撰写规划" in first_task
    assert "两条硬约束" in first_task
    assert "禁止出现无来源的精确数字" in first_task
    # 轨迹 meta 记录 plan（P1-3 可回放）
    import json

    trace_files = list((tmp_path / "traces").glob("*.jsonl"))
    record = json.loads(trace_files[0].read_text(encoding="utf-8"))
    assert "plan" in record["meta"]
    assert "大纲" in record["meta"]["plan"]
    # basic_research 合规：报告自动追加投资建议免责声明
    assert result["report"].startswith("# 报告\n\n正文")
    assert "不构成任何投资建议" in result["report"]


def test_data_discipline_in_researcher_instructions(monkeypatch):
    """回归（A 方案）：Researcher 指令必须包含数据纪律——禁止编造精确数字、
    允许「语料未覆盖」留白；QA 指令必须认可诚实留白。"""
    from agent import orchestrator as orch

    class FakeModel:
        pass

    class FakeRetriever:
        documents = {}

        def search_reranked(self, q, top_k=5):
            return []

    class FakeStore:
        def query_articles(self, **kw):
            return []

    built: list[dict] = []

    class FakeAgent:
        def __init__(self, **kw):
            built.append({"instructions": kw.get("instructions", ""), "max_steps": kw.get("max_steps")})

    monkeypatch.setattr(orch, "CodeAgent", FakeAgent)
    monkeypatch.setattr(orch.ReportPipeline, "_get_mcp_tools", lambda self: [])

    pipe = orch.ReportPipeline(FakeRetriever(), FakeStore())
    pipe._build_agents(FakeModel(), "weekly")

    researcher_ins = built[0]["instructions"]  # 第一个是 researcher
    assert "数据纪律" in researcher_ins
    assert "禁止编造任何精确数字" in researcher_ins
    assert "语料未覆盖" in researcher_ins

    assert "诚实留白" in orch.QA_INSTRUCTIONS
    assert "不列入 issues" in orch.QA_INSTRUCTIONS
