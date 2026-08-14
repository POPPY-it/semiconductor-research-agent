"""切分与加权检索的单元测试（无网络、无模型）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.knowledge.chunker import chunk_text  # noqa: E402
from agent.knowledge.retriever import Document, HybridRetriever  # noqa: E402
from tests.test_knowledge import FakeEmbedder, FakeStore  # noqa: E402


def test_chunk_text_basic():
    text = "句子一，比较长。" * 30
    chunks = chunk_text(text, chunk_size=100, overlap=20)
    assert len(chunks) > 1
    assert all(len(c) <= 120 for c in chunks)  # 允许轻微超限（句子粒度）
    joined = "".join(chunks)
    assert "句子一" in joined


def test_chunk_text_short_doc_single_chunk():
    assert chunk_text("短文本") == ["短文本"]


def test_weighted_rrf_prefers_bm25_signal():
    docs = [
        Document(doc_id="a", text="台积电 2nm 产能爬坡超预期"),
        Document(doc_id="b", text="台积电宣布 2nm 进展，产能爬坡计划公布"),
        Document(doc_id="c", text="存储芯片价格连续上涨"),
    ]
    uniform = HybridRetriever(docs, FakeEmbedder(), FakeStore(), bm25_weight=0.5, vector_weight=0.5)
    weighted = HybridRetriever(docs, FakeEmbedder(), FakeStore(), bm25_weight=0.9, vector_weight=0.1)
    # 词法高度匹配时，加权版更坚定地把 a 排第一
    assert uniform.search_hybrid("2nm 产能", top_k=1)[0][0] == "a"
    assert weighted.search_hybrid("2nm 产能", top_k=1)[0][0] == "a"
    assert len(weighted.search_hybrid("2nm", top_k=3)) == 3


def test_reranked_fallback_without_reranker():
    docs = [Document(doc_id="a", text="台积电 2nm 产能")]
    r = HybridRetriever(docs, FakeEmbedder(), FakeStore(), reranker=None)
    hits = r.search_reranked("2nm", top_k=1)
    assert hits[0][0] == "a"
