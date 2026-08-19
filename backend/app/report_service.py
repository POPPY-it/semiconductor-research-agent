"""报告任务服务：把编排器接进会话/事件/存储（在任务队列的 worker 线程中运行）。

W8 加固：质检交付策略（caveat/reject）、任务指标埋点、索引互斥（生成期间禁止重建）。
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .core import settings
from .db import SessionStore, STATUS_DONE, STATUS_ERROR, STATUS_RUNNING
from .events import EventBus
from .middleware import metrics

logger = logging.getLogger(__name__)


@dataclass
class ReportResult:
    report_path: str
    verdict: dict
    revision_rounds: int
    report_md: str


def _apply_qa_policy(result: dict) -> str:
    """质检交付策略：
    - 通过：原样交付
    - caveat（默认）：未通过在正文顶部注入警示横幅后交付
    - reject：未通过则拒绝交付正文（保存空串，verdict 保留）

    GPT 审查 §4.3 整改：叠加**确定性数字引用门禁**（MIN_NUMBER_CITATION_RATE）——
    与 LLM 质检独立、不依赖提示词约束；门禁不通过时同样按 reject/caveat 策略处理。
    """
    verdict = result.get("verdict") or {"passed": False, "issues": []}
    md = result.get("report", "")
    gate = result.get("deterministic_gate") or {"ok": True, "rate": 1.0}
    issues = list(verdict.get("issues", []) or [])
    if not gate["ok"]:
        issues.append(
            f"确定性门禁未通过：数字级引用率 {gate['rate']:.0%}（阈值 "
            f"{settings.MIN_NUMBER_CITATION_RATE:.0%}），URL 落地率 "
            f"{gate.get('url_grounding_rate', 1.0):.0%}（阈值 {settings.MIN_URL_GROUNDING_RATE:.0%}）"
            + (
                f"，疑似编造 URL：{', '.join(gate.get('ungrounded_urls', [])[:2])}"
                if gate.get("ungrounded_urls")
                else ""
            )
        )
    passed = bool(verdict.get("passed")) and gate["ok"]
    if passed:
        return md
    if settings.QA_POLICY == "reject":
        return ""
    banner = (
        "> ⚠️ **质检未通过**：以下内容包含未能通过事实校验的表述，请谨慎引用：\n>\n"
        + "\n".join(f"> - {i}" for i in issues[:8])
        + "\n\n"
    )
    return banner + md


class ReportService:
    """pipeline_factory 返回 ReportPipeline（延迟构建：知识库索引耗时，全局复用一次）。"""

    def __init__(
        self,
        store: SessionStore,
        bus: EventBus,
        pipeline_factory: Callable,
    ):
        self.store = store
        self.bus = bus
        self._pipeline_factory = pipeline_factory
        self._pipeline = None
        self._lock = threading.RLock()  # 索引互斥：生成/问答期间禁止重建

    def _ensure_pipeline_locked(self):
        if self._pipeline is None:
            self._pipeline = self._pipeline_factory()
        return self._pipeline

    def run(self, session_id: int, topic: str, report_type: str) -> None:
        """worker 入口：跑编排器并发布阶段事件（done/error 必发其一）。"""
        t0 = time.time()
        try:
            self.store.set_status(session_id, STATUS_RUNNING)
            self.bus.publish(session_id, {"type": "phase", "data": {"phase": "index", "msg": "构建知识库索引..."}})
            with self._lock:
                pipeline = self._ensure_pipeline_locked()
                self.bus.publish(session_id, {"type": "phase", "data": {"phase": "research", "msg": "研究 Agent 撰写中..."}})
                result = pipeline.generate(topic, report_type=report_type)
            verdict = result.get("verdict") or {"passed": False, "issues": []}
            # 确定性双门禁（与 LLM 质检独立）：
            # 1) 数字引用率（GPT 审查 §4.3）；2) URL 落地率——报告 URL 必须来自检索结果
            from agent.traces import number_citation_rate

            gate_rate = number_citation_rate(result.get("report", ""))
            grounding = result.get("url_grounding") or {"rate": 1.0, "ungrounded": []}
            gate_ok = (
                gate_rate >= settings.MIN_NUMBER_CITATION_RATE
                and grounding.get("rate", 1.0) >= settings.MIN_URL_GROUNDING_RATE
            )
            result["deterministic_gate"] = {
                "ok": gate_ok,
                "rate": gate_rate,
                "url_grounding_rate": grounding.get("rate", 1.0),
                "ungrounded_urls": grounding.get("ungrounded", []),
            }
            self.bus.publish(
                session_id,
                {
                    "type": "phase",
                    "data": {
                        "phase": "qa_done",
                        "msg": (
                            f"质检完成：passed={verdict.get('passed')}，"
                            f"确定性门禁={'通过' if gate_ok else '未通过'}"
                            f"（数字引用率 {gate_rate:.0%}，"
                            f"URL落地率 {grounding.get('rate', 1.0):.0%}），"
                            f"修订 {result.get('revision_rounds', 0)} 轮，"
                            f"模型={result.get('model_used', 'primary')}，"
                            f"预算用量={result.get('budget_used_chars', 0)} 字符"
                        ),
                    },
                },
            )
            report_md = _apply_qa_policy(result)
            self.store.save_report(
                session_id,
                verdict,
                result.get("revision_rounds", 0),
                result.get("report_path", ""),
                report_md,
            )
            self.store.set_status(session_id, STATUS_DONE)
            self.bus.publish(
                session_id,
                {"type": "done", "data": {"report_path": result.get("report_path", "")}},
            )
            metrics.inc("report_tasks_total", ("done",))
            metrics.inc("report_task_duration_ms_sum", ("",), int((time.time() - t0) * 1000))
            metrics.inc("report_task_count", ())
        except Exception as e:  # noqa: BLE001 —— worker 内兜底，保证错误事件必发
            logger.exception("session %s 失败", session_id)
            self.store.set_status(session_id, STATUS_ERROR)
            self.bus.publish(session_id, {"type": "error", "data": {"message": str(e)[:500]}})
            metrics.inc("report_tasks_total", ("error",))

    def qa(self, question: str, history: list[dict] | None = None) -> dict:
        """同步问答（轻量任务，直接跑在请求线程；预算独立熔断；支持多轮上下文）。"""
        t0 = time.time()
        with self._lock:
            pipeline = self._ensure_pipeline_locked()
            result = pipeline.answer_question(question, history=history)
        metrics.inc("qa_requests_total")
        metrics.inc("qa_duration_ms_sum", ("",), int((time.time() - t0) * 1000))
        metrics.inc("qa_count", ())
        return result

    def reindex(self) -> None:
        """重建知识库索引（文档上传后调用；与生成/问答任务互斥）。"""
        with self._lock:
            pipeline = self._ensure_pipeline_locked()
            pipeline.rebuild()
