"""报告任务服务：把编排器接进会话/事件/存储（在任务队列的 worker 线程中运行）。"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from .db import SessionStore, STATUS_DONE, STATUS_ERROR, STATUS_RUNNING
from .events import EventBus

logger = logging.getLogger(__name__)


@dataclass
class ReportResult:
    report_path: str
    verdict: dict
    revision_rounds: int
    report_md: str


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

    def _get_pipeline(self):
        if self._pipeline is None:
            self._pipeline = self._pipeline_factory()
        return self._pipeline

    def run(self, session_id: int, topic: str, report_type: str) -> None:
        """worker 入口：跑编排器并发布阶段事件（done/error 必发其一）。"""
        try:
            self.store.set_status(session_id, STATUS_RUNNING)
            self.bus.publish(session_id, {"type": "phase", "data": {"phase": "index", "msg": "构建知识库索引..."}})
            pipeline = self._get_pipeline()
            self.bus.publish(session_id, {"type": "phase", "data": {"phase": "research", "msg": "研究 Agent 撰写中..."}})
            result = pipeline.generate(topic, report_type=report_type)
            self.bus.publish(
                session_id,
                {
                    "type": "phase",
                    "data": {
                        "phase": "qa_done",
                        "msg": f"质检完成：passed={result['verdict'].get('passed')}，修订 {result['revision_rounds']} 轮",
                    },
                },
            )
            self.store.save_report(
                session_id,
                result["verdict"],
                result["revision_rounds"],
                result["report_path"],
                result["report"],
            )
            self.store.set_status(session_id, STATUS_DONE)
            self.bus.publish(
                session_id,
                {"type": "done", "data": {"report_path": result["report_path"]}},
            )
        except Exception as e:  # noqa: BLE001 —— worker 内兜底，保证错误事件必发
            logger.exception("session %s 失败", session_id)
            self.store.set_status(session_id, STATUS_ERROR)
            self.bus.publish(session_id, {"type": "error", "data": {"message": str(e)[:500]}})
