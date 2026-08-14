"""研报生成入口：python scripts/generate_report.py [选题]

默认选题：本周半导体行业动态周报（基于已采集的 SEC 财报与行业新闻）
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.knowledge.loader import build_retriever  # noqa: E402
from agent.orchestrator import ReportPipeline  # noqa: E402
from data.storage import SQLiteStore  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "articles.db"
VECTOR_DIR = ROOT / "data" / "vectorstore" / "main"
MODEL_DIR = ROOT / "data" / "models"

DEFAULT_TOPIC = "本周半导体行业动态周报（基于已采集的 SEC 财报披露与行业新闻，聚焦 NVIDIA/台积电/Intel/ASML）"


def main() -> None:
    topic = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TOPIC
    print(f"选题: {topic}")

    print("构建知识库（首次需下载模型）...")
    retriever = build_retriever(DB, VECTOR_DIR, MODEL_DIR)
    print(f"知识库就绪: {len(retriever.documents)} 个分块")

    store = SQLiteStore(DB)
    try:
        pipeline = ReportPipeline(retriever, store)
        result = pipeline.generate(topic)
    finally:
        store.close()

    print(f"\n报告路径: {result['report_path']}")
    print(f"质检结论: {json.dumps(result['verdict'], ensure_ascii=False)}")
    print(f"修订轮数: {result['revision_rounds']}")
    print("\n===== 报告开头 =====")
    print(result["report"][:800])


if __name__ == "__main__":
    main()
