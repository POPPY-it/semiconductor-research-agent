"""服务层单元/集成测试：任务队列、会话库、事件总线、API（假管道，无网络）。"""
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.core import settings  # noqa: E402
from backend.app.db import SessionStore, STATUS_DONE  # noqa: E402
from backend.app.events import EventBus, wait_for_terminal  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.report_service import ReportService  # noqa: E402
from backend.app.tasks import ThreadPoolQueue  # noqa: E402


class FakePipeline:
    def generate(self, topic, report_type="weekly"):
        return {
            "report_path": "fake/path.md",
            "report": "# 假报告\n\n" + topic,
            "verdict": {"passed": True, "issues": []},
            "revision_rounds": 0,
            "model_used": "primary",
            "budget_used_chars": 100,
        }

    def answer_question(self, question, history=None):
        return {
            "question": question,
            "answer": "这是假答案：42",
            "sources": [{"title": "假来源", "url": "https://example.com/1"}],
        }


def make_app(tmp_path, token: str = "test-token-1"):
    monkey = pytest.MonkeyPatch()
    monkey.setattr(settings, "API_TOKEN", token)
    store = SessionStore(tmp_path / "app.db")
    bus = EventBus()
    queue = ThreadPoolQueue(max_workers=2)
    service = ReportService(store, bus, lambda: FakePipeline())
    return create_app(queue=queue, service=service)


def test_threadpool_queue():
    q = ThreadPoolQueue(max_workers=2)
    tid = q.submit(lambda a, b: a + b, 1, 2)
    assert q.status(tid) in ("queued", "running", "done")
    assert q.result(tid, timeout=10) == 3
    assert q.status(tid) == "done"
    with pytest.raises(KeyError):
        q.result("no-such-id")


def test_event_bus_terminal_backlog():
    bus = EventBus()
    bus.publish(1, {"type": "done", "data": {}})
    ev = bus.subscribe(1).next_event(timeout=2)
    assert ev and ev["type"] == "done"


def test_wait_for_terminal():
    bus = EventBus()
    bus.publish(7, {"type": "phase", "data": {"phase": "research"}})
    bus.publish(7, {"type": "done", "data": {"ok": True}})
    ev = wait_for_terminal(bus, 7, timeout=5)
    assert ev and ev["type"] == "done"


def test_api_full_flow(tmp_path):
    app = make_app(tmp_path)
    client = TestClient(app)
    # 无 token → 401
    resp = client.post("/api/v1/sessions", json={"topic": "测试主题", "report_type": "weekly"})
    assert resp.status_code == 401

    headers = {"X-API-Token": "test-token-1"}
    resp = client.post(
        "/api/v1/sessions", json={"topic": "半导体周报测试", "report_type": "weekly"}, headers=headers
    )
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    # 等任务完成
    deadline = time.time() + 15
    status = "queued"
    while time.time() < deadline and status not in ("done", "error"):
        time.sleep(0.3)
        status = client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()["status"]
    assert status == STATUS_DONE

    detail = client.get(f"/api/v1/sessions/{session_id}", headers=headers).json()
    assert detail["report"]["verdict"]["passed"] is True

    # 终态积压：SSE 立即返回 done
    with client.stream("GET", f"/api/v1/sessions/{session_id}/events", headers=headers) as sse:
        text = "".join(sse.iter_text())
    assert "event: done" in text

    # 列表
    sessions = client.get("/api/v1/sessions", headers=headers).json()["sessions"]
    assert any(s["id"] == session_id for s in sessions)


def test_api_validation(tmp_path):
    app = make_app(tmp_path)
    client = TestClient(app)
    headers = {"X-API-Token": "test-token-1"}
    resp = client.post("/api/v1/sessions", json={"topic": "短", "report_type": "weekly"}, headers=headers)
    assert resp.status_code == 422  # topic 过短
    resp = client.post("/api/v1/sessions", json={"topic": "正常主题", "report_type": "monthly"}, headers=headers)
    assert resp.status_code == 422  # 非法类型
