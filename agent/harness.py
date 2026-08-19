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


def evaluate_one(pipeline, task: dict, output_dir: str | Path | None = None) -> dict:
    """跑一条任务并基于轨迹计算指标；失败返回 error 记录。

    output_dir：报告输出目录（评测默认用隔离临时目录，避免污染正式报告产物）。
    """
    try:
        result = pipeline.generate(
            task["topic"],
            report_type=task.get("report_type", "weekly"),
            output_dir=output_dir,
        )
    except Exception as e:  # noqa: BLE001 —— 单条失败不阻塞整体
        return {"id": task["id"], "status": "error", "error": str(e)[:200]}

    trace = json.loads(Path(result["trace_path"]).read_text(encoding="utf-8"))
    meta = trace.get("meta", {})
    steps = trace.get("steps", [])
    report_text = result.get("report", "") or ""

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
    number_citation_rate = meta.get("number_citation_rate", 0.0)
    url_grounding_rate = (meta.get("url_grounding") or {}).get("rate", 1.0)
    verdict_passed = bool((meta.get("verdict") or {}).get("passed"))
    # 黄金事实核对（GPT 审查 §4.5 整改）：facts/checkpoints 是否在报告正文命中
    fact_hit, fact_total, ck_hit, ck_total = _check_task_facts(report_text, task)
    fact_hit_rate = round(fact_hit / fact_total, 3) if fact_total else 1.0
    ck_hit_rate = round(ck_hit / ck_total, 3) if ck_total else 1.0
    leakage = _has_process_leakage(report_text)
    # 成功率口径（整改后）：质检通过 且 黄金事实命中率≥0.5 且 无过程性泄露
    # 且 URL 落地率≥0.8（证据包：报告 URL 必须来自检索结果，差距收敛第 1 项）
    success = (
        verdict_passed
        and fact_hit_rate >= 0.5
        and not leakage
        and url_grounding_rate >= 0.8
    )

    return {
        "id": task["id"],
        "status": "done",
        "success": success,
        "verdict_passed": verdict_passed,
        "fact_hit_rate": fact_hit_rate,
        "checkpoint_hit_rate": ck_hit_rate,
        "leakage": leakage,
        "uncited_rate": uncited_rate,
        "citation_density": citation_density,
        "number_citation_rate": number_citation_rate,
        "url_grounding_rate": url_grounding_rate,
        "numbers_total": numbers.get("total_numbers", 0),
        "numbers_without_url": numbers.get("numbers_without_url", 0),
        "steps": len(steps),
        "tool_calls": sum(len(s.get("tools", [])) for s in steps),
        "errors": sum(1 for s in steps if s.get("error")),
        "budget_chars": meta.get("budget_used_chars", 0),
        "duration_s": round(meta.get("duration_s", 0), 1),
        "revision_rounds": meta.get("revision_rounds"),
        "required_tools_missing": required_missing,
        "report_path": meta.get("report_path", ""),
    }


def _check_task_facts(report_text: str, task: dict) -> tuple[int, int, int, int]:
    """黄金事实/检查点核对（宽松口径，GPT 审查 §4.5）。

    - fact 命中：fact 中任一数字（去逗号后）出现在报告，或去掉数字/单位后的关键词
      短语（≥3 字）出现在报告；
    - checkpoint 命中：checkpoint 中任一信息性中文词（≥2 字）出现在报告
      （checkpoint 是"要点描述"，无法精确匹配，取宽松命中作参考指标）。
    """
    facts = task.get("facts", [])
    fact_hit = sum(1 for f in facts if _fact_hit(report_text, f))
    cks = task.get("checkpoints", [])
    ck_hit = sum(1 for c in cks if _ck_hit(report_text, c))
    return fact_hit, len(facts), ck_hit, len(cks)


def _fact_hit(report: str, fact: str) -> bool:
    nums = re.findall(r"\d[\d,\.]*", fact)
    num_hit = any(n.replace(",", "") in report.replace(",", "") for n in nums) if nums else True
    kw = re.sub(r"[\d,\.\s%％亿万美元新台币欧元元约]", "", fact)
    kw_hit = len(kw) >= 3 and kw in report
    return num_hit or kw_hit


_CK_STOP = ("报告", "给出", "引用", "来源", "应该", "不得", "明确", "具体",
            "精确", "金额", "最近", "最新", "要求", "说明", "格式", "规范", "避免", "出现")


