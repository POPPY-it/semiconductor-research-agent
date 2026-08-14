"""行业新闻 RSS 采集器原型（数据源 2、3/5）。

- Google News RSS：聚合全网中文半导体新闻（该域名直连超时，需走本机代理）
- IT之家 RSS：IT 综合资讯（直连可用），按半导体关键词过滤

不同数据源的网络策略不同 → W3（M1）将统一为"源适配器"接口，每个适配器自带网络策略。
"""
from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

RAW_DIR = Path(__file__).resolve().parents[1] / "raw"

# Google News 域名在本机需走代理（见 docs/day1-log.md 网络说明）
GOOGLE_NEWS_PROXIES = {"http": "http://127.0.0.1:10808", "https": "http://127.0.0.1:10808"}

KEYWORDS = ("半导体", "芯片", "晶圆", "光刻", "存储", "台积电", "中芯", "EDA", "先进封装", "GPU", "HBM")


def fetch_google_news(query: str = "半导体", limit: int = 10) -> list[dict]:
    url = (
        "https://news.google.com/rss/search?"
        f"q={requests.utils.quote(query)}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    )
    resp = requests.get(url, proxies=GOOGLE_NEWS_PROXIES, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    items: list[dict] = []
    for item in root.findall("./channel/item")[:limit]:
        items.append(
            {
                "title": item.findtext("title"),
                "link": item.findtext("link"),
                "pub_date": item.findtext("pubDate"),
                "source": item.findtext("source"),
            }
        )
    return items


def fetch_ithome(limit: int = 20) -> list[dict]:
    resp = requests.get("https://www.ithome.com/rss/", timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    items: list[dict] = []
    for item in root.findall("./channel/item"):
        title = item.findtext("title") or ""
        if not any(kw in title for kw in KEYWORDS):
            continue
        items.append(
            {
                "title": title,
                "link": item.findtext("link"),
                "pub_date": item.findtext("pubDate"),
                "source": "IT之家",
            }
        )
        if len(items) >= limit:
            break
    return items


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    google = fetch_google_news()
    print(f"[Google News] 半导体相关新闻 {len(google)} 条")
    ithome = fetch_ithome()
    print(f"[IT之家] 半导体关键词过滤后 {len(ithome)} 条")
    result = {
        "collected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "google_news": google,
        "ithome": ithome,
    }
    out_path = RAW_DIR / "news_sample.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已保存 -> {out_path}")


if __name__ == "__main__":
    main()
