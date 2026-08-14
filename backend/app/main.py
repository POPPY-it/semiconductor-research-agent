"""服务层 API（M5）：会话 + 任务队列 + SSE 事件流 + 鉴权。

架构：app 工厂（可注入测试依赖）→ ReportService 在任务队列 worker 中运行编排器
→ EventBus 把阶段事件推给 SSE 订阅者。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

from fastapi import Body, Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from .core import settings
from .db import SessionStore
from .events import EventBus
from .report_service import ReportService
from .tasks import TaskQueue, ThreadPoolQueue

logger = logging.getLogger(__name__)


def default_pipeline_factory():
    """生产接线：知识库（含模型）懒加载，全局复用。"""
    import sys

    ROOT = Path(__file__).resolve().parents[2]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from agent.knowledge.loader import build_retriever
    from agent.orchestrator import ReportPipeline
    from data.storage import SQLiteStore

    retriever = build_retriever(
        settings.ARTICLES_DB, settings.VECTOR_DIR, settings.MODEL_DIR
    )
    store = SQLiteStore(settings.ARTICLES_DB)
    return ReportPipeline(retriever, store)


class SessionCreate(BaseModel):
    topic: str = Field(..., min_length=4, max_length=500)
    report_type: str = Field("weekly", pattern="^(daily|weekly|deep)$")


def create_app(
    queue: TaskQueue | None = None,
    service: ReportService | None = None,
) -> FastAPI:
    app = FastAPI(title="Semiconductor Research Agent API", version="0.2.0")

    if queue is None:
        queue = ThreadPoolQueue(max_workers=2)
    if service is None:
        service = ReportService(SessionStore(settings.DB_PATH), EventBus(), default_pipeline_factory)
    app.state.queue = queue
    app.state.service = service

    async def require_token(x_api_token: str | None = Header(default=None)) -> None:
        if settings.auth_enabled() and x_api_token != settings.API_TOKEN:
            raise HTTPException(status_code=401, detail="invalid or missing X-API-Token")

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "auth_enabled": settings.auth_enabled()}

    @app.post("/api/v1/sessions", dependencies=[Depends(require_token)])
    async def create_session(req: SessionCreate = Body(...)):
        session_id = service.store.create(req.topic, req.report_type)
        task_id = queue.submit(service.run, session_id, req.topic, req.report_type)
        return {"session_id": session_id, "task_id": task_id}

    @app.get("/api/v1/sessions", dependencies=[Depends(require_token)])
    async def list_sessions(limit: int = 20):
        return {"sessions": service.store.list(limit=limit)}

    @app.get("/api/v1/sessions/{session_id}", dependencies=[Depends(require_token)])
    async def get_session(session_id: int):
        data = service.store.get(session_id)
        if data is None:
            raise HTTPException(status_code=404, detail="session not found")
        return data

    @app.get("/api/v1/sessions/{session_id}/events", dependencies=[Depends(require_token)])
    async def stream_events(session_id: int):
        if service.store.get(session_id) is None:
            raise HTTPException(status_code=404, detail="session not found")

        def gen():
            sub = service.bus.subscribe(session_id)
            try:
                while True:
                    ev = sub.next_event(timeout=20.0)
                    if ev is None:
                        yield {"event": "keepalive", "data": "{}"}
                        continue
                    yield {"event": ev["type"], "data": json.dumps(ev.get("data", {}), ensure_ascii=False)}
                    if ev["type"] in ("done", "error"):
                        break
            finally:
                sub.close()

        return EventSourceResponse(gen(), ping=15)

    return app


app = create_app()
