"""Harness 入口：python scripts/run_harness.py [--limit N] [--ids t01,t02]

跑 eval/tasks.json 任务集，产出 eval/results_latest.json + eval/metrics.md。
--limit 取前 N 条；--ids 只跑指定 id 列表（两者同时给时 --ids 优先）。

可重复运行（GPT 审查 §4.4 整改）：向量索引与报告输出都用**隔离临时目录**，
不污染主知识库索引与正式报告产物；重复执行不会撞 Chroma 固定 doc_id 重复错误。
"""
import argparse
import sys
import tempfile
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
    parser.add_argument("--ids", type=str, default=None, help="只跑指定任务 id（逗号分隔）")
    args = parser.parse_args()

    tasks = load_tasks()
    if args.ids:
        wanted = {x.strip() for x in args.ids.split(",") if x.strip()}
        tasks = [t for t in tasks if t["id"] in wanted]
        print(f"加载任务集：{len(load_tasks())} 条，本次只跑 {len(tasks)} 条: {sorted(wanted)}")
    else:
        print(f"加载任务集：{len(tasks)} 条" + (f"，本次只跑前 {args.limit} 条" if args.limit else ""))

    # 隔离临时向量索引：每次运行全新构建，不写主库 data/vectorstore，可重复执行
    with tempfile.TemporaryDirectory(prefix="harness_vec_") as vec_dir:
        print("构建知识库索引（隔离临时目录）...")
        retriever = build_retriever(
            settings.ARTICLES_DB, Path(vec_dir), settings.MODEL_DIR, reset=True
        )
        store = SQLiteStore(settings.ARTICLES_DB)
        try:
            pipeline = ReportPipeline(retriever, store)
            run_harness(pipeline, tasks, limit=args.limit)
        finally:
            store.close()


if __name__ == "__main__":
    main()
