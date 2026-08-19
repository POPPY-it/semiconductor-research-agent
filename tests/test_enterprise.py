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


def test_report_type_whitelist(tmp_path):
    """研投 basic_research 可通过白名单；非法类型 422。"""
    client = TestClient(make_app(tmp_path))
    headers = {"X-API-Token": "test-token-1"}
    ok = client.post(
        "/api/v1/sessions",
        json={"topic": "台积电基本面分析测试选题", "report_type": "basic_research"},
        headers=headers,
    )
    assert ok.status_code == 200
    bad = client.post(
        "/api/v1/sessions",
        json={"topic": "非法类型测试", "report_type": "not_a_type"},
        headers=headers,
    )
    assert bad.status_code == 422


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
    _sk, _ps, _qf, _sa, _sss, gen_chart, _sg, _sp = pipe._make_tools()
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


def test_memory_store_keyword_path(tmp_path):
    from agent.memory import MemoryStore

    m = MemoryStore(tmp_path / "mem.db")  # 无 embedder → 关键词召回路径
    m.add("用户关注 HBM 与先进封装方向")
    m.add("用户偏好半导体行业深度研报")
    hits = m.search("HBM 最近有什么进展", top_k=3)
    assert any("HBM" in x for x in hits)
    assert len(m.list_all()) == 2
    assert m.clear() == 2
    assert m.list_all() == []


def test_memory_extract_with_fake_client():
    from agent.memory import MemoryStore

    class _Completions:
        def create(self, **kwargs):
            class _Msg:
                content = '["用户关注存内计算方向", "用户在做秋招项目"]'

            class _Choice:
                message = _Msg()

            class _Resp:
                choices = [_Choice()]

            return _Resp()

    class _Chat:
        completions = _Completions()

    class FakeClient:
        model_id = "fake"
        chat = _Chat()

    facts = MemoryStore.extract(FakeClient(), "问：存内计算有什么进展 答：PIM 论文很多")
    assert facts == ["用户关注存内计算方向", "用户在做秋招项目"]


def test_extract_json_handles_multiple_braces():
    from agent.orchestrator import _extract_json

    # 多组花括号 + 嵌套：应取第一个完整可解析的 JSON（旧贪心正则会把多个对象吸成一个而失败）
    text = '结论如下 {"a": {"b": 1}} 以及 {"c": 2} 其他文字'
    assert _extract_json(text) == {"a": {"b": 1}}
    # 无效 JSON 应跳过继续找
    assert _extract_json('{"x": } 垃圾 {"ok": 1}') == {"ok": 1}
    assert _extract_json("无 JSON") is None
    assert _extract_json(None) is None


def test_analyze_numbers_with_citations():
    from agent.traces import analyze_numbers

    md = (
        "台积电营收 4675.8 亿元 [来源](https://www.sec.gov/x)\n"
        "同比增长 44.7%。另有未标注数字 12 亿美元。"
    )
    r = analyze_numbers(md)
    assert r["total_numbers"] == 3
    assert r["numbers_without_url"] == 2  # 44.7% 与 12 亿美元无链接
    assert r["uncited_rate"] > 0


def test_save_trace_roundtrip(tmp_path):
    from agent.traces import new_run_id, save_trace

    rid = new_run_id()
    path = save_trace(
        tmp_path, rid, "report", "测试选题",
        [{"kind": "ActionStep", "role": "researcher", "tools": [{"name": "search_knowledge"}]}],
        {"verdict": {"passed": True}, "duration_s": 1.2},
    )
    import json

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["run_id"] == rid
    assert record["steps"][0]["role"] == "researcher"
    assert record["meta"]["verdict"]["passed"] is True


def test_fallback_switch_uses_new_agent(tmp_path, monkeypatch):
    """回归：连接类错误触发备用模型后，重试必须用重建后的新 Agent（旧实现用旧实例）。"""
    from agent import orchestrator as orch

    calls: dict[str, list[str]] = {"researcher_runs": [], "qa_runs": []}

    class FakeModel:
        def __init__(self, tag):
            self.tag = tag

    class APIConnectionError(Exception):
        pass

    class FakeResearcher:
        def __init__(self, model):
            self.model = model

        def run(self, task, reset=True):
            calls["researcher_runs"].append(self.model.tag)
            if len(calls["researcher_runs"]) == 1:
                raise APIConnectionError("Connection error")
            return "# 报告\n\n正文内容"

    class FakeQA:
        def __init__(self, model):
            self.model = model

        def run(self, task, reset=True):
            calls["qa_runs"].append(self.model.tag)
            return {"passed": True, "issues": []}

    class FakeRetriever:
        documents = {}

        def search_hybrid(self, q, top_k=5):
            return []

    class FakeStore:
        def query_articles(self, **kw):
            return []

    monkeypatch.setattr(orch, "build_model", lambda: FakeModel("primary"))
    monkeypatch.setattr(orch, "build_fallback_model", lambda: FakeModel("fallback"))
    monkeypatch.setattr(orch.settings, "TOKEN_BUDGET_CHARS", 1000000)
    monkeypatch.setattr(orch.settings, "MEMORY_DB", tmp_path / "mem.db")
    monkeypatch.setattr(orch.settings, "VECTOR_DIR", tmp_path / "vec")
    monkeypatch.setattr(orch.settings, "REPORT_DIR", tmp_path / "reports")
    monkeypatch.setattr(orch.settings, "TRACE_DIR", tmp_path / "traces")
    monkeypatch.setattr(
        orch.ReportPipeline,
        "_build_agents",
        lambda self, model, report_type="weekly": (FakeResearcher(model), FakeQA(model)),
    )

    pipe = orch.ReportPipeline(FakeRetriever(), FakeStore())
    result = pipe.generate("测试选题")
    # 分节独立 run + 反思循环：第 1 节（weekly=4 节）主模型失败 → 切换后重试该节 +
    # 其余 3 节 + 反思轮都用备用模型的新 Agent
    assert calls["researcher_runs"][0] == "primary"
    assert len(calls["researcher_runs"]) == 6  # 节1失败重试 + 4 节 + 反思 1 轮
    assert all(tag == "fallback" for tag in calls["researcher_runs"][1:])
    assert result["model_used"] == "fallback"
    # 轨迹已落盘（P0-2）
    trace_files = list((tmp_path / "traces").glob("*.jsonl"))
    assert len(trace_files) == 1
    import json

    record = json.loads(trace_files[0].read_text(encoding="utf-8"))
    assert record["kind"] == "report"
    assert record["meta"]["model_used"] == "fallback"


