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
    for t in ("daily", "weekly", "deep"):
        assert "sections" in REPORT_TEMPLATES[t]
        assert REPORT_TEMPLATES[t]["min_words"] > 0
