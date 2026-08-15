"""企业级加固测试：认证 Cookie、限流、恢复、重试、token 预算、质检交付策略。"""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from agent.llm import BudgetedModel, BudgetExceededError  # noqa: E402
from backend.app.auth import issue_auth_cookie, verify_auth_cookie  # noqa: E402
from backend.app.core import settings  # noqa: E402
from backend.app.db import SessionStore  # noqa: E402
from backend.app.events import EventBus  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.report_service import ReportService, _apply_qa_policy  # noqa: E402
from backend.app.tasks import ThreadPoolQueue  # noqa: E402


# ---------- 认证 Cookie ----------

def test_auth_cookie_roundtrip_and_expiry():
    tok = issue_auth_cookie("secret-1", ttl=60)
    assert verify_auth_cookie(tok, "secret-1") is True
    assert verify_auth_cookie(tok, "wrong-secret") is False
    assert verify_auth_cookie("garbage.value", "secret-1") is False
    expired = issue_auth_cookie("secret-1", ttl=-10)
    assert verify_auth_cookie(expired, "secret-1") is False


def make_app(tmp_path, token="test-token-1"):
    m = pytest.MonkeyPatch()
    m.setattr(settings, "API_TOKEN", token)
    m.setattr(settings, "COOKIE_SECRET", "test-cookie-secret")
    store = SessionStore(tmp_path / "app.db")
    bus = EventBus()
    queue = ThreadPoolQueue(max_workers=2)

    class FakePipeline:
        def generate(self, topic, report_type="weekly"):
            return {
                "report_path": "fake.md",
                "report": "# 报告\n\n" + topic,
                "verdict": {"passed": True, "issues": []},
                "revision_rounds": 0,
                "model_used": "primary",
                "budget_used_chars": 100,
            }

        def answer_question(self, question, history=None):
            return {
                "question": question,
                "answer": "假答案",
                "sources": [{"title": "来源", "url": "https://example.com/x"}],
            }

        def rebuild(self):
            pass  # 假管道：重建索引为 no-op

    service = ReportService(store, bus, lambda: FakePipeline())
    return create_app(queue=queue, service=service)


def test_login_sets_httponly_cookie(tmp_path):
    client = TestClient(make_app(tmp_path))
    resp = client.post("/api/v1/auth/login", json={"token": "test-token-1"})
    assert resp.status_code == 200
    set_cookie = resp.headers.get("set-cookie", "")
    assert "agent_auth=" in set_cookie and "HttpOnly" in set_cookie
    # 用 Cookie（不再传 header）创建会话
    resp2 = client.post(
        "/api/v1/sessions", json={"topic": "用Cookie认证的会话", "report_type": "daily"}
    )
    assert resp2.status_code == 200

    resp3 = client.post("/api/v1/auth/login", json={"token": "wrong"})
    assert resp3.status_code == 401


def test_rate_limit_on_session_create(tmp_path):
    client = TestClient(make_app(tmp_path))
    headers = {"X-API-Token": "test-token-1"}
    codes = [
        client.post(
            "/api/v1/sessions",
            json={"topic": f"限流测试主题{i:02d}", "report_type": "daily"},
            headers=headers,
        ).status_code
        for i in range(7)
    ]
    assert codes.count(200) == 5  # 前 5 次放行
    assert codes[-2:] == [429, 429]  # 之后被限流


def test_retry_endpoint(tmp_path):
    client = TestClient(make_app(tmp_path))
    headers = {"X-API-Token": "test-token-1"}
    sid = client.post(
        "/api/v1/sessions", json={"topic": "重试测试主题", "report_type": "daily"}, headers=headers
    ).json()["session_id"]
    deadline = time.time() + 10
    while time.time() < deadline:
        if client.get(f"/api/v1/sessions/{sid}", headers=headers).json()["status"] == "done":
            break
        time.sleep(0.2)
    # 模拟失败后重试
    resp = client.post(f"/api/v1/sessions/{sid}/retry", headers=headers)
    assert resp.status_code == 200
    assert client.get(f"/api/v1/sessions/{sid}", headers=headers).json()["status"] in (
        "queued",
        "running",
        "done",
    )


