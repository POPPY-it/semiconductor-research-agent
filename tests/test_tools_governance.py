"""P1-2 工具治理测试：schema 元信息、外部 API 超时/退避/降级、参数校验文案、
MCP 独立 Tool 拆分、写稿/问答检索统一。
"""
import os
import sys
from pathlib import Path

# 本机开发环境有 socks 代理变量（ALL_PROXY=127.0.0.1:10808），httpx/openai/mcp
# 构造客户端时会尝试 socks 代理而缺少 socksio → 测试环境统一清掉代理变量。
for _k in ("ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(_k, None)

import pytest  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core import settings  # noqa: E402


class _FakeResp:
    def __init__(self, status_code=200, content=b"", json_data=None):
        self.status_code = status_code
        self.content = content
        self._json = json_data if json_data is not None else {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeRetriever:
    documents = {}

    def search_hybrid(self, q, top_k=5):
        return []

    def search_reranked(self, q, top_k=5):
        return []


class _FakeStore:
    def query_articles(self, **kw):
        return []


def _make_tool_map():
    from agent.tools import make_tools

    return {t.name: t for t in make_tools(_FakeRetriever(), _FakeStore())}


# ---------- 1. schema 元信息 ----------

def test_tool_meta_matches_make_tools():
    from agent.tools import TOOL_META, make_tools

    tools = make_tools(_FakeRetriever(), _FakeStore())
    names = [t.name for t in tools]
    # 顺序稳定：检索类在前，出图在后（兼容既有调用方解包）
    assert names == [
        "search_knowledge",
        "query_filings",
        "search_arxiv",
        "search_semantic_scholar",
        "generate_chart",
        "search_graph",
        "search_pubmed",
    ]
    assert set(names) == set(TOOL_META)
    # 每个工具都有必填字段/范围/超时/降级说明
    for name, m in TOOL_META.items():
        assert "required" in m and "range" in m and "timeout_s" in m and "degrade" in m
    # 外部 API 工具声明了超时
    for ext in ("search_arxiv", "search_semantic_scholar", "search_pubmed"):
        assert TOOL_META[ext]["timeout_s"] > 0


# ---------- 2. 外部 API：超时/退避/降级 ----------

def test_external_get_connection_error_degrades_immediately(monkeypatch):
    import requests

    from agent.tools import external_get

    calls = {"n": 0}

    def fake_get(*a, **k):
        calls["n"] += 1
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr("requests.get", fake_get)
    resp, err = external_get("https://x.example/api", timeout=5, max_attempts=3)
    assert resp is None
    assert "ConnectionError" in err  # 连接类错误不重试，直接降级
    assert calls["n"] == 1


def test_external_get_timeout_degrades_with_message(monkeypatch):
    import requests

    from agent.tools import external_get

    def fake_get(*a, **k):
        raise requests.exceptions.Timeout("timed out")

    monkeypatch.setattr("requests.get", fake_get)
    resp, err = external_get("https://x.example/api", timeout=5, label="arXiv")
    assert resp is None and err is not None


def test_external_get_backoff_retry_then_success(monkeypatch):
    import time as _time

    from agent.tools import external_get

    calls = {"n": 0}
    slept: list[float] = []

    def fake_get(*a, **k):
        calls["n"] += 1
        return _FakeResp(429) if calls["n"] < 3 else _FakeResp(200)

    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr(_time, "sleep", lambda s: slept.append(s))
    resp, err = external_get("https://x.example/api", timeout=5, backoff_base=2.0)
    assert resp is not None and err is None
    assert calls["n"] == 3
    assert slept == [2.0, 4.0]  # 指数退避：2s、4s


def test_external_get_exhausts_retries_then_degrade(monkeypatch):
    import time as _time

    from agent.tools import external_get

    monkeypatch.setattr("requests.get", lambda *a, **k: _FakeResp(429))
    monkeypatch.setattr(_time, "sleep", lambda s: None)
    resp, err = external_get("https://x.example/api", timeout=5, max_attempts=3)
    assert resp is None
    assert "HTTP 429" in err


def test_fault_injection_hook(monkeypatch):
    """SIMULATED_API_FAILURES 命中 URL 时直接模拟失败（验收演示钩子）。"""
    from agent.tools import external_get

    monkeypatch.setattr(settings, "SIMULATED_API_FAILURES", "arxiv,example.org")
    resp, err = external_get("https://export.arxiv.org/api/query?x=1", timeout=5)
    assert resp is None and "故障注入" in err


# ---------- 3. 工具级降级（人为让 arXiv 挂掉） ----------

def test_search_arxiv_degrades_when_api_down(monkeypatch):
    from agent import tools as tools_mod

    def fake_external_get(*a, **k):
        return None, "Timeout: 连接超时"

    monkeypatch.setattr(tools_mod, "external_get", fake_external_get)
    tools = _make_tool_map()
    out = tools["search_arxiv"](query="LLM agent")
    assert "arXiv 暂不可用" in out
    assert "search_knowledge" in out or "query_filings" in out  # 提示替代数据源
    assert "Traceback" not in out  # 不抛异常到编排器外面


def test_search_semantic_scholar_degrades_when_api_down(monkeypatch):
    from agent import tools as tools_mod

    def fake_external_get(*a, **k):
        return None, "HTTP 429"

    monkeypatch.setattr(tools_mod, "external_get", fake_external_get)
    tools = _make_tool_map()
    out = tools["search_semantic_scholar"](query="LLM agent")
    assert "Semantic Scholar 暂不可用" in out


def test_search_pubmed_degrades_when_api_down(monkeypatch):
    from agent import tools as tools_mod

    def boom(*a, **k):
        raise RuntimeError("eutils down")

    monkeypatch.setattr("data.collectors.pubmed.search_pubmed", boom)
    tools = _make_tool_map()
    out = tools["search_pubmed"](query="cancer")
    assert "PubMed 暂不可用" in out


# ---------- 4. 参数校验：错误回给模型，不抛出去 ----------

def test_tool_validation_returns_message_not_raise():
    tools = _make_tool_map()
    assert "limit 需在 1~10 之间" in tools["search_knowledge"](keywords="台积电", limit=0)
    assert "limit 需在 1~10 之间" in tools["search_knowledge"](keywords="台积电", limit=99)
    assert "keywords 不能为空" in tools["search_knowledge"](keywords="  ")
    assert "max_results 需在 1~10 之间" in tools["search_arxiv"](query="LLM", max_results=50)
    assert "company 不能为空" in tools["query_filings"](company="")
    assert "chart_type 只能是" in tools["generate_chart"](chart_type="3d", data="[]", title="t")
    assert "合法 JSON" in tools["generate_chart"](chart_type="bar", data="not-json", title="t")
    assert "至少含一行" in tools["generate_chart"](chart_type="bar", data="[]", title="t")
    assert "query 不能为空" in tools["search_pubmed"](query="")


def test_tool_validation_does_not_raise_on_garbage(monkeypatch):
    """极端输入也不允许把异常抛到编排器外面。"""
    tools = _make_tool_map()
    out = tools["search_knowledge"](keywords=None, limit="abc")
    assert isinstance(out, str) and "参数错误" in out


# ---------- 5. MCP：每个工具映射成独立 Tool ----------

def test_build_mcp_tools_maps_each_tool_independently(monkeypatch):
    from mcp import StdioServerParameters

    from agent import mcp_client as mc

    spec = StdioServerParameters(command="x", args=["github_server.py"])
    fake_catalog = {
        "search_github_repos": {
            "spec": spec,
            "description": "GitHub 开源仓库搜索",
            "inputSchema": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string", "description": "关键词"},
                    "limit": {"type": "integer", "description": "条数"},
                },
            },
            "server": "github",
        },
        "fetch_to_markdown": {
            "spec": spec,
            "description": "网页正文抓取",
            "inputSchema": {
                "type": "object",
                "required": ["url"],
                "properties": {"url": {"type": "string", "description": "URL"}},
            },
            "server": "fetch",
        },
    }
    monkeypatch.setattr(mc, "discover", lambda specs: fake_catalog)

    tools = mc.build_mcp_tools([spec])
    assert [t.name for t in tools] == ["search_github_repos", "fetch_to_markdown"]

    gh = tools[0]
    # schema 映射：required → nullable=False，其余 → nullable=True
    assert gh.inputs["query"]["nullable"] is False
    assert gh.inputs["limit"]["nullable"] is True
    assert gh.inputs["limit"]["type"] == "integer"
    assert "github" in gh.description

    # 成功路径
    calls = {}

    def fake_call(spec_, name, args):
        calls["name"] = name
        calls["args"] = args
        return "OK"

    monkeypatch.setattr(mc, "_call_tool", fake_call)
    assert gh(query="LLM", limit=3) == "OK"
    assert calls == {"name": "search_github_repos", "args": {"query": "LLM", "limit": 3}}


