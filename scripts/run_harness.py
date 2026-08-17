"""Harness 入口：python scripts/run_harness.py [--limit N]

跑 eval/tasks.json 任务集，产出 eval/results_latest.json + eval/metrics.md。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.harness import load_tasks, run_harness  # noqa: E402
from agent.knowledge.loader import build_retriever  # noqa: E402
from agent.orchestrator import ReportPipeline  # noqa: E402
from backend.app.core import settings  # noqa: E402
from data.storage import SQLiteStore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent 级评测 Harness")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 条（验证用）")
    args = parser.parse_args()

    tasks = load_tasks()
    print(f"加载任务集：{len(tasks)} 条" + (f"，本次只跑前 {args.limit} 条" if args.limit else ""))

    print("构建知识库索引...")
    retriever = build_retriever(settings.ARTICLES_DB, settings.VECTOR_DIR, settings.MODEL_DIR)
    store = SQLiteStore(settings.ARTICLES_DB)
    try:
        pipeline = ReportPipeline(retriever, store)
        run_harness(pipeline, tasks, limit=args.limit)
    finally:
        store.close()


if __name__ == "__main__":
    main()
