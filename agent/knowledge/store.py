"""向量库抽象：Chroma 实现（持久化本地目录）。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class VectorHit:
    doc_id: str
    score: float  # 余弦相似度（Chroma 返回的 distance 语义取决于配置，这里统一为"越大越相关"）


class VectorStore(ABC):
    @abstractmethod
    def add(self, ids: list[str], documents: list[str], embeddings: list[list[float]]) -> None: ...

    @abstractmethod
    def search(self, query_embedding: list[float], top_k: int = 10) -> list[VectorHit]: ...


class ChromaStore(VectorStore):
    def __init__(self, persist_dir: str | Path, collection: str = "semiconductor_docs"):
        import chromadb  # 延迟导入

        Path(persist_dir).mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        self._collection = self._client.get_or_create_collection(
            name=collection, metadata={"hnsw:space": "cosine"}
        )

    def add(self, ids: list[str], documents: list[str], embeddings: list[list[float]]) -> None:
        self._collection.add(ids=ids, documents=documents, embeddings=embeddings)

    def search(self, query_embedding: list[float], top_k: int = 10) -> list[VectorHit]:
        res = self._collection.query(query_embeddings=[query_embedding], n_results=top_k)
        ids = res["ids"][0]
        dists = res["distances"][0]
        return [
            VectorHit(doc_id=str(doc_id), score=1.0 - float(dist))
            for doc_id, dist in zip(ids, dists)
        ]
