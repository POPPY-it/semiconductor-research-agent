"""混合检索：BM25（字符 bigram 分词）+ 向量余弦 + RRF 融合。

jieba 在当前 Python 3.10 环境构建失败（老包无 wheel），改用零依赖的
字符 bigram 分词：ASCII 词整体保留 + 汉字按相邻二字组切分。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from rank_bm25 import BM25Okapi

from .embedder import Embedder
from .store import VectorStore


@dataclass
class Document:
    doc_id: str
    text: str
    meta: dict = field(default_factory=dict)


def char_bigram_tokenize(text: str) -> list[str]:
    """中文友好的零依赖分词：ASCII 词整体保留 + 汉字字符 bigram。"""
    tokens: list[str] = []
    buf = ""

    def flush() -> None:
        nonlocal buf
        if buf:
            tokens.append(buf.lower())
            buf = ""

    for ch in text:
        if ch.isalnum() and ord(ch) < 128:
            buf += ch
        else:
            flush()
    flush()

    han = [ch for ch in text if "\u4e00" <= ch <= "\u9fff"]
    if len(han) == 1:
        tokens += han
    else:
        tokens += [han[i] + han[i + 1] for i in range(len(han) - 1)]
    return tokens or ["<empty>"]


class HybridRetriever:
    """对一批文档建立 BM25 与向量双索引，支持多模式检索与重排。

    W4 升级：加权 RRF（W2 实测等权融合稀释 BM25 信号）+ 可选 reranker 精排。
    """

    def __init__(
        self,
        documents: list[Document],
        embedder: Embedder,
        store: VectorStore,
        rrf_k: int = 60,
        bm25_weight: float = 0.7,
        vector_weight: float = 0.3,
        reranker=None,
    ):
        self.documents = {d.doc_id: d for d in documents}
        self.embedder = embedder
        self.store = store
        self.rrf_k = rrf_k
        self.bm25_weight = bm25_weight
        self.vector_weight = vector_weight
        self.reranker = reranker
        self._bm25: BM25Okapi | None = None
        self._indexed = False

    def index(self) -> None:
        if self._indexed:
            return
        docs = list(self.documents.values())
        self._bm25 = BM25Okapi([char_bigram_tokenize(d.text) for d in docs])
        embeddings = self.embedder.embed([d.text for d in docs])
        self.store.add(
            [d.doc_id for d in docs], [d.text for d in docs], embeddings
        )
        self._indexed = True

    def search_bm25(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        self.index()
        scores = self._bm25.get_scores(char_bigram_tokenize(query))
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        docs = list(self.documents.values())
        return [(docs[i].doc_id, float(scores[i])) for i in order]

    def search_vector(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        self.index()
        qv = self.embedder.embed([query])[0]
        hits = self.store.search(qv, top_k)
        return [(h.doc_id, h.score) for h in hits]

    def search_hybrid(
        self, query: str, top_k: int = 10, candidates: int = 50
    ) -> list[tuple[str, float]]:
        """加权 RRF 融合：默认 BM25 0.7 / 向量 0.3（W2 实测结论）。"""
        bm25 = self.search_bm25(query, top_k=candidates)
        vec = self.search_vector(query, top_k=candidates)
        rrf: dict[str, float] = {}
        for rank, (doc_id, _score) in enumerate(bm25):
            rrf[doc_id] = rrf.get(doc_id, 0.0) + self.bm25_weight / (self.rrf_k + rank + 1)
        for rank, (doc_id, _score) in enumerate(vec):
            rrf[doc_id] = rrf.get(doc_id, 0.0) + self.vector_weight / (self.rrf_k + rank + 1)
        return sorted(rrf.items(), key=lambda kv: kv[1], reverse=True)[:top_k]

    def search_reranked(
        self, query: str, top_k: int = 10, candidates: int = 30
    ) -> list[tuple[str, float]]:
        """混合召回 + cross-encoder 精排。"""
        if self.reranker is None:
            return self.search_hybrid(query, top_k)
        cands = self.search_hybrid(query, top_k=candidates)
        texts = [self.documents[doc_id].text for doc_id, _ in cands]
        scores = self.reranker.rerank(query, texts)
        ranked = sorted(zip([d for d, _ in cands], scores), key=lambda kv: kv[1], reverse=True)
        return [(doc_id, float(s)) for doc_id, s in ranked[:top_k]]
