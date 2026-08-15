"""RAG 评测（对标 RAGAS）：检索指标（无 LLM，可进 CI）+ LLM-as-judge 质量指标。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

# 检索指标（纯计算，无 LLM，CI 安全）
def evaluate_retrieval(retriever, cases: list[dict], k: int = 5) -> dict:
    recalls, mrrs, precisions = [], [], []
    per_case = []
    for c in cases:
        hits = retriever.search_hybrid(c["question"], top_k=k)
        hit_ids = [h[0] for h in hits]
        rel = {
            doc_id
            for doc_id, doc in retriever.documents.items()
            if any(kw.lower() in doc.text.lower() for kw in c["keywords"])
        }
        hit_rel = [i for i in hit_ids if i in rel]
        recall = len(hit_rel) / len(rel) if rel else 1.0
        mrr = 0.0
        for rank, i in enumerate(hit_ids, 1):
            if i in rel:
                mrr = 1.0 / rank
                break
        precision = len(hit_rel) / len(hit_ids) if hit_ids else 0.0
        recalls.append(recall)
        mrrs.append(mrr)
        precisions.append(precision)
        per_case.append({"question": c["question"], "recall": round(recall, 3), "mrr": round(mrr, 3)})
    return {
        "k": k,
        "n": len(cases),
        "recall_mean": round(sum(recalls) / len(recalls), 3) if recalls else 0.0,
        "mrr_mean": round(sum(mrrs) / len(mrrs), 3) if mrrs else 0.0,
        "precision_mean": round(sum(precisions) / len(precisions), 3) if precisions else 0.0,
        "per_case": per_case,
    }


def _judge(client, prompt: str) -> float:
    """LLM-as-judge：让模型输出 0~1 分数。"""
    resp = client.chat.completions.create(
        model=client.model_id,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=20,
    )
    text = resp.choices[0].message.content.strip()
    try:
        return max(0.0, min(1.0, float(text)))
    except ValueError:
        # 尝试从文本中提取数字
        import re

        m = re.search(r"0?\.\d+|1(?:\.0)?|[01]", text)
        return float(m.group(0)) if m else 0.0


def judge_faithfulness(client, question: str, answer: str, context: str) -> float:
    prompt = (
        "你是事实一致性评审。给定检索到的上下文，判断回答中的每个事实性陈述是否都被上下文支持。\n\n"
        f"【问题】{question}\n\n【检索上下文】{context[:3000]}\n\n【回答】{answer[:2000]}\n\n"
        "只输出一个 0~1 之间的小数（1=完全支持，0=完全无支持）。"
    )
    return _judge(client, prompt)


def judge_answer_relevance(client, question: str, answer: str) -> float:
    prompt = (
        "你是回答相关性评审。判断回答是否直接、完整地回应了问题。\n\n"
        f"【问题】{question}\n\n【回答】{answer[:2000]}\n\n"
        "只输出一个 0~1 之间的小数（1=完全相关，0=完全跑题）。"
    )
    return _judge(client, prompt)


def load_golden_set(path: str | Path) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---- CI 自包含模式：内存检索器（无 DB、无模型下载）----
def build_mini_retriever(docs: list[dict]):
    """用确定性假 Embedder + 内存向量库构建检索器，供 CI 评测回归。"""
    from agent.knowledge.retriever import Document, HybridRetriever

    class _Embedder:
        def embed(self, texts):
            out = []
            for t in texts:
                vec = [0.0] * 64
                for ch in t:
                    vec[ord(ch) % 64] += 1.0
                norm = sum(x * x for x in vec) ** 0.5 or 1.0
                out.append([x / norm for x in vec])
            return out

    class _Store:
        def __init__(self):
            self.ids, self.vecs = [], []

        def add(self, ids, documents, embeddings):
            self.ids, self.vecs = ids, embeddings

        def search(self, qv, top_k=5):
            from agent.knowledge.store import VectorHit

            def cos(a, b):
                dot = sum(x * y for x, y in zip(a, b))
                na = sum(x * x for x in a) ** 0.5
                nb = sum(y * y for y in b) ** 0.5
                return dot / (na * nb) if na and nb else 0.0

            ranked = sorted(
                ((i, cos(qv, v)) for i, v in enumerate(self.vecs)),
                key=lambda kv: kv[1],
                reverse=True,
            )[:top_k]
            return [VectorHit(doc_id=self.ids[i], score=s) for i, s in ranked]

    documents = [
        Document(doc_id=f"d{i}", text=d["title"] + "\n" + d["content"], meta={})
        for i, d in enumerate(docs)
    ]
    return HybridRetriever(documents, _Embedder(), _Store())


def evaluate_full(
    retriever,
    cases: list[dict],
    answer_fn: Callable[[str], str],
    client=None,
) -> dict:
    """检索指标 + （若提供 client）LLM 质量指标。"""
    report = {"retrieval": evaluate_retrieval(retriever, cases)}
    if client is not None:
        faith, rels = [], []
        per_case = []
        for c in cases:
            answer = answer_fn(c["question"])
            context = "\n".join(
                retriever.documents[h[0]].text[:400]
                for h in retriever.search_hybrid(c["question"], top_k=3)
            )
            f = judge_faithfulness(client, c["question"], answer, context)
            r = judge_answer_relevance(client, c["question"], answer)
            faith.append(f)
            rels.append(r)
            per_case.append({"question": c["question"], "faithfulness": round(f, 2), "relevance": round(r, 2)})
        report["llm_judge"] = {
            "faithfulness_mean": round(sum(faith) / len(faith), 3),
            "answer_relevance_mean": round(sum(rels) / len(rels), 3),
            "per_case": per_case,
        }
    return report