def test_mcp_tool_forward_degrades_on_error(monkeypatch):
    from mcp import StdioServerParameters

    from agent import mcp_client as mc

    spec = StdioServerParameters(command="x", args=["github_server.py"])
    monkeypatch.setattr(
        mc,
        "discover",
        lambda specs: {
            "search_github_repos": {
                "spec": spec,
                "description": "d",
                "inputSchema": {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}},
                "server": "github",
            }
        },
    )

    def boom(spec_, name, args):
        raise RuntimeError("stdio 子进程启动失败")

    monkeypatch.setattr(mc, "_call_tool", boom)
    tools = mc.build_mcp_tools([spec])
    out = tools[0](query="LLM")
    assert "调用失败" in out and "search_knowledge" in out  # 降级文案带替代工具提示


# ---------- 7. HTTP MCP（搜索代理网关） ----------

def test_build_mcp_http_tools_filters_and_maps(monkeypatch):
    """HTTP 网关工具：后缀过滤（不一次挂 24 个）+ schema 映射为独立 Tool。"""
    from agent import mcp_client as mc

    fake_tools = []
    for name, req in [
        ("search_proxy_serper_news", ["q"]),
        ("search_proxy_tavily_search", ["query"]),
        ("search_proxy_serper_search", ["q"]),
        ("search_proxy_exa_answer", ["query"]),
    ]:
        t = type("T", (), {
            "name": name,
            "description": f"{name} 描述",
            "inputSchema": {"type": "object", "properties": {r: {"type": "string"} for r in req}},
        })()
        fake_tools.append(t)

    monkeypatch.setattr(mc, "_http_connect_and_list", lambda url, headers: fake_tools)

    tools = mc.build_mcp_http_tools(
        "https://x/mcp", {"Authorization": "Bearer t"}, allow=["serper_news", "tavily_search"]
    )
    assert sorted(t.name for t in tools) == [
        "search_proxy_serper_news",
        "search_proxy_tavily_search",
    ]
    news = [t for t in tools if t.name.endswith("serper_news")][0]
    assert news.inputs["q"]["type"] == "string"
    assert "http" in news.description  # 描述标注传输类型


