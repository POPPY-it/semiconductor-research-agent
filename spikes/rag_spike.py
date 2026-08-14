"""W2 预研：RAG 检索链路实测（BM25 vs 向量 vs 混合）+ Recall@k / MRR 评测。

数据：data/raw/ 真实采集样本（Google News + IT之家新闻 13 条，SEC EDGAR 财报披露 32 条）。
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.knowledge.embedder import FastembedEmbedder  # noqa: E402
from agent.knowledge.retriever import Document, HybridRetriever  # noqa: E402
from agent.knowledge.store import ChromaStore  # noqa: E402

VECTOR_DIR = ROOT / "data" / "vectorstore" / "spike"


def load_documents() -> list[Document]:
    docs: list[Document] = []
    news = json.loads((ROOT / "data" / "raw" / "news_sample.json").read_text(encoding="utf-8"))
    for item in news.get("google_news", []) + news.get("ithome", []):
        text = f"{item.get('source', '')}新闻：{item.get('title', '')}（发布于 {item.get('pub_date', '')}）"
        docs.append(
            Document(doc_id=f"news-{len(docs)}", text=text, meta={"type": "news", **item})
        )
    filings = json.loads((ROOT / "data" / "raw" / "sec_edgar_sample.json").read_text(encoding="utf-8"))
    for item in filings.get("filings", []):
        text = (
            f"{item['company']} 向美国证监会提交 {item['form']}，"
            f"报告期 {item['report_date']}，提交日期 {item['filing_date']}。"
        )
        docs.append(
            Document(doc_id=f"filing-{len(docs)}", text=text, meta={"type": "filing", **item})
        )
    return docs


# 评测集：查询 → 相关文档需包含的关键词（粗粒度标注，用于链路级评测）
EVAL = [
    ("台积电 2nm 产能进展如何", ["台积电"]),
    ("NVIDIA 最近提交了哪些财报", ["NVIDIA"]),
    ("存储芯片价格走势", ["存储"]),
    ("SEMI 对设备支出的最新预期", ["SEMI"]),
    ("ASML 的财报披露", ["ASML"]),
]


def relevant_set(docs: list[Document], keywords: list[str]) -> set[str]:
    return {
        d.doc_id for d in docs if any(k in d.text for k in keywords)
    }


def evaluate(name: str, search_fn, docs: list[Document], top_k: int = 5) -> dict:
    recalls, mrrs, lat = [], [], []
    for query, keywords in EVAL:
        rel = relevant_set(docs, keywords)
        t0 = time.perf_counter()
        hits = search_fn(query, top_k)
        lat.append((time.perf_counter() - t0) * 1000)
        hit_ids = [h[0] for h in hits]
        inter = set(hit_ids) & rel
        recalls.append(len(inter) / len(rel) if rel else 0.0)
        rank = next((i + 1 for i, h in enumerate(hit_ids) if h in rel), None)
        mrrs.append(1.0 / rank if rank else 0.0)
    return {
        "name": name,
        "recall@5_mean": round(sum(recalls) / len(recalls), 3),
        "mrr_mean": round(sum(mrrs) / len(mrrs), 3),
        "latency_ms_mean": round(sum(lat) / len(lat), 1),
        "per_query": [
            {"query": q, "recall@5": round(r, 3), "mrr": round(m, 3), "latency_ms": round(l, 1)}
            for (q, _), r, m, l in zip(EVAL, recalls, mrrs, lat)
        ],
    }


def main() -> None:
    docs = load_documents()
    print(f"文档数: {len(docs)}")

    t0 = time.perf_counter()
    embedder = FastembedEmbedder(cache_dir=str(ROOT / "data" / "models"))
    store = ChromaStore(VECTOR_DIR)
    retriever = HybridRetriever(docs, embedder, store)
    retriever.index()
    print(f"索引耗时: {time.perf_counter() - t0:.1f}s（含首次模型下载）")

    results = [
        evaluate("BM25-only", retriever.search_bm25, docs),
        evaluate("Vector-only", retriever.search_vector, docs),
        evaluate("Hybrid-RRF", retriever.search_hybrid, docs),
    ]

    print("\n=== 评测结果 ===")
    for r in results:
        print(
            f"{r['name']:14s} recall@5={r['recall@5_mean']}  mrr={r['mrr_mean']}  "
            f"avg_latency={r['latency_ms_mean']}ms"
        )
    print("\n=== 分查询明细（Hybrid） ===")
    for row in results[-1]["per_query"]:
        print(row)

    out = ROOT / "spikes" / "results" / "rag_eval.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已保存 -> {out}")


if __name__ == "__main__":
    main()
