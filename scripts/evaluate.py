"""评测入口：python scripts/evaluate.py [--retrieval-only | --full]"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]

from agent.eval import evaluate_full, evaluate_retrieval, load_golden_set  # noqa: E402
from agent.knowledge.loader import build_retriever  # noqa: E402
from backend.app.core import settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 评测")
    parser.add_argument("--retrieval-only", action="store_true", help="仅检索指标（无 LLM，CI 用）")
    parser.add_argument("--full", action="store_true", help="检索 + LLM-as-judge 质量指标")
    parser.add_argument("--mini", action="store_true", help="用 mini 语料 + 内存检索器（CI 自包含，无 DB/模型）")
    args = parser.parse_args()

    cases = load_golden_set(ROOT / "data" / "eval" / "golden_set.json")
    print(f"加载黄金集：{len(cases)} 条")

    if args.mini:
        from agent.eval import build_mini_retriever, evaluate_retrieval

        docs = json.loads((ROOT / "data" / "eval" / "mini_corpus.json").read_text(encoding="utf-8"))
        retriever = build_mini_retriever(docs)
        report = {"retrieval": evaluate_retrieval(retriever, cases)}
    else:
        print("构建知识库索引...")
        retriever = build_retriever(settings.ARTICLES_DB, settings.VECTOR_DIR, settings.MODEL_DIR)

        if args.full:
            from openai import OpenAI

            client = OpenAI(base_url=settings.LLM_BASE_URL, api_key=settings.LLM_API_KEY)
            client.model_id = settings.LLM_MODEL

            from agent.orchestrator import ReportPipeline
            from data.storage import SQLiteStore

            store = SQLiteStore(settings.ARTICLES_DB)
            try:
                pipeline = ReportPipeline(retriever, store)
                answer_fn = lambda q: pipeline.answer_question(q)["answer"]  # noqa: E731
                report = evaluate_full(retriever, cases, answer_fn, client=client)
            finally:
                store.close()
        else:
            report = {"retrieval": evaluate_retrieval(retriever, cases)}

    out = ROOT / "spikes" / "results" / "eval_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n结果已保存 -> {out}")


if __name__ == "__main__":
    main()