def test_qa_endpoint(tmp_path):
    client = TestClient(make_app(tmp_path))
    headers = {"X-API-Token": "test-token-1"}
    resp = client.post(
        "/api/v1/qa", json={"question": "台积电营收？"}, headers=headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"] == "假答案"
    assert data["sources"][0]["url"] == "https://example.com/x"
    assert data["conversation_id"] > 0
    # 未认证 → 401
    assert client.post("/api/v1/qa", json={"question": "x?"}).status_code == 401


def test_multi_turn_conversation(tmp_path):
    client = TestClient(make_app(tmp_path))
    headers = {"X-API-Token": "test-token-1"}
    # 第一问：自动建会话
    r1 = client.post("/api/v1/qa", json={"question": "台积电营收？"}, headers=headers).json()
    conv_id = r1["conversation_id"]
    # 追问：携带 conversation_id
    r2 = client.post(
        "/api/v1/qa",
        json={"question": "那 ASML 呢？", "conversation_id": conv_id},
        headers=headers,
    ).json()
    assert r2["conversation_id"] == conv_id
    # 会话历史应有 4 条（2 问 2 答）
    msgs = client.get(f"/api/v1/qa/conversations/{conv_id}", headers=headers).json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    # 会话列表包含该会话
    convs = client.get("/api/v1/qa/conversations", headers=headers).json()["conversations"]
    assert any(c["id"] == conv_id for c in convs)


def test_upload_document_endpoint(tmp_path):
    m = pytest.MonkeyPatch()
    m.setattr(settings, "ARTICLES_DB", tmp_path / "articles.db")
    client = TestClient(make_app(tmp_path))
    headers = {"X-API-Token": "test-token-1"}
    resp = client.post(
        "/api/v1/documents",
        headers=headers,
        files={"file": ("季报.txt", "这是一份测试文档内容，包含半导体行业数据。".encode("utf-8"), "text/plain")},
    )
    assert resp.status_code == 200
    assert resp.json()["new"] == 1
    # 文档列表
    docs = client.get("/api/v1/documents", headers=headers).json()["documents"]
    assert any(d["title"] == "季报.txt" for d in docs)
    # 无认证 → 401
    assert client.post(
        "/api/v1/documents",
        files={"file": ("x.txt", b"x", "text/plain")},
    ).status_code == 401


def test_recover_stale(tmp_path):
    store = SessionStore(tmp_path / "app.db")
    a = store.create("话题A", "daily")
    b = store.create("话题B", "weekly")
    store.set_status(b, "running")
    n = store.recover_stale()
    assert n == 2  # queued 与 running 都被恢复为 error
    assert store.get(a)["status"] == "error"
    assert store.get(b)["status"] == "error"


def test_generate_chart_tool(tmp_path):
    m = pytest.MonkeyPatch()
    m.setattr(settings, "CHART_DIR", tmp_path / "charts")

    from agent.orchestrator import ReportPipeline

    class FakeRetriever:
        documents = {}

        def search_hybrid(self, q, top_k=5):
            return []

        def search_reranked(self, q, top_k=5):
            return []

    class FakeStore:
        def query_articles(self, **kw):
            return []

    pipe = ReportPipeline(FakeRetriever(), FakeStore())
    _sk, _qf, _sa, _sss, gen_chart, _sg = pipe._make_tools()
    md = gen_chart("bar", '[{"label":"A","value":10},{"label":"B","value":20}]', "测试图表")
    assert md.startswith("![测试图表](/charts/")
    fname = md.split("(/charts/")[1].rstrip(")")
    assert (tmp_path / "charts" / fname).exists()


def test_knowledge_graph():
    from agent.knowledge.graph import EntityExtractor, KnowledgeGraph

    g = KnowledgeGraph()
    g.add_document("d1", "台积电 2nm 先进封装 CoWoS 产能爬坡，与 NVIDIA 合作 HBM")
    g.add_document("d2", "台积电 2nm 与 ASML EUV 光刻设备采购")
    g.add_document("d3", "LLM Agent 的 RAG 检索增强研究")
    assert g.stats()["nodes"] >= 5
    # 台积电的关联实体应包含 2nm / 先进封装 / NVIDIA / ASML 等
    related = [e for e, _w in g.related_entities("台积电", 20)]
    assert "2nm" in related and "先进封装" in related
    # 全局核心实体非空
    assert len(g.centrality(10)) > 0


# ---------- token 预算熔断 ----------

class FakeModel:
    def __init__(self):
        self.model_id = "fake"

    def generate(self, messages, **kwargs):
        return type("Msg", (), {"content": "x" * 100})()


def test_budget_model_aborts_when_exceeded():
    wrapped = BudgetedModel(FakeModel(), budget_chars=250)
    wrapped.generate([{"content": "a" * 200}])  # 200 < 250 OK
    with pytest.raises(BudgetExceededError):
        wrapped.generate([{"content": "b" * 100}])  # 累计 300 > 250 → 熔断


def test_budget_model_accepts_chatmessage_objects():
    # smolagents 实际传入的是 ChatMessage 对象而非 dict
    wrapped = BudgetedModel(FakeModel(), budget_chars=500)

    class ChatMessage:
        def __init__(self, content):
            self.content = content

    wrapped.generate([ChatMessage("a" * 100)])
    assert wrapped.used_chars >= 100


def test_budget_error_unwrapped_from_wrapper():
    from agent.orchestrator import _extract_budget_error

    inner = BudgetExceededError("预算超限")
    try:
        raise inner
    except BudgetExceededError as e1:
        try:
            raise RuntimeError("Error in generating model output: token 预算超限") from e1
        except RuntimeError as e2:
            found = _extract_budget_error(e2)
            assert found is inner  # 沿 __cause__ 链找回原始熔断异常


# ---------- 质检交付策略 ----------

def test_qa_policy_caveat_injects_banner():
    m = pytest.MonkeyPatch()
    m.setattr(settings, "QA_POLICY", "caveat")
    result = {
        "report": "# 正文\n\n内容",
        "verdict": {"passed": False, "issues": ["数字无来源"]},
    }
    md = _apply_qa_policy(result)
    assert md.startswith("> ⚠️ **质检未通过**")
    assert "数字无来源" in md and "正文" in md


def test_qa_policy_reject_returns_empty():
    m = pytest.MonkeyPatch()
    m.setattr(settings, "QA_POLICY", "reject")
    result = {
        "report": "# 正文",
        "verdict": {"passed": False, "issues": ["数字无来源"]},
    }
    assert _apply_qa_policy(result) == ""


def test_qa_policy_passed_untouched():
    m = pytest.MonkeyPatch()
    m.setattr(settings, "QA_POLICY", "reject")
    result = {"report": "# 正文", "verdict": {"passed": True, "issues": []}}
    assert _apply_qa_policy(result) == "# 正文"
