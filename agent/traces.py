"""轨迹落盘（P0-2）：每次 generate / answer_question 写一份 JSONL 轨迹。

用途：① 回放一次失败（企业要的"败了怎么收"）；② Agent 级评测的数据源
（成功率 / 无引用数字率 / 平均步数 / 成本）。
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path

_NUMBER_RE = re.compile(
    r"\d[\d,]*(?:\.\d+)?\s*(?:%|％|亿|万|千|百万|欧元|美元|新台币|亿元|亿欧元|亿美元|亿元人民币)?"
)


def new_run_id() -> str:
    return uuid.uuid4().hex[:10]


def serialize_step(step) -> dict:
    """把 smolagents 的 MemoryStep 序列化为紧凑轨迹条目（缺字段则跳过）。"""
    d: dict = {"kind": type(step).__name__}
    if hasattr(step, "step_number"):
        d["step_number"] = getattr(step, "step_number")
    tools = []
    for tc in getattr(step, "tool_calls", None) or []:
        tools.append(
            {
                "name": getattr(tc, "name", ""),
                "arguments": str(getattr(tc, "arguments", ""))[:200],
            }
        )
    if tools:
        d["tools"] = tools
    mo = getattr(step, "model_output", None)
    if mo is not None:
        content = getattr(mo, "content", None)
        if isinstance(content, str):
            d["model_output"] = content[:500]
    ao = getattr(step, "action_output", None)
    if ao is not None:
        d["action_output"] = str(ao)[:300]
    # CodeAgent 执行代码后，工具返回值存在 observations（action_output 常为 None）
    obs = getattr(step, "observations", None)
    if obs is not None and ao is None:
        d["action_output"] = str(obs)[:300]
    err = getattr(step, "error", None)
    if err is not None:
        d["error"] = str(err)[:300]
    timing = getattr(step, "timing", None)
    if timing is not None:
        st = getattr(timing, "start_time", None)
        en = getattr(timing, "end_time", None)
        if st and en:
            d["duration_s"] = round(max(0.0, en - st), 2)
    tu = getattr(step, "token_usage", None)
    if tu is not None:
        d["tokens"] = {
            "in": getattr(tu, "input_tokens", None),
            "out": getattr(tu, "output_tokens", None),
        }
    return d


def collect_agent_steps(agent) -> list[dict]:
    """读取 agent.memory.steps 序列化；无 memory 的对象返回空。

    CodeAgent 的 ToolCall 记录为 python_interpreter，真实工具调用出现在
    代码里——但代码**不一定在 model_output**（实测 model_output 常为空，
    完整代码在 python_interpreter 的 arguments 里）。这里把两处都扫一遍
    `name(` 模式，把实际调用的工具补进 step.tools，保证轨迹里工具可见。
    """
    memory = getattr(agent, "memory", None)
    if memory is None:
        return []
    tool_names = list(getattr(agent, "tools", {}) or {}.keys())
    steps = []
    for s in getattr(memory, "steps", None) or []:
        d = serialize_step(s)
        code_parts: list[str] = []
        mo = d.get("model_output")
        if isinstance(mo, str) and mo:
            code_parts.append(mo)
        for tc in getattr(s, "tool_calls", None) or []:
            if getattr(tc, "name", "") == "python_interpreter":
                code_parts.append(str(getattr(tc, "arguments", "")))
        code_src = "\n".join(code_parts)
        if code_src and tool_names:
            detected = [
                {"name": n, "arguments": ""}
                for n in tool_names
                if re.search(rf"\b{re.escape(n)}\s*\(", code_src)
            ]
            if detected:
                existing = {t.get("name") for t in d.get("tools", [])}
                d["tools"] = d.get("tools", []) + [
                    x for x in detected if x["name"] not in existing
                ]
        steps.append(d)
    return steps


def analyze_numbers(md: str) -> dict:
    """统计报告正文中的数字及其是否在**之后 120 字符内**带链接（无引用数字率）。

    引用惯例：论断后跟链接（[来源](url) 或 (https://...)），因此只看数字后方窗口。
    """
    total = 0
    without_url = 0
    examples: list[str] = []
    for m in _NUMBER_RE.finditer(md or ""):
        total += 1
        window = md[m.end() : m.end() + 120]
        if "http" not in window.lower():
            without_url += 1
            if len(examples) < 8:
                examples.append(m.group(0).strip())
    return {
        "total_numbers": total,
        "numbers_without_url": without_url,
        "uncited_rate": round(without_url / total, 3) if total else 0.0,
        "examples": examples,
    }


def save_trace(
    trace_dir: str | Path,
    run_id: str,
    kind: str,
    topic: str,
    steps: list[dict],
    meta: dict,
) -> Path:
    """写一份单行 JSON（JSONL 格式）轨迹文件，返回路径。"""
    trace_dir = Path(trace_dir)
    trace_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "run_id": run_id,
        "kind": kind,
        "topic": topic,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "steps": steps,
        "meta": meta,
    }
    path = trace_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{run_id}.jsonl"
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return path