def _ck_hit(report: str, ck: str) -> bool:
    """checkpoint 命中：checkpoint 中的数字出现在报告，或任意 2-gram 关键词命中。

    checkpoint 是"要点描述"（如"报告给出台积电最近月度营收的精确金额"），
    不能整串匹配——切成 2-gram 并过滤停用词（"台积电"→"台积"/"积电"）。
    """
    nums = re.findall(r"\d[\d,\.]*", ck)
    if nums and any(n.replace(",", "") in report.replace(",", "") for n in nums):
        return True
    grams = set()
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", ck):
        for i in range(len(chunk) - 1):
            g = chunk[i : i + 2]
            if g not in _CK_STOP:
                grams.add(g)
    return any(g in report for g in grams) if grams else True


_PROCESS_LEAK_KEYWORDS = ("based on my", "以下是修订", "验证清单", "过程性", "let me compile")


def _has_process_leakage(report_text: str) -> bool:
    """过程性文本泄露检测（GPT 审查 §4.5：输出不应混入模型思考/验证清单）。"""
    head = (report_text or "")[:600].lower()
    return any(k in head for k in _PROCESS_LEAK_KEYWORDS)


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
        "avg_fact_hit_rate": round(sum(r["fact_hit_rate"] for r in done) / n, 3),
        "avg_checkpoint_hit_rate": round(sum(r["checkpoint_hit_rate"] for r in done) / n, 3),
        "leakage_count": sum(1 for r in done if r["leakage"]),
        "avg_uncited_rate": round(sum(r["uncited_rate"] for r in done) / n, 3),
        "avg_citation_density": round(sum(r["citation_density"] for r in done) / n, 3),
        "avg_number_citation_rate": round(sum(r["number_citation_rate"] for r in done) / n, 3),
        "avg_url_grounding_rate": round(sum(r["url_grounding_rate"] for r in done) / n, 3),
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
        f"| **任务成功率** | {summary.get('success_rate', 0)}（质检通过+黄金事实命中率≥0.5+无泄露） |",
        f"| **黄金事实命中率（均值）** | {summary.get('avg_fact_hit_rate', 0)} |",
        f"| **检查点命中率（均值）** | {summary.get('avg_checkpoint_hit_rate', 0)} |",
        f"| 过程性泄露任务数 | {summary.get('leakage_count', 0)} |",
        f"| **无引用数字率（均值）** | {summary.get('avg_uncited_rate', 0)} |",
        f"| **段落引用密度（均值）** | {summary.get('avg_citation_density', 0)} |",
        f"| **数字级引用率（均值）** | {summary.get('avg_number_citation_rate', 0)} |",
        f"| **URL 落地率（均值）** | {summary.get('avg_url_grounding_rate', 0)} |",
        f"| **平均步骤数** | {summary.get('avg_steps', 0)} |",
        f"| 平均工具调用 | {summary.get('avg_tool_calls', 0)} |",
        f"| 平均错误数 | {summary.get('avg_errors', 0)} |",
        f"| 平均耗时（s） | {summary.get('avg_duration_s', 0)} |",
        f"| 平均预算字符 | {summary.get('avg_budget_chars', 0)} |",
        "",
        "## 逐任务",
        "",
        "| id | 状态 | 成功 | 事实命中 | 检查点 | 泄露 | 无引用率 | 引用密度 | 数字引用率 | URL落地 | 步数 | 工具调用 | 错误 | 耗时s | 缺工具 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        if r["status"] == "done":
            lines.append(
                f"| {r['id']} | done | {r['success']} | {r['fact_hit_rate']} | {r['checkpoint_hit_rate']} "
                f"| {r['leakage']} | {r['uncited_rate']} | {r['citation_density']} | {r['number_citation_rate']} "
                f"| {r['url_grounding_rate']} | {r['steps']} | {r['tool_calls']} | {r['errors']} | {r['duration_s']} "
                f"| {','.join(r['required_tools_missing']) or '-'} |"
            )
        else:
            lines.append(
                f"| {r['id']} | error | - | - | - | - | - | - | - | - | - | - | - | - | {r.get('error', '')[:40]} |"
            )
    METRICS_PATH.write_text("\n".join(lines), encoding="utf-8")


def run_harness(pipeline, tasks: list[dict], limit: int | None = None) -> dict:
    """跑任务集；报告输出到隔离临时目录（可重复运行，不污染正式报告产物）。"""
    import tempfile

    results = []
    with tempfile.TemporaryDirectory(prefix="harness_reports_") as tmp:
        for task in tasks[:limit]:
            print(f"[harness] 运行 {task['id']}: {task['topic'][:40]}...", flush=True)
            r = evaluate_one(pipeline, task, output_dir=tmp)
            results.append(r)
            print(f"  -> {json.dumps(r, ensure_ascii=False)[:200]}", flush=True)
    summary = summarize(results)
    write_outputs(results, summary)
    print("\n=== 汇总 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary
