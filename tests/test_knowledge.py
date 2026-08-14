"""知识层单元测试：分词、检索（用假 Embedder，无网络/模型依赖）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.knowledge.embedder import Embedder  # noqa: E402
from agent.knowledge.retriever import (  # noqa: E402
    Document,
    HybridRetriever,
    char_bigram_tokenize,
)
from agent.knowledge.store import VectorStore, VectorHit  # noqa: E402


class FakeStore(VectorStore):
    """内存向量库：按余弦相似度暴力检索（无 chromadb 依赖）。"""

    def __init__(self):
        self._ids: list[str] = []
        self._vecs: list[list[float]] = []

    def add(self, ids, documents, embeddings) -> None:
        self._ids = ids
        self._vecs = embeddings

    def search(self, query_embedding, top_k=10) -> list[VectorHit]:
        def cos(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            na = sum(x * x for x in a) ** 0.5
            nb = sum(y * y for y in b) ** 0.5
            return dot / (na * nb) if na and nb else 0.0

        ranked = sorted(
            ((i, cos(query_embedding, v)) for i, v in enumerate(self._vecs)),
            key=lambda kv: kv[1],
            reverse=True,
        )[:top_k]
        return [VectorHit(doc_id=self._ids[i], score=s) for i, s in ranked]


class FakeEmbedder(Embedder):
    """确定性假 Embedder：给每个文档一个可分离的稀疏向量。"""

    def __init__(self, dim: int = 32):
        self._dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            vec = [0.0] * self._dim
            for ch in t:
                vec[ord(ch) % self._dim] += 1.0
            norm = sum(x * x for x in vec) ** 0.5 or 1.0
            out.append([x / norm for x in vec])
        return out

    @property
    def dim(self) -> int:
        return self._dim


def test_char_bigram_tokenize():
    tokens = char_bigram_tokenize("台积电 2nm 产能")
    assert "台积" in tokens and "积电" in tokens
    assert "2nm" in tokens  # ASCII 词整体保留


def test_hybrid_retriever_returns_results():
    docs = [
        Document(doc_id="a", text="台积电 2nm 产能爬坡超预期"),
        Document(doc_id="b", text="存储芯片价格连续上涨"),
        Document(doc_id="c", text="NVIDIA 提交了 10-Q 财报"),
    ]
    retriever = HybridRetriever(docs, FakeEmbedder(), FakeStore())
    hits = retriever.search_hybrid("台积电 2nm 进展", top_k=3)
    assert len(hits) == 3
    assert hits[0][0] == "a"  # 词法+向量都最相关


def test_search_modes_agree_on_top1():
    docs = [
        Document(doc_id="a", text="台积电 2nm 产能爬坡超预期"),
        Document(doc_id="b", text="存储芯片价格连续上涨"),
    ]
    retriever = HybridRetriever(docs, FakeEmbedder(), FakeStore())
    assert retriever.search_bm25("台积电 2nm", top_k=1)[0][0] == "a"
    assert retriever.search_vector("台积电 2nm", top_k=1)[0][0] == "a"
