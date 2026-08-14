"""RAG 评测 v2：长文档语料（29 篇 SEC 财报全文 + 2 篇新闻正文）上的 5 路对比。

- 切分：chunk_text(500, overlap=100)
- 对比：BM25 / 向量 / 等权RRF / 加权RRF / 加权RRF+reranker
- 指标：Recall@5、MRR、延迟
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.knowledge.chunker import chunk_text  # noqa: E402
from agent.knowledge.embedder import FastembedEmbedder  # noqa: E402
from agent.knowledge.reranker import FastembedReranker  # noqa: E402
from agent.knowledge.retriever import Document, HybridRetriever  # noqa: E402
from agent.knowledge.store import ChromaStore  # noqa: E402
from data.storage import SQLiteStore  # noqa: E402

DB = ROOT / "data" / "articles.db"
VECTOR_DIR = ROOT / "data" / "vectorstore" / "v2"
MODEL_DIR = ROOT / "data" / "models"


def load_chunk_documents() -> tuple[list[Document], dict[str, str]]:
    """返回 (chunk 文档列表, chunk_id -> 文章 id 映射)。"""
    store = SQLiteStore(DB)
    try:
        articles = store.query_articles(limit=500)
    finally:
        store.close()

    docs: list[Document] = []
    chunk2article: dict[str, str] = {}
    for i, art in enumerate(articles):
        if not art["content"]:
            continue
        text = art["title"] + "\n" + art["content"]
        chunks = chunk_text(text)
        for j, ch in enumerate(chunks):
            cid = f"art{i}-c{j}"
            docs.append(
                Document(doc_id=cid, text=ch, meta={"url": art["url"], "source": art["source"]})
            )
            chunk2article[cid] = str(i)
    return docs, chunk2article


# 查询 → 文章级关键词（命中标题或正文的文章视为相关）
EVAL = [
    ("NVIDIA 数据中心业务表现如何", ["NVIDIA", "Data Center"]),
    ("台积电 2nm 制程进展", ["TAIWAN SEMICONDUCTOR", "2nm", "台积电"]),
    ("ASML EUV 光刻机业务", ["ASML", "EUV"]),
    ("Intel 资本开支与代工业务", ["INTEL", "Intel"]),
    ("存储芯片价格走势", ["DRAM", "存储"]),
    ("半导体设备支出预期", ["SEMI", "设备"]),
    ("英伟达的股票回购计划", ["NVIDIA", "repurchase", "回购"]),
    ("晶圆代工产能利用率", ["capacity utilization", "产能"]),
]


def relevant_articles(docs_by_article: dict[str, list[str]], keywords: list[str]) -> set[str]:
    return {aid for aid, chunks in docs_by_article.items() if any(k in " ".join(chunks[:3]) for k in keywords)}


def build_article_index(docs: list[Document], chunk2article: dict[str, str]) -> dict[str, list[str]]:
    """article id -> 该文章的前几个分块文本（用于相关性标注匹配）。"""
    by_art: dict[str, list[str]] = {}
    for d in docs:
        by_art.setdefault(chunk2article[d.doc_id], []).append(d.text)
    return by_art


def evaluate(name, search_fn, docs, by_art, chunk2article, top_k=5):
    search_fn("预热查询", top_k)  # 预热：排除一次性索引/模型初始化成本
    recalls, mrrs, lat = [], [], []
    for query, keywords in EVAL:
        rel_arts = relevant_articles(by_art, keywords)
        if not rel_arts:
            continue
        t0 = time.perf_counter()
        hits = search_fn(query, top_k)
        lat.append((time.perf_counter() - t0) * 1000)
        hit_arts = {a for did, _ in hits for a in [chunk2article.get(did)] if a in rel_arts}
        recalls.append(len(hit_arts) / len(rel_arts))
        hit_ids = [did for did, _ in hits]
        rank = next(
            (i + 1 for i, did in enumerate(hit_ids) if chunk2article.get(did) in rel_arts), None
        )
        mrrs.append(1.0 / rank if rank else 0.0)
    n = len(recalls)
    return {
        "name": name,
        "queries": n,
        "recall@5_mean": round(sum(recalls) / n, 3),
        "mrr_mean": round(sum(mrrs) / n, 3),
        "latency_ms_mean": round(sum(lat) / n, 1),
    }


def main() -> None:
    docs, chunk2article = load_chunk_documents()
    by_art = build_article_index(docs, chunk2article)
    print(f"文章数: {len(by_art)}，分块总数: {len(docs)}")

    t0 = time.perf_counter()
    embedder = FastembedEmbedder(cache_dir=str(MODEL_DIR))
    print(f"embedder 加载: {time.perf_counter()-t0:.1f}s")

    def make_retriever(store, weights=None, reranker=None):
        return HybridRetriever(
            docs,
            embedder,
            store,
            bm25_weight=(weights[0] if weights else 0.5),
            vector_weight=(weights[1] if weights else 0.5),
            reranker=reranker,
        )

    results = []
    store_bm = ChromaStore(VECTOR_DIR, collection="v2_bm25")
    r_bm = make_retriever(store_bm, (1.0, 0.0))
    results.append(evaluate("BM25-only", r_bm.search_bm25, docs, by_art, chunk2article))

    store_vec = ChromaStore(VECTOR_DIR, collection="v2_vec")
    r_vec = make_retriever(store_vec, (0.0, 1.0))
    results.append(evaluate("Vector-only", r_vec.search_vector, docs, by_art, chunk2article))

    store_u = ChromaStore(VECTOR_DIR, collection="v2_uniform")
    r_u = make_retriever(store_u, (0.5, 0.5))
    results.append(evaluate("RRF-uniform", r_u.search_hybrid, docs, by_art, chunk2article))

    store_w = ChromaStore(VECTOR_DIR, collection="v2_weighted")
    r_w = make_retriever(store_w, (0.7, 0.3))
    results.append(evaluate("RRF-weighted(0.7/0.3)", r_w.search_hybrid, docs, by_art, chunk2article))

    t0 = time.perf_counter()
    reranker = FastembedReranker(cache_dir=str(MODEL_DIR))
    print(f"reranker 加载: {time.perf_counter()-t0:.1f}s")
    r_r = make_retriever(store_w, (0.7, 0.3), reranker)
    results.append(evaluate("RRF+reranker", r_r.search_reranked, docs, by_art, chunk2article))

    print("\n=== 评测结果 v2 ===")
    for r in results:
        print(
            f"{r['name']:22s} recall@5={r['recall@5_mean']}  mrr={r['mrr_mean']}  "
            f"avg_latency={r['latency_ms_mean']}ms  (queries={r['queries']})"
        )

    out = ROOT / "spikes" / "results" / "rag_eval_v2.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已保存 -> {out}")


if __name__ == "__main__":
    main()
