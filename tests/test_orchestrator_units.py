"""编排器辅助函数单元测试（不触发 LLM 调用）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.orchestrator import REPORT_TEMPLATES, _extract_json  # noqa: E402


def test_extract_json_from_dict():
    assert _extract_json({"passed": True, "issues": []}) == {"passed": True, "issues": []}


def test_extract_json_from_wrapped_string():
    text = '校验完成，结论如下：\n{"passed": false, "issues": ["数字无来源"]}\n以上。'
    assert _extract_json(text) == {"passed": False, "issues": ["数字无来源"]}


def test_extract_json_invalid():
    assert _extract_json("无法解析的输出") is None
    assert _extract_json(None) is None


def test_report_templates_cover_types():
    """全部 6 种报告类型都有分节与字数约束（§4.5：survey/medical_survey 此前未测）。"""
    for t in ("daily", "weekly", "deep", "survey", "medical_survey", "basic_research"):
        assert "sections" in REPORT_TEMPLATES[t]
        assert REPORT_TEMPLATES[t]["min_words"] > 0


def test_medical_and_investment_templates_have_compliance():
    """医学综述与研投基本面分析必须带合规约束（safety 写入 researcher 指令 + 免责声明）。"""
    med = REPORT_TEMPLATES["medical_survey"]
    assert "safety" in med and "disclaimer" in med
    assert "诊疗" in med["disclaimer"]

    inv = REPORT_TEMPLATES["basic_research"]
    assert "safety" in inv and "disclaimer" in inv
    # 合规边界：不得输出投资建议 / 目标价 / 估值结论
    assert "投资建议" in inv["safety"] or "买入" in inv["safety"]
    assert "不构成任何投资建议" in inv["disclaimer"]
    # 财务数字必须来自 SEC
    assert "SEC" in inv["safety"]
