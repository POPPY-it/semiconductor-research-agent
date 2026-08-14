"""服务层 API（M5+W8 企业级版）。

安全：X-API-Token 登录换取 HttpOnly Cookie（SSE 自动携带，token 不进 URL/日志）；
防护：请求 ID 审计日志、速率限制；可靠性：启动恢复中断会话、失败任务可重试；
可观测：/api/metrics（Prometheus 文本）+ 深度健康检查。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

from fastapi import Body, Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from .auth import issue_auth_cookie, verify_auth_cookie
from .core import settings
from .db import SessionStore
from .events import EventBus
from .middleware import RequestLogMiddleware, RateLimitMiddleware, metrics
from .report_service import ReportService
from .tasks import RQQueue, TaskQueue, ThreadPoolQueue

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
    report_type: str = Field("weekly", pattern="^(daily|weekly|deep|survey)$")


class LoginRequest(BaseModel):
    token: str = Field(..., min_length=1)


class QuestionRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=500)
    conversation_id: int | None = Field(default=None)


def create_app(
    queue: TaskQueue | None = None,
    service: ReportService | None = None,
) -> FastAPI:
    app = FastAPI(title="Semiconductor Research Agent API", version="0.3.0")
    app.add_middleware(RequestLogMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if queue is None:
        if settings.APP_QUEUE == "rq":
            queue = RQQueue(settings.REDIS_URL)  # 生产规模化路径（requirements-prod + Redis）
        else:
            queue = ThreadPoolQueue(max_workers=2)
    if service is None:
        service = ReportService(SessionStore(settings.DB_PATH), EventBus(), default_pipeline_factory)
    app.state.queue = queue
    app.state.service = service

    # 启动恢复：上次进程中断的会话标为 error，用户可重试
    recovered = service.store.recover_stale()
    if recovered:
        logger.warning("恢复 %d 个中断会话（已标记 error，可重试）", recovered)

    async def require_auth(
        request: Request,
        x_api_token: str | None = Header(default=None),
    ) -> None:
        cookie = request.cookies.get(settings.AUTH_COOKIE, "")
        header_ok = settings.auth_enabled() and x_api_token == settings.API_TOKEN
        cookie_ok = bool(cookie) and verify_auth_cookie(cookie, settings.COOKIE_SECRET)
        if not (header_ok or cookie_ok):
            raise HTTPException(status_code=401, detail="invalid or missing credentials")

    @app.post("/api/v1/auth/login")
    async def login(req: LoginRequest):
        if not settings.auth_enabled() or req.token != settings.API_TOKEN:
            raise HTTPException(status_code=401, detail="invalid token")
        cookie_value = issue_auth_cookie(settings.COOKIE_SECRET, ttl=settings.AUTH_COOKIE_TTL)
        from fastapi.responses import JSONResponse

        resp = JSONResponse({"ok": True, "expires_in": settings.AUTH_COOKIE_TTL})
        resp.set_cookie(
            settings.AUTH_COOKIE,
            cookie_value,
            max_age=settings.AUTH_COOKIE_TTL,
            httponly=True,
            samesite="lax",
        )
        return resp

    @app.post("/api/v1/auth/logout")
    async def logout():
        from fastapi.responses import JSONResponse

        resp = JSONResponse({"ok": True})
        resp.delete_cookie(settings.AUTH_COOKIE)
        return resp

    @app.get("/api/health")
    async def health():
        from data.storage import SQLiteStore

        articles = 0
        try:
            s = SQLiteStore(settings.ARTICLES_DB)
            articles = s.count()
            s.close()
        except Exception:  # noqa: BLE001 —— 健康检查不因附属库失败而 500
            pass
        return {
            "status": "ok",
            "version": "0.3.0",
            "auth_enabled": settings.auth_enabled(),
            "queue": {"pending": queue.pending() if hasattr(queue, "pending") else None},
            "articles": articles,
            "qa_policy": settings.QA_POLICY,
            "llm": settings.LLM_MODEL,
            "fallback_llm": settings.FALLBACK_LLM_MODEL or None,
        }

    @app.get("/api/metrics", include_in_schema=False)
    async def get_metrics():
        return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")

    @app.post("/api/v1/sessions", dependencies=[Depends(require_auth)])
    async def create_session(req: SessionCreate = Body(...)):
        session_id = service.store.create(req.topic, req.report_type)
        task_id = queue.submit(service.run, session_id, req.topic, req.report_type)
        return {"session_id": session_id, "task_id": task_id}

    @app.post("/api/v1/qa", dependencies=[Depends(require_auth)])
    async def ask_question(req: QuestionRequest = Body(...)):
        """多轮问答：可携带 conversation_id 复用历史上下文；首次提问自动建会话。"""
        store = service.store
        conversation_id = req.conversation_id
        if conversation_id is None:
            conversation_id = store.create_conversation(req.question)
        history = store.get_qa_history(conversation_id)
        result = service.qa(req.question, history=history)
        store.add_qa_message(conversation_id, "user", req.question)
        store.add_qa_message(conversation_id, "assistant", result["answer"], result["sources"])
        return {**result, "conversation_id": conversation_id}

    @app.get("/api/v1/qa/conversations", dependencies=[Depends(require_auth)])
    async def list_conversations():
        return {"conversations": service.store.list_conversations()}

    @app.get("/api/v1/qa/conversations/{conversation_id}", dependencies=[Depends(require_auth)])
    async def get_conversation(conversation_id: int):
        return {"messages": service.store.get_qa_history(conversation_id)}

    @app.post("/api/v1/documents", dependencies=[Depends(require_auth)])
    async def upload_document(file: UploadFile = File(...)):
        """上传文档（PDF/txt/md/html）→ 解析入库 → 重建知识库索引。"""
        from data.parsers import parse_document
        from data.storage import SQLiteStore

        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="empty file")
        content = parse_document(data, file.filename or "upload.txt")
        if not content.strip():
            raise HTTPException(status_code=400, detail="无法解析文档内容")
        store = SQLiteStore(settings.ARTICLES_DB)
        try:
            new = store.upsert_articles(
                [
                    {
                        "source": "upload",
                        "title": file.filename or "upload.txt",
                        "url": f"upload://{file.filename or 'file'}",
                        "content": content,
                    }
                ]
            )
        finally:
            store.close()
        service.reindex()  # 重建知识库索引（与生成任务互斥）
        return {"title": file.filename, "chars": len(content), "new": new}

    @app.get("/api/v1/documents", dependencies=[Depends(require_auth)])
    async def list_documents():
        from data.storage import SQLiteStore

        store = SQLiteStore(settings.ARTICLES_DB)
        try:
            rows = store.query_articles(source="upload", limit=100)
        finally:
            store.close()
        return {
            "documents": [
                {"title": r["title"], "chars": len(r["content"]), "fetched_at": ""}
                for r in rows
            ]
        }

    @app.get("/api/v1/sessions", dependencies=[Depends(require_auth)])
    async def list_sessions(limit: int = 20):
        return {"sessions": service.store.list(limit=limit)}

    @app.get("/api/v1/sessions/{session_id}", dependencies=[Depends(require_auth)])
    async def get_session(session_id: int):
        data = service.store.get(session_id)
        if data is None:
            raise HTTPException(status_code=404, detail="session not found")
        return data

    @app.post("/api/v1/sessions/{session_id}/retry", dependencies=[Depends(require_auth)])
    async def retry_session(session_id: int):
        data = service.store.get(session_id)
        if data is None:
            raise HTTPException(status_code=404, detail="session not found")
        service.store.set_status(session_id, "queued")
        task_id = queue.submit(service.run, session_id, data["topic"], data["report_type"])
        return {"session_id": session_id, "task_id": task_id}

    @app.get("/api/v1/sessions/{session_id}/report", dependencies=[Depends(require_auth)])
    async def get_report_md(session_id: int):
        data = service.store.get(session_id)
        if data is None:
            raise HTTPException(status_code=404, detail="session not found")
        return {"report_md": service.store.get_report_md(session_id)}

    @app.get("/api/v1/sessions/{session_id}/events", dependencies=[Depends(require_auth)])
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

    # 生产模式：托管前端构建产物（frontend/dist 存在时挂载）
    import mimetypes

    from fastapi.staticfiles import StaticFiles

    # Windows 上 mimetypes 依赖注册表，需显式注册（否则 .js 被当 text/plain，模块脚本加载失败）
    for ext, mime in (
        (".js", "text/javascript"),
        (".mjs", "text/javascript"),
        (".css", "text/css"),
        (".svg", "image/svg+xml"),
        (".json", "application/json"),
        (".woff2", "font/woff2"),
    ):
        mimetypes.add_type(mime, ext)

    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")

    return app


app = create_app()