def test_http_mcp_tool_forward_dispatches_http(monkeypatch):
    """forward 必须走 HTTP 调用路径（含总超时），异常降级为文案。"""
    from agent import mcp_client as mc

    monkeypatch.setattr(
        mc,
        "_http_connect_and_list",
        lambda url, headers: [
            type("T", (), {
                "name": "search_proxy_serper_news",
                "description": "d",
                "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
            })()
        ],
    )
    calls = {}

    def fake_http(url, headers, name, args, timeout=45.0):
        calls.update(url=url, name=name, args=args)
        return '{"organic": []}'

    monkeypatch.setattr(mc, "_http_call_tool", fake_http)
    tools = mc.build_mcp_http_tools("https://x/mcp", {"Authorization": "Bearer t"})
    out = tools[0](q="TSMC")
    assert out == '{"organic": []}'
    assert calls == {"url": "https://x/mcp", "name": "search_proxy_serper_news", "args": {"q": "TSMC"}}

    # 失败 → 降级文案
    def boom(*a, **k):
        raise TimeoutError("网关超时")

    monkeypatch.setattr(mc, "_http_call_tool", boom)
    out2 = tools[0](q="TSMC")
    assert "调用失败" in out2 and "search_knowledge" in out2


def test_http_mcp_tool_enum_normalization(monkeypatch):
    """回归：枚举参数传非法值（如 Tavily search_depth='deep'）必须归一化而非网关 400。"""
    from agent import mcp_client as mc

    monkeypatch.setattr(
        mc,
        "_http_connect_and_list",
        lambda url, headers: [
            type("T", (), {
                "name": "search_proxy_tavily_search",
                "description": "d",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "search_depth": {
                            "type": "string",
                            "enum": ["basic", "advanced", "fast", "ultra-fast"],
                            "default": "basic",
                        },
                    },
                },
            })()
        ],
    )
    calls = {}

    def fake_http(url, headers, name, args, timeout=45.0):
        calls["args"] = args
        return '{"results": []}'

    monkeypatch.setattr(mc, "_http_call_tool", fake_http)
    tools = mc.build_mcp_http_tools("https://x/mcp", {"Authorization": "Bearer t"})
    t = tools[0]

    # schema 描述透传枚举与默认值（模型可见，防乱传）
    assert "可选值" in t.inputs["search_depth"]["description"]
    assert "basic" in t.inputs["search_depth"]["description"]

    # 非法值 → 归一化为 default，且结果带提示；合法值原样透传
    out = t(query="台积电", search_depth="deep")
    assert calls["args"] == {"query": "台积电", "search_depth": "basic"}
    assert "已归一化" in out

    out2 = t(query="台积电", search_depth="advanced")
    assert calls["args"]["search_depth"] == "advanced"
    assert "已归一化" not in out2


