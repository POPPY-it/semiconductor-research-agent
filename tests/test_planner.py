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


def test_number_citation_rate_metric():
    from agent.traces import number_citation_rate

    md = (
        "台积电净收入 182 亿美元[来源](https://a.com)，同比 +58%。\n"
        "毛利率 54% 是一个没有紧邻来源的数字，后面跟着很长的一段纯文字描述，"
        "这段文字会填满八十个字符的窗口让链接无法出现在窗口内，从而该数字应被判定为未引用。\n"
        "先进工艺占比 77% [来源](https://c.com)。"
    )
    r = number_citation_rate(md)
    # 182亿 与 77% 紧邻来源（cited）；58% 与 54% 的 80 字符窗口内无链接（not cited）
    assert r == 0.5
    assert number_citation_rate("") == 0.0


def test_harness_fact_check_and_success_definition():
    """GPT 审查 §4.5：成功定义必须验证黄金事实，且检测过程性泄露。"""
    from agent.harness import _check_task_facts, _has_process_leakage

    task = {
        "facts": ["2026年7月合并营收约4,675.8亿新台币", "同比约+44.7%"],
        "checkpoints": ["报告给出台积电最近月度营收的精确金额"],
    }
    good_report = "台积电7月营收 4,675.8 亿新台币，同比 +44.7% [来源](https://a.com)"
    fh, ft, ch, ct = _check_task_facts(good_report, task)
    assert fh == 2 and ft == 2  # 两个黄金事实都命中
    assert ch >= 1  # checkpoint 关键词命中

    bad_report = "本周行业整体平稳，无具体数据。"
    fh2, ft2, _, _ = _check_task_facts(bad_report, task)
    assert fh2 == 0  # 黄金事实全未命中

    assert _has_process_leakage("Based on my extensive research and verification...")
    assert not _has_process_leakage("# 周报\n\n正文内容[来源](https://a.com)")


def test_url_grounding_detects_fabricated_urls():
    """差距收敛第 1 项：报告 URL 必须来自检索结果，编造 URL 被确定性检出。"""
    from agent.evidence import check_url_grounding, extract_urls_with_context

    tool_outputs = [
        "台积电7月营收 4,675.8 亿新台币 (来源: https://www.sec.gov/archives/tsm.htm)",
        '{"news": [{"title": "存储涨价", "url": "https://www.ithome.com/0/989/912.htm"}]}',
    ]
    urls = extract_urls_with_context(tool_outputs[0])
    assert urls[0]["url"] == "https://www.sec.gov/archives/tsm.htm"
    assert urls[0]["snippet"]  # 上下文片段非空

    grounded_report = (
        "营收 4,675.8 亿[来源](https://www.sec.gov/archives/tsm.htm)，"
        "存储涨价[来源](https://www.ithome.com/0/989/912.htm)"
    )
    r = check_url_grounding(grounded_report, tool_outputs)
    assert r["rate"] == 1.0 and r["ungrounded"] == []

    # 编造 URL：不在任何工具返回中
    fake_report = "编造来源[来源](https://evil.example.com/fake)"
    r2 = check_url_grounding(fake_report, tool_outputs)
    assert r2["rate"] == 0.0
    assert "https://evil.example.com/fake" in r2["ungrounded"]

    # 空报告视为全落地（无 URL 可查）
    assert check_url_grounding("无链接正文", tool_outputs)["rate"] == 1.0


def test_source_level_classification():
    """差距收敛第 3 项：来源分级（官方/学术/媒体/聚合）与报告占比统计。"""
    from agent.evidence import report_source_levels, source_level

    assert source_level("https://www.sec.gov/archives/x.htm") == 0  # 官方
    assert source_level("https://pr.tsmc.com/english/news/3329") == 0  # 官方（子域尾缀）
    assert source_level("https://arxiv.org/abs/2608.1") == 1  # 学术
    assert source_level("https://pubmed.ncbi.nlm.nih.gov/36576964/") == 1
    assert source_level("https://www.ithome.com/0/989/912.htm") == 2  # 媒体
    assert source_level("https://wallstreetcn.com/articles/3774694") == 2
    assert source_level("https://news.google.com/rss/articles/x") == 3  # 聚合
    assert source_level("https://evil.example.com/fake") == 3  # 未知

    md = (
        "官方数据[来源](https://www.sec.gov/x) 与学术[来源](https://arxiv.org/a)"
        "及媒体[来源](https://www.ithome.com/x)和聚合[来源](https://news.google.com/x)"
    )
    s = report_source_levels(md)
    assert s["total"] == 4
    assert s["counts"] == {0: 1, 1: 1, 2: 1, 3: 1}
    assert s["official_ratio"] == 0.5  # 官方+学术 / 总数


