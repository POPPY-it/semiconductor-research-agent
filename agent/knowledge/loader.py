"""知识库构建：从 SQLite 文章库加载文档 → 分块 → 构建混合检索器。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.knowledge.chunker import chunk_text  # noqa: E402
from agent.knowledge.embedder import FastembedEmbedder  # noqa: E402
from agent.knowledge.reranker import FastembedReranker  # noqa: E402
from agent.knowledge.retriever import Document, HybridRetriever  # noqa: E402
from agent.knowledge.store import ChromaStore  # noqa: E402
from data.storage import SQLiteStore  # noqa: E402


def build_retriever(
    db_path: str | Path,
    vector_dir: str | Path,
    model_dir: str | Path,
    with_reranker: bool = True,
    reset: bool = False,
) -> HybridRetriever:
    """从文章库构建检索器（含分块索引；首次调用会下载 embedding 模型）。"""
    store = SQLiteStore(db_path)
    try:
        articles = store.query_articles(limit=1000)
    finally:
        store.close()

    docs: list[Document] = []
    for i, art in enumerate(articles):
        text = art["title"] + ("\n" + art["content"] if art["content"] else "")
        chunks = chunk_text(text) if art["content"] else [text]
        for j, ch in enumerate(chunks):
            docs.append(
                Document(
                    doc_id=f"art{i}-c{j}",
                    text=ch,
                    meta={"url": art["url"], "source": art["source"], "title": art["title"]},
                )
            )

    embedder = FastembedEmbedder(cache_dir=str(model_dir))
    chroma = ChromaStore(vector_dir, collection="main")
    if reset:
        chroma.reset()  # 重建索引：清空旧集合，避免 doc_id 冲突
    reranker = FastembedReranker(cache_dir=str(model_dir)) if with_reranker else None
    retriever = HybridRetriever(docs, embedder, chroma, reranker=reranker)
    retriever.index()
    return retriever