def test_orchestrator_merges_http_mcp_tools(monkeypatch):
    """settings 配置了 HTTP 网关时，_get_mcp_tools 合并 stdio + http 工具。"""
    from agent import orchestrator as orch

    class FakeRetriever:
        documents = {}

        def search_reranked(self, q, top_k=5):
            return []

    class FakeStore:
        def query_articles(self, **kw):
            return []

    monkeypatch.setattr(orch.settings, "MCP_SERVERS", "github")
    monkeypatch.setattr(orch.settings, "MCP_HTTP_URL", "https://x/mcp")
    monkeypatch.setattr(orch.settings, "MCP_HTTP_TOKEN", "secret-token")
    monkeypatch.setattr(orch.settings, "MCP_HTTP_TOOLS", "serper_news")

    pipe = orch.ReportPipeline(FakeRetriever(), FakeStore())
    called = {}

    def fake_stdio(specs):
        called["stdio"] = True
        return [type("T", (), {"name": "search_github_repos", "description": "s", "inputs": {}, "output_type": "string"})()]

    def fake_http(url, headers, allow=None):
        called["http"] = (url, headers, allow)
        return [type("T", (), {"name": "search_proxy_serper_news", "description": "h", "inputs": {}, "output_type": "string"})()]

    monkeypatch.setattr("agent.mcp_client.build_mcp_tools", fake_stdio)
    monkeypatch.setattr("agent.mcp_client.build_mcp_http_tools", fake_http)

    tools = pipe._get_mcp_tools()
    names = sorted(t.name for t in tools)
    assert names == ["search_github_repos", "search_proxy_serper_news"]
    assert called["http"][1] == {"Authorization": "Bearer secret-token"}
    assert called["http"][2] == ["serper_news"]


# ---------- 6. 写稿/问答检索统一（P1-2 §4.5） ----------

def test_collect_steps_detects_tools_from_python_interpreter_arguments():
    """回归：真实 CodeAgent 的代码在 python_interpreter 的 arguments 里
    （model_output 常为空）——必须从 arguments 扫描出真实工具名。"""
    from agent.traces import collect_agent_steps

    class _TC:
        def __init__(self, name, arguments):
            self.name = name
            self.arguments = arguments

    class FakeStep:
        def __init__(self, code):
            self.step_number = 1
            self.model_output = None  # 真实场景常为空
            self.tool_calls = [_TC("python_interpreter", code)]
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


def test_collect_steps_no_duplicate_tools():
    """同一工具在 model_output 与 arguments 都出现时只记一次。"""
    from agent.traces import collect_agent_steps

    class _TC:
        def __init__(self, name, arguments):
            self.name = name
            self.arguments = arguments

    class FakeStep:
        def __init__(self):
            self.step_number = 1
            self.model_output = type("M", (), {"content": "x = search_knowledge(keywords='a')"})()
            self.tool_calls = [_TC("python_interpreter", "x = search_knowledge(keywords='a')")]
            self.action_output = None
            self.error = None
            self.timing = type("T", (), {"start_time": 1.0, "end_time": 2.0})()
            self.token_usage = None

    class FakeMemory:
        steps = [FakeStep()]

    class FakeAgent:
        tools = {"search_knowledge": object(), "final_answer": object()}
        memory = FakeMemory()

    steps = collect_agent_steps(FakeAgent())
    names = [t["name"] for s in steps for t in s.get("tools", [])]
    assert names.count("search_knowledge") == 1

def test_answer_question_uses_reranked_like_reporting(monkeypatch, tmp_path):
    """问答证据面板必须与写稿 search_knowledge 走同一套 search_reranked。"""
    from agent import orchestrator as orch

    calls = {"reranked": 0, "hybrid": 0}

    class FakeRetriever:
        documents = {}

        def search_reranked(self, q, top_k=5):
            calls["reranked"] += 1
            return []

        def search_hybrid(self, q, top_k=5):
            calls["hybrid"] += 1
            return []

    class FakeAgent:
        def __init__(self, *a, **k):
            pass

        def run(self, task):
            return "答案正文（含 12 亿美元数据）"

    monkeypatch.setattr(orch, "CodeAgent", FakeAgent)
    monkeypatch.setattr(orch, "build_model", lambda: object())  # 避免构造 OpenAI 客户端
    monkeypatch.setattr(orch.settings, "MEMORY_DB", tmp_path / "mem.db")
    monkeypatch.setattr(orch.settings, "TRACE_DIR", tmp_path / "traces")
    monkeypatch.setattr(orch.settings, "TOKEN_BUDGET_CHARS", 100_000)

    pipe = orch.ReportPipeline(FakeRetriever(), _FakeStore())
    monkeypatch.setattr(pipe, "_get_mcp_tools", lambda: [])
    monkeypatch.setattr(pipe, "_extract_and_store_memories", lambda q, a: None)

    result = pipe.answer_question("台积电营收？")
    assert result["answer"] == "答案正文（含 12 亿美元数据）"
    assert calls["reranked"] == 1
    assert calls["hybrid"] == 0  # 旧实现走 search_hybrid，此处断言已统一
