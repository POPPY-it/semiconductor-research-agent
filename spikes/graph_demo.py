"""知识图谱真实数据验证：从文章库建图 → 输出核心实体与关联关系。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.knowledge.graph import KnowledgeGraph  # noqa: E402
from data.storage import SQLiteStore  # noqa: E402


def main() -> None:
    store = SQLiteStore(Path(__file__).resolve().parents[1] / "data" / "articles.db")
    try:
        articles = store.query_articles(limit=1000)
    finally:
        store.close()

    graph = KnowledgeGraph()
    for art in articles:
        text = art["title"] + ("\n" + art["content"] if art["content"] else "")
        graph.add_document(f"a{art['url'][:20]}", text)

    print("图谱统计:", graph.stats())
    print("\n=== 全局核心实体（按关联度 Top15）===")
    for e, w in graph.centrality(15):
        print(f"  {e}: {w}")
    print("\n=== 「台积电」关联实体 ===")
    for e, w in graph.related_entities("台积电", 10):
        print(f"  {e}: 共现 {w}")
    print("\n=== 「HBM」关联实体 ===")
    for e, w in graph.related_entities("HBM", 10):
        print(f"  {e}: 共现 {w}")
    print("\n=== 「RAG」关联实体 ===")
    for e, w in graph.related_entities("RAG", 10):
        print(f"  {e}: 共现 {w}")


if __name__ == "__main__":
    main()