def test_claim_support_rate():
    """差距收敛第 5 项：数字论断须在检索证据中出现（claim→source→span）。"""
    from agent.evidence import build_evidence_index, claim_support_rate, extract_numeric_claims

    tool_outputs = [
        "台积电7月营收 4,675.8 亿新台币 同比 +44.7% (来源: https://www.sec.gov/tsm.htm)",
        "存储芯片价格涨幅超 200% (来源: https://www.ithome.com/x)",
    ]
    # 报告含 3 个带单位数字：4,675.8 亿 与 44.7% 绑定 sec.gov（span 含数字，支持）；
    # 99.9% 绑定 ithome.com/y（证据池无该 URL 的该数字 span → 不支持）
    report = (
        "台积电 7 月营收 4,675.8 亿新台币[来源](https://www.sec.gov/tsm.htm)，"
        "同比 +44.7%[来源](https://www.sec.gov/tsm.htm)。\n"
        "另有传闻占比 99.9%[来源](https://www.ithome.com/y)。"
    )
    claims = extract_numeric_claims(report)
    assert len(claims) == 2  # 第一句含两个数字算同一论断，第二句一条
    # 年份/编号不计入
    assert extract_numeric_claims("2026 年 3 家公司披露 0001046179 文件") == []

    r = claim_support_rate(report, tool_outputs)
    assert r["total"] == 3  # 数字级判定：4,675.8 亿、44.7%、99.9%
    assert r["supported"] == 2
    assert r["rate"] == round(2 / 3, 3)
    assert any("99.9%" in c for c in r["unsupported"])

    idx = build_evidence_index(tool_outputs)
    assert "4,675.8 亿" in idx  # 数字倒排索引命中（键带单位）
    assert idx["4,675.8 亿"][0]["url"] == "https://www.sec.gov/tsm.htm"


def test_claim_support_cross_mismatch_blocked():
    """复审 §6.1/6.2：交叉错配必须被拦截——报告数字绑定 A 但 A 的 span 无此数。"""
    from agent.evidence import claim_support_rate

    # 证据池：A 的 span 含 100 亿，B 的 span 含 999 亿
    tool_outputs = [
        "苹果出货 100 亿 (来源: https://a.com)",
        "谷歌采购 999 亿 (来源: https://b.com)",
    ]
    # 报告把 100 亿 链接到 B、999 亿 链接到 A——反向错配
    report = (
        "苹果出货 100 亿[来源](https://b.com)，"
        "谷歌采购 999 亿[来源](https://a.com)。"
    )
    r = claim_support_rate(report, tool_outputs)
    # 旧 any-match 实现：数字都在证据池 → rate=1.0（漏洞）；
    # 精确绑定：100 亿→b.com 的 span 无"100 亿"，999 亿→a.com 的 span 无"999 亿" → 全拦
    assert r["rate"] == 0.0
    assert r["supported"] == 0


def test_claim_support_requires_adjacent_url():
    """数字无紧邻 URL → 不支持（空证据不再默认满分，复审 §6.4）。"""
    from agent.evidence import claim_support_rate

    report = "毛利率 54% 数字后没有任何链接，只有纯文字说明。"
    r = claim_support_rate(report, ["某证据 54% (来源: https://x.com)"])
    assert r["total"] == 1
    assert r["rate"] == 0.0  # 无紧邻 URL → 不支持
    assert "无紧邻 URL" in r["unsupported"][0]


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
    # GPT 审查 §4.21：测试输出必须走 tmp_path，禁止污染正式报告产物目录
    result = pipe.generate("台积电基本面", report_type="basic_research", output_dir=tmp_path / "reports")

    # 分节独立 run：researcher 被调 N 次（basic_research 模板=6 节）+ 反思循环 1 次
    first_task = calls["tasks"][0]
    assert "第 1/6 节" in first_task
    assert "撰写规划" in first_task
    assert "禁止出现无来源的精确数字" in first_task
    assert any("第 2/6 节" in t for t in calls["tasks"])
    # 反思循环（差距收敛第 4 项）：初稿后有一次证据自检 + 定向补检索
    assert any("严格质检员的视角反思" in t for t in calls["tasks"])
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
