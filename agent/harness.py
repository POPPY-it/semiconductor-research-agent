"""Agent 级评测 Harness（P1-1）：跑任务集，统计企业听得懂的 4 个指标。

指标：
1. 任务成功率：质检通过，或 caveat 但无「无来源数字」
2. 无引用数字率：正文里金额/百分比有多少没带链接
3. 平均工具步数 / 失败重试次数
4. 单任务成本：字符（估算 token）与墙钟时间

输出：eval/results_latest.json + eval/metrics.md（提交进 git）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TASKS_PATH = ROOT / "eval" / "tasks.json"
METRICS_PATH = ROOT / "eval" / "metrics.md"
RESULTS_PATH = ROOT / "eval" / "results_latest.json"


def load_tasks(path: str | Path = TASKS_PATH) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def evaluate_one(pipeline, task: dict) -> dict:
    """跑一条任务并基于轨迹计算指标；失败返回 error 记录。"""
    try:
        result = pipeline.generate(task["topic"], report_type=task.get("report_type", "weekly"))
    except Exception as e:  # noqa: BLE001 —— 单条失败不阻塞整体
        return {"id": task["id"], "status": "error", "error": str(e)[:200]}

    trace = json.loads(Path(result["trace_path"]).read_text(encoding="utf-8"))
    meta = trace.get("meta", {})
    steps = trace.get("steps", [])

    # CodeAgent 的工具调用记录为 python_interpreter，真实工具名出现在代码里
    # （model_output 或 python_interpreter 的 arguments，两处都扫）
    tools_used = {t["name"] for s in steps for t in s.get("tools", [])}
    for s in steps:
        for src in (s.get("model_output", ""),):
            if isinstance(src, str):
                for t in task.get("required_tools", []):
                    if re.search(rf"\b{re.escape(t)}\s*\(", src):
                        tools_used.add(t)
        for tc in s.get("tools", []):
            if tc.get("name") == "python_interpreter":
                args = tc.get("arguments", "")
                for t in task.get("required_tools", []):
                    if re.search(rf"\b{re.escape(t)}\s*\(", args):
                        tools_used.add(t)
    required_missing = sorted(set(task.get("required_tools", [])) - tools_used)
    numbers = meta.get("numbers", {})
    uncited_rate = numbers.get("uncited_rate", 1.0)
    citation_density = meta.get("citation_density", 0.0)
    verdict_passed = bool((meta.get("verdict") or {}).get("passed"))
    # 成功率口径：质检通过，或 caveat 但无「无来源数字」
    success = verdict_passed or uncited_rate == 0.0

    return {
        "id": task["id"],
        "status": "done",
        "success": success,
        "verdict_passed": verdict_passed,
        "uncited_rate": uncited_rate,
        "citation_density": citation_density,
        "numbers_total": numbers.get("total_numbers", 0),
        "numbers_without_url": numbers.get("numbers_without_url", 0),
        "steps": len(steps),
        "tool_calls": sum(len(s.get("tools", [])) for s in steps),
        "errors": sum(1 for s in steps if s.get("error")),
        "budget_chars": meta.get("budget_used_chars", 0),
        "duration_s": round(meta.get("duration_s", 0), 1),
        "revision_rounds": meta.get("revision_rounds"),
        "required_tools_missing": required_missing,
    }


def summarize(results: list[dict]) -> dict:
    done = [r for r in results if r["status"] == "done"]
    n = len(done)
    if not n:
        return {"n": 0}
    return {
        "n": len(results),
        "n_done": n,
        "n_error": sum(1 for r in results if r["status"] == "error"),
        "success_rate": round(sum(1 for r in done if r["success"]) / n, 3),
        "avg_uncited_rate": round(sum(r["uncited_rate"] for r in done) / n, 3),
        "avg_citation_density": round(sum(r["citation_density"] for r in done) / n, 3),
        "avg_steps": round(sum(r["steps"] for r in done) / n, 1),
        "avg_tool_calls": round(sum(r["tool_calls"] for r in done) / n, 1),
        "avg_errors": round(sum(r["errors"] for r in done) / n, 2),
        "avg_duration_s": round(sum(r["duration_s"] for r in done) / n, 1),
        "avg_budget_chars": int(sum(r["budget_chars"] for r in done) / n),
        "required_tools_missing_all": [
            r["id"] for r in done if r["required_tools_missing"]
        ],
    }


def write_outputs(results: list[dict], summary: dict) -> None:
    RESULTS_PATH.write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# Agent 评测指标（Harness）",
        "",
        "> 最近一次运行：见 `results_latest.json`（提交进 git）。",
        "",
        "## 汇总",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| 任务数（成功/错误） | {summary['n_done']}/{summary['n_error']} |",
        f"| **任务成功率** | {summary.get('success_rate', 0)} |",
        f"| **无引用数字率（均值）** | {summary.get('avg_uncited_rate', 0)} |",
        f"| **段落引用密度（均值）** | {summary.get('avg_citation_density', 0)} |",
        f"| **平均步骤数** | {summary.get('avg_steps', 0)} |",
        f"| 平均工具调用 | {summary.get('avg_tool_calls', 0)} |",
        f"| 平均错误数 | {summary.get('avg_errors', 0)} |",
        f"| 平均耗时（s） | {summary.get('avg_duration_s', 0)} |",
        f"| 平均预算字符 | {summary.get('avg_budget_chars', 0)} |",
        "",
        "## 逐任务",
        "",
        "| id | 状态 | 成功 | 无引用率 | 引用密度 | 步数 | 工具调用 | 错误 | 耗时s | 缺工具 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        if r["status"] == "done":
            lines.append(
                f"| {r['id']} | done | {r['success']} | {r['uncited_rate']} | {r['citation_density']} | "
                f"{r['steps']} | {r['tool_calls']} | {r['errors']} | {r['duration_s']} | "
                f"{','.join(r['required_tools_missing']) or '-'} |"
            )
        else:
            lines.append(f"| {r['id']} | error | - | - | - | - | - | - | - | {r.get('error', '')[:40]} |")
    METRICS_PATH.write_text("\n".join(lines), encoding="utf-8")


def run_harness(pipeline, tasks: list[dict], limit: int | None = None) -> dict:
    results = []
    for task in tasks[:limit]:
        print(f"[harness] 运行 {task['id']}: {task['topic'][:40]}...", flush=True)
        r = evaluate_one(pipeline, task)
        results.append(r)
        print(f"  -> {json.dumps(r, ensure_ascii=False)[:200]}", flush=True)
    summary = summarize(results)
    write_outputs(results, summary)
    print("\n=== 汇总 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary
