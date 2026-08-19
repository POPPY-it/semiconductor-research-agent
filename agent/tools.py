"""工具层治理（P1-2）：把散落在编排器里的工具收成「可治理」的集中模块。

企业可验收的 4 点：
1. 每个工具一份 schema 元信息（必填字段、取值范围、超时）——见 TOOL_META；
2. 参数校验失败回给模型「哪错了」，不抛到编排器外面（工具内部 return 文案）；
3. 外部 API（arXiv / S2 / PubMed）统一：超时、429/5xx 指数退避、降级文案
   ——见 external_get；单源故障时任务仍可用知识库 + SEC 出报告；
4. 写稿检索（search_knowledge）与问答检索（answer_question 证据面板）
   统一走 search_reranked（混合召回 + 精排），不再一处 reranked 一处 hybrid。

故障注入钩子：settings.SIMULATED_API_FAILURES（逗号分隔域名片段，如 "arxiv"）
命中即模拟失败，用于验收「外部 API 挂掉任务不炸」。
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from smolagents import tool

from backend.app.core import settings

# ---------------------------------------------------------------- 工具元信息

TOOL_META: dict[str, dict] = {
    "search_knowledge": {
        "required": ["keywords"],
        "range": {"limit": (1, 10)},
        "timeout_s": None,  # 本地索引（BM25+向量+精排），无外部超时
        "source": "本地知识库（新闻与财报全文）",
        "degrade": "本地工具，不涉及外部 API",
    },
    "parallel_search": {
        "required": ["queries"],
        "range": {"limit": (1, 5), "queries_len": (2, 6)},
        "timeout_s": None,
        "source": "本地知识库（多查询并发，差距收敛第 2 项）",
        "degrade": "本地工具；单条查询失败返回该条错误，不阻塞整体",
    },
    "query_filings": {
        "required": ["company"],
        "range": {"limit": (1, 10)},
        "timeout_s": None,
        "source": "本地 SEC 财报索引（已入库披露记录）",
        "degrade": "本地工具，不涉及外部 API",
    },
    "search_arxiv": {
        "required": ["query"],
        "range": {"max_results": (1, 10)},
        "timeout_s": 15,
        "source": "arXiv API（export.arxiv.org，官方限速 ≥3s/请求）",
        "degrade": "返回「arXiv 暂不可用」文案并提示改用 search_knowledge / query_filings",
    },
    "search_semantic_scholar": {
        "required": ["query"],
        "range": {"limit": (1, 10)},
        "timeout_s": 15,
        "source": "Semantic Scholar Graph API（匿名限流较重）",
        "degrade": "429 指数退避重试 3 次后返回「暂不可用」文案",
    },
    "search_pubmed": {
        "required": ["query"],
        "range": {"limit": (1, 10)},
        "timeout_s": 20,
        "source": "NCBI E-utilities（esearch + efetch）",
        "degrade": "异常返回「暂不可用」文案并提示改用 search_knowledge",
    },
    "search_graph": {
        "required": [],
        "range": {},
        "timeout_s": None,
        "source": "本地实体共现图",
        "degrade": "本地工具，不涉及外部 API",
    },
    "generate_chart": {
        "required": ["chart_type", "data", "title"],
        "range": {"chart_type": ["bar", "line", "pie"]},
        "timeout_s": None,
        "source": "本地 matplotlib 出图",
        "degrade": "本地工具，不涉及外部 API",
    },
}


def tool_meta_summary() -> str:
    """面向 README/面试的紧凑清单。"""
    lines = ["工具 schema 清单（必填 / 范围 / 超时 / 来源）："]
    for name, m in TOOL_META.items():
        rng = m["range"] or "无"
        timeout = f"{m['timeout_s']}s" if m["timeout_s"] else "本地"
        lines.append(
            f"- {name}: 必填 {m['required'] or '无'}，范围 {rng}，超时 {timeout}，"
            f"来源 {m['source']}，降级：{m['degrade']}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------- 外部 API 治理

def external_get(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: float = 15.0,
    max_attempts: int = 3,
    backoff_base: float = 2.0,
    retry_statuses: tuple[int, ...] = (429, 500, 502, 503, 504),
    sleep_before: float = 0.0,
    label: str = "",
) -> tuple[Any | None, str | None]:
    """统一外部 API 请求：超时 + 429/5xx 指数退避 + 降级文案。

    返回 (resp, None) 成功，或 (None, 降级文案) 失败——**绝不抛异常到编排器外面**。

    - 连接类/超时错误不重试，立即降级（企业验收点：单源故障不炸整单）；
    - 429/5xx 退避重试 max_attempts 次后降级；
    - SIMULATED_API_FAILURES 命中 URL 时直接模拟失败（故障注入演示）。
    """
    import requests as _requests

    injected = [d.strip() for d in str(settings.SIMULATED_API_FAILURES).split(",") if d.strip()]
    if injected and any(d in url for d in injected):
        return None, f"故障注入（SIMULATED_API_FAILURES 命中 {injected}）"

    if sleep_before > 0:
        time.sleep(sleep_before)

    name = label or url
    attempt = 0
    while True:
        try:
            resp = _requests.get(url, params=params, headers=headers, timeout=timeout)
        except _requests.RequestException as e:
            # 连接类/超时错误：不重试，直接降级
            return None, f"{type(e).__name__}: {e}"
        if resp.status_code in retry_statuses and attempt < max_attempts - 1:
            attempt += 1
            time.sleep(backoff_base * (2 ** (attempt - 1)))
            continue
        if resp.status_code >= 400:
            return None, f"HTTP {resp.status_code}"
        return resp, None


# ---------------------------------------------------------------- 参数校验

def _check_range(name: str, value: Any, lo: int, hi: int, default: int) -> tuple[bool, int | str]:
    """校验整数范围；失败返回 (False, 给模型的错误文案)。"""
    if value is None:
        return True, default
    try:
        v = int(value)
    except (TypeError, ValueError):
        return False, f"参数错误：{name} 必须是整数，收到 {value!r}（范围 {lo}~{hi}）"
    if not (lo <= v <= hi):
        return False, f"参数错误：{name} 需在 {lo}~{hi} 之间，收到 {v}"
    return True, v


def _check_nonempty(name: str, value: Any) -> tuple[bool, str]:
    if value is None or not str(value).strip():
        return False, f"参数错误：{name} 不能为空"
    return True, str(value).strip()


# ---------------------------------------------------------------- 工具工厂

def make_tools(retriever, store) -> list:
    """构建 7 个治理后的工具（顺序稳定：检索类在前，出图在后）。

    与旧 `_make_tools` 同名同序，但：校验失败/外部 API 失败一律返回可读文案，
    由模型自行决定改用其他工具——而不是抛异常打断整单任务。
    """

    @tool
    def search_knowledge(keywords: str, limit: int = 5) -> str:
        """在行业知识库（新闻与财报全文）中检索相关内容（混合召回 + 精排）。

        Args:
            keywords: 空格分隔的中文或英文关键词。
            limit: 返回条数，默认 5，范围 1~10。
        """
        ok, kw = _check_nonempty("keywords", keywords)
        if not ok:
            return kw
        ok, lim = _check_range("limit", limit, 1, 10, 5)
        if not ok:
            return lim
        try:
            hits = retriever.search_reranked(kw, top_k=lim)
        except Exception as e:  # noqa: BLE001 —— 检索异常也回给模型，不炸任务
            return f"（知识库检索失败：{e}，请稍后重试）"
        from agent.evidence import source_level_label

        lines = []
        for doc_id, score in hits:
            doc = retriever.documents[doc_id]
            url = doc.meta.get("url", "")
            lines.append(
                f"[相关度 {score:.2f}] {doc.text[:240]}... "
                f"(来源: {url} [{source_level_label(url)}])"
            )
        return "\n---\n".join(lines) or "（无结果）"

    @tool
    def parallel_search(queries: str, limit: int = 3) -> str:
        """并发检索知识库：一次提交 2~6 条查询，并行执行混合检索+精排并合并返回。

        用于分节写作前批量取材（差距收敛第 2 项：多路查询并发，墙钟时间减半）。
        注意：reranker 为 CPU 推理，并发收益取决于核数；单条查询失败不影响其他条。

        Args:
            queries: JSON 字符串数组，如 ["存储芯片 涨价 2026", "HBM 产能 供需"]（2~6 条）。
            limit: 每条查询返回条数，默认 3，范围 1~5。
        """
        ok, lim = _check_range("limit", limit, 1, 5, 3)
        if not ok:
            return lim
        try:
            qs = json.loads(queries)
        except (json.JSONDecodeError, TypeError):
            return (
                "参数错误：queries 必须是合法 JSON 字符串数组，"
                '如 ["存储芯片 涨价", "HBM 产能"]'
            )
        if not isinstance(qs, list):
            return "参数错误：queries 必须是 JSON 数组"
        qs = [str(q).strip() for q in qs if str(q).strip()]
        if not (2 <= len(qs) <= 6):
            return "参数错误：queries 需为 2~6 条非空查询的 JSON 数组"

        import concurrent.futures as _cf

        def _one(q: str) -> str:
            try:
                hits = retriever.search_reranked(q, top_k=lim)
            except Exception as e:  # noqa: BLE001 —— 单条失败不阻塞整体
                return f"（查询「{q}」失败：{e}）"
            from agent.evidence import source_level_label

            lines = []
            for doc_id, score in hits:
                doc = retriever.documents[doc_id]
                url = doc.meta.get("url", "")
                lines.append(
                    f"[相关度 {score:.2f}] {doc.text[:200]}... "
                    f"(来源: {url} [{source_level_label(url)}])"
                )
            return "\n".join(lines) or "（无结果）"

        with _cf.ThreadPoolExecutor(max_workers=min(4, len(qs))) as ex:
            results = list(ex.map(_one, qs))
        return "\n\n".join(
            f"## 查询「{q}」\n{r}" for q, r in zip(qs, results)
        )

    @tool
    def query_filings(company: str, limit: int = 3) -> str:
        """查询指定公司最近的 SEC 财报披露记录（已入库索引）。

        Args:
            company: 公司名，如 NVIDIA / TSMC / Intel / ASML。
            limit: 返回条数，默认 3，范围 1~10。
        """
        ok, c = _check_nonempty("company", company)
        if not ok:
            return c
        ok, lim = _check_range("limit", limit, 1, 10, 3)
        if not ok:
            return lim
        try:
            rows = store.query_articles(source="SEC_EDGAR", keyword=c, limit=lim)
        except Exception as e:  # noqa: BLE001
            return f"（SEC 索引查询失败：{e}，请稍后重试）"
        return json.dumps(
            [{"title": r["title"], "date": r["published_at"], "url": r["url"]} for r in rows],
            ensure_ascii=False,
        )

    @tool
    def search_arxiv(query: str, max_results: int = 5) -> str:
        """实时检索 arXiv 学术论文（学术调研用）；超时/限流返回降级说明，不影响主流程。

        Args:
            query: 英文检索词或短语，如 "LLM agent" 或 "chip design"。
            max_results: 返回条数，默认 5，范围 1~10。
        """
        ok, q = _check_nonempty("query", query)
        if not ok:
            return q
        ok, mr = _check_range("max_results", max_results, 1, 10, 5)
        if not ok:
            return mr
        from urllib.parse import quote

        url = (
            "https://export.arxiv.org/api/query?"
            f"search_query=all:{quote(q)}&sortBy=relevance&max_results={mr}"
        )
        # arXiv 官方限速 ≥3s/请求；超时 15s；429/5xx 退避；失败降级
        resp, err = external_get(url, timeout=15, sleep_before=3.0, label="arXiv")
        if err:
            return (
                f"（arXiv 暂不可用：{err}。"
                "可改用 search_knowledge / query_filings 获取已入库的行业资料）"
            )
        try:
            import xml.etree.ElementTree as _ET

            ns = {"a": "http://www.w3.org/2005/Atom"}
            root = _ET.fromstring(resp.content)
            lines = []
            for e in root.findall("a:entry", ns):
                title = re.sub(r"\s+", " ", e.findtext("a:title", "", ns)).strip()
                link = e.findtext("a:id", "", ns)
                year = e.findtext("a:published", "", ns)[:4]
                authors = ", ".join(
                    a.findtext("a:name", "", ns) for a in e.findall("a:author", ns)[:4]
                )
                summary = re.sub(r"\s+", " ", e.findtext("a:summary", "", ns)).strip()[:400]
                lines.append(f"[{title}] ({authors}, {year}) {link}\n摘要: {summary}")
            return "\n---\n".join(lines) or "（无结果）"
        except Exception as e:  # noqa: BLE001
            return f"（arXiv 返回解析失败：{e}，可改用 search_knowledge）"

    @tool
    def generate_chart(chart_type: str, data: str, title: str) -> str:
        """生成统计图表 PNG 并返回 Markdown 图片引用（用于在报告中嵌入可视化）。

        Args:
            chart_type: 图表类型，可选 bar（柱状）/ line（折线）/ pie（饼图）。
            data: JSON 字符串，形如 [{"label":"Q1","value":88}, ...]。
            title: 图表标题。
        """
        if chart_type not in ("bar", "line", "pie"):
            return f"参数错误：chart_type 只能是 bar/line/pie，收到 {chart_type!r}"
        ok, t = _check_nonempty("title", title)
        if not ok:
            return t
        try:
            rows = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return "参数错误：data 必须是合法 JSON 数组字符串，如 [{\"label\":\"Q1\",\"value\":88}]"
        if not isinstance(rows, list) or not rows:
            return "参数错误：data 必须是至少含一行的 JSON 数组"
        try:
            labels = [str(r.get("label", "")) for r in rows]
            values = [float(r.get("value", 0)) for r in rows]
        except (AttributeError, TypeError, ValueError):
            return "参数错误：data 每行需含 label（字符串）与 value（数字）字段"

        import uuid as _uuid

        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as _plt

        _plt.rcParams["font.sans-serif"] = [
            "Microsoft YaHei",
            "SimHei",
            "Arial Unicode MS",
            "DejaVu Sans",
        ]
        _plt.rcParams["axes.unicode_minus"] = False

        try:
            fig, ax = _plt.subplots(figsize=(8, 4))
            if chart_type == "bar":
                ax.bar(labels, values)
            elif chart_type == "line":
                ax.plot(labels, values, marker="o")
            else:
                ax.pie(values, labels=labels, autopct="%1.1f%%")
            ax.set_title(t)
            _plt.tight_layout()

            out_dir = settings.CHART_DIR
            out_dir.mkdir(parents=True, exist_ok=True)
            fname = f"{_uuid.uuid4().hex[:10]}.png"
            _plt.savefig(out_dir / fname, dpi=120)
            return f"![{t}](/charts/{fname})"
        except Exception as e:  # noqa: BLE001
            return f"（图表生成失败：{e}）"
        finally:
            _plt.close(fig)  # type: ignore[possibly-undefined]

    @tool
    def search_semantic_scholar(query: str, limit: int = 5) -> str:
        """检索学术论文并返回被引次数（引文影响力，学术调研用）；限流自动退避重试。

        Args:
            query: 英文检索词或短语，如 "LLM agent"。
            limit: 返回条数，默认 5，范围 1~10。
        """
        ok, q = _check_nonempty("query", query)
        if not ok:
            return q
        ok, lim = _check_range("limit", limit, 1, 10, 5)
        if not ok:
            return lim
        params = {"query": q, "limit": lim, "fields": "title,year,citationCount,abstract,url"}
        headers = {}
        if settings.SEMANTIC_SCHOLAR_API_KEY:
            headers["x-api-key"] = settings.SEMANTIC_SCHOLAR_API_KEY
        # 匿名额度易触发 429：退避重试 3 次后降级
        resp, err = external_get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params=params,
            headers=headers,
            timeout=15,
            max_attempts=3,
            backoff_base=4.0,
            label="Semantic Scholar",
        )
        if err:
            return (
                f"（Semantic Scholar 暂不可用：{err}。"
                "可改用 search_arxiv 或 search_knowledge 获取资料）"
            )
        try:
            papers = resp.json().get("data", [])
            lines = []
            for p in papers:
                lines.append(
                    f"[{p.get('title')}] ({p.get('year')}) 被引 {p.get('citationCount')} 次 "
                    f"{p.get('url', '')}\n摘要: {(p.get('abstract') or '')[:300]}"
                )
            return "\n---\n".join(lines) or "（无结果）"
        except Exception as e:  # noqa: BLE001
            return f"（Semantic Scholar 返回解析失败：{e}，可改用 search_arxiv）"

    @tool
    def search_graph(entity: str) -> str:
        """查询实体共现图：返回与某实体相关的实体及共现强度；传空字符串返回全局核心实体。

        Args:
            entity: 实体名，如 "台积电" / "HBM" / "RAG"；传 "" 查全局核心实体。
        """
        graph = getattr(retriever, "graph", None)
        if graph is None:
            return "（知识图谱未构建）"
        if not entity or not entity.strip():
            top = graph.centrality(15)
            return "全局核心实体（按关联度）：\n" + "\n".join(f"- {e}（{w}）" for e, w in top)
        ents = graph.related_entities(entity.strip(), 10)
        if not ents:
            return f"（图谱中未找到与「{entity}」相关的实体）"
        return f"「{entity}」的关联实体（按共现强度）：\n" + "\n".join(
            f"- {e}（共现 {w}）" for e, w in ents
        )

    @tool
    def search_pubmed(query: str, limit: int = 5) -> str:
        """实时检索 PubMed 生物医药文献（含摘要）；异常返回降级说明，不中断任务。

        Args:
            query: 英文检索词，如 "cancer immunotherapy"。
            limit: 返回条数，默认 5，范围 1~10。
        """
        ok, q = _check_nonempty("query", query)
        if not ok:
            return q
        ok, lim = _check_range("limit", limit, 1, 10, 5)
        if not ok:
            return lim
        try:
            from data.collectors.pubmed import search_pubmed as _pubmed

            papers = _pubmed(q, lim)
        except Exception as e:  # noqa: BLE001
            return f"（PubMed 暂不可用：{type(e).__name__}: {e}。可改用 search_knowledge）"
        lines = []
        for p in papers:
            lines.append(
                f"[{p['title']}] ({p['journal']}, {p['pubdate']}) {p['url']}\n"
                f"作者: {', '.join(p['authors'][:4])}\n摘要: {p['abstract'][:300]}"
            )
        return "\n---\n".join(lines) or "（无结果）"

    return [
        search_knowledge,
        parallel_search,
        query_filings,
        search_arxiv,
        search_semantic_scholar,
        generate_chart,
        search_graph,
        search_pubmed,
    ]
