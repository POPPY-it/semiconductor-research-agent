"""抓取新闻文章正文并回写数据库（M2 正文语料准备）。

用法: python scripts/fetch_articles.py [--limit N]
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.collectors.article_content import fetch_content  # noqa: E402
from data.storage import SQLiteStore  # noqa: E402

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "articles.db"

# SEC 要求描述性 User-Agent（浏览器 UA 会被 403）
SEC_UA = {
    "User-Agent": "SemiconductorResearchAgent/0.1 (campus recruiting project; contact: research@example.com)"
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--source", choices=["all", "news", "sec"], default="all")
    args = parser.parse_args()

    store = SQLiteStore(DEFAULT_DB)
    try:
        articles = store.query_articles(limit=300)
        if args.source == "news":
            targets = [a for a in articles if a["source"] in ("GoogleNews", "IT之家") and not a["content"]]
        elif args.source == "sec":
            targets = [a for a in articles if a["source"] == "SEC_EDGAR" and not a["content"]]
        else:
            targets = [a for a in articles if not a["content"]]
        print(f"待抓正文: {len(targets)} 篇（上限 {args.limit}）")
        ok = fail = 0
        for art in targets[: args.limit]:
            max_chars = 8000 if art["source"] == "SEC_EDGAR" else 6000
            headers = SEC_UA if art["source"] == "SEC_EDGAR" else None
            content = fetch_content(art["url"], max_chars=max_chars, headers=headers)
            if not content and art["source"] == "SEC_EDGAR":
                time.sleep(2.0)  # 403 限流则退避重试一次
                content = fetch_content(art["url"], max_chars=max_chars, headers=headers)
            if content:
                store.update_content(art["url"], content)
                ok += 1
                print(f"OK  [{art['source']}] {art['title'][:45]} ({len(content)} 字)")
            else:
                fail += 1
                print(f"FAIL [{art['source']}] {art['title'][:45]}")
            if art["source"] == "SEC_EDGAR":
                time.sleep(0.5)  # SEC 礼貌限速
        print(f"\n完成: 成功 {ok}，失败 {fail}")
    finally:
        store.close()


if __name__ == "__main__":
    main()