class _HashEmbedder:
    """确定性假 Embedder（与 test_knowledge 同思路）。"""

    def __init__(self, dim=32):
        self.dim = dim

    def embed(self, texts):
        out = []
        for t in texts:
            vec = [0.0] * self.dim
            for ch in t:
                vec[ord(ch) % self.dim] += 1.0
            norm = sum(x * x for x in vec) ** 0.5 or 1.0
            out.append([x / norm for x in vec])
        return out


def test_memory_vector_search_maps_by_id(tmp_path):
    """回归：向量召回必须按 rowid 映射记忆文本（旧实现把倒序列表下标当 doc_id 用）。"""
    from agent.memory import MemoryStore

    m = MemoryStore(tmp_path / "mem.db", embedder=_HashEmbedder(), vector_dir=tmp_path / "vec")
    m.add("记忆A：用户关注 HBM")
    m.add("记忆B：用户关注存内计算")
    m.add("记忆C：用户关注先进封装")
    # 删除中间一条 → rowid 不连续（1,3）；旧实现 DESC 列表为 [C,A]，doc_id=1 会被错当 index 1 → 返回 C
    m._conn.execute("DELETE FROM memories WHERE content LIKE '%记忆B%'")

    result = m.search("记忆A：用户关注 HBM", top_k=2)
    assert result[0] == "记忆A：用户关注 HBM"  # 旧实现会返回"记忆C"


def test_collect_agent_steps_detects_tools_from_code():
    """CodeAgent 的真实工具调用在代码里——collect_agent_steps 应把它们补进轨迹。"""
    from agent.traces import collect_agent_steps

    class FakeStep:
        def __init__(self, code):
            self.step_number = 1
            self.model_output = type("M", (), {"content": code})()
            self.tool_calls = []
            self.action_output = None
            self.error = None
            self.timing = type("T", (), {"start_time": 1.0, "end_time": 2.0})()
            self.token_usage = None

    class FakeMemory:
        steps = [
            FakeStep("result = search_knowledge(keywords='台积电', limit=3)\nprint(result)"),
            FakeStep("rows = query_filings(company='NVIDIA')"),
        ]

    class FakeAgent:
        tools = {"search_knowledge": object(), "query_filings": object(), "final_answer": object()}
        memory = FakeMemory()

    steps = collect_agent_steps(FakeAgent())
    seen = {t["name"] for s in steps for t in s.get("tools", [])}
    assert "search_knowledge" in seen
    assert "query_filings" in seen


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


def test_deterministic_gate_rejects_low_citation():
    """GPT 审查 §4.3：数字级引用率低于阈值时，即使 LLM 质检通过也按策略处理。"""
    m = pytest.MonkeyPatch()
    m.setattr(settings, "QA_POLICY", "reject")
    m.setattr(settings, "MIN_NUMBER_CITATION_RATE", 0.3)
    result = {
        "report": "毛利率 54% 是一个没有紧邻来源的数字，后面跟很长文字填满窗口。",
        "verdict": {"passed": True, "issues": []},
        "deterministic_gate": {"ok": False, "rate": 0.0},
    }
    assert _apply_qa_policy(result) == ""  # reject：拒交

    m.setattr(settings, "QA_POLICY", "caveat")
    md = _apply_qa_policy(result)
    assert "确定性门禁未通过" in md  # caveat：横幅注明门禁未通过
    assert "54%" in md  # 正文仍交付


def test_deterministic_gate_rejects_low_url_grounding():
    """证据包门禁：URL 落地率低于阈值时拒交/横幅（报告 URL 必须来自检索结果）。"""
    m = pytest.MonkeyPatch()
    m.setattr(settings, "QA_POLICY", "reject")
    m.setattr(settings, "MIN_URL_GROUNDING_RATE", 0.8)
    result = {
        "report": "# 正文",
        "verdict": {"passed": True, "issues": []},
        "deterministic_gate": {
            "ok": False,
            "rate": 0.9,
            "url_grounding_rate": 0.5,
            "ungrounded_urls": ["https://evil.example.com/fake"],
        },
    }
    assert _apply_qa_policy(result) == ""  # reject：拒交

    m.setattr(settings, "QA_POLICY", "caveat")
    md = _apply_qa_policy(result)
    assert "确定性门禁未通过" in md
    assert "evil.example.com" in md  # 疑似编造 URL 展示在横幅


def test_deterministic_gate_passed_ok():
    result = {
        "report": "# 正文",
        "verdict": {"passed": True, "issues": []},
        "deterministic_gate": {"ok": True, "rate": 0.9, "url_grounding_rate": 0.95},
    }
    assert _apply_qa_policy(result) == "# 正文"  # 门禁通过 + 质检通过 → 原样交付
