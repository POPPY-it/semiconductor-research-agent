"""行业新闻 RSS 采集器（数据源 2、3/5）。

- Google News RSS：聚合全网中文半导体新闻（该域名直连超时，需走本机代理）
- IT之家 RSS：IT 综合资讯（直连可用），按半导体关键词过滤
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import requests

from .base import BaseCollector

GOOGLE_NEWS_PROXIES = {"http": "http://127.0.0.1:10808", "https": "http://127.0.0.1:10808"}

KEYWORDS = (
    "半导体", "芯片", "晶圆", "光刻", "存储", "台积电", "中芯", "EDA",
    "先进封装", "GPU", "HBM", "集成电路", "晶圆代工", "算力", "AI芯片", "英伟达",
)


def _parse_rss_items(xml_bytes: bytes, limit: int, source: str, keyword_filter=None) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    items: list[dict] = []
    for item in root.findall("./channel/item"):
        title = item.findtext("title") or ""
        if keyword_filter and not any(kw in title for kw in keyword_filter):
            continue
        items.append(
            {
                "source": source,
                "title": title,
                "url": item.findtext("link") or "",
                "published_at": item.findtext("pubDate") or "",
                "extra": {"origin_source": item.findtext("source") or ""},
            }
        )
        if len(items) >= limit:
            break
    return items


class GoogleNewsRSSCollector(BaseCollector):
    """Google News RSS（需代理；代理不可用时自动失败降级，不阻塞其他源）。"""

    name = "google_news"

    def __init__(self, query: str = "半导体", limit: int = 10):
        self.query = query
        self.limit = limit

    def fetch(self) -> list[dict]:
        url = (
            "https://news.google.com/rss/search?"
            f"q={requests.utils.quote(self.query)}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
        )
        resp = requests.get(url, proxies=GOOGLE_NEWS_PROXIES, timeout=15)
        resp.raise_for_status()
        return _parse_rss_items(resp.content, self.limit, source="GoogleNews")


class SinaTechRSSCollector(BaseCollector):
    """新浪科技滚动新闻 RSS（直连可用，无需代理）。"""

    name = "sina_tech"
    URL = "https://rss.sina.com.cn/tech/rollnews.xml"

    def __init__(self, limit: int = 50):
        self.limit = limit

    def fetch(self) -> list[dict]:
        resp = requests.get(
            self.URL,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
                )
            },
            timeout=15,
        )
        resp.raise_for_status()
        return _parse_rss_items(
            resp.content, self.limit, source="新浪科技", keyword_filter=KEYWORDS
        )


class ITHomeRSSCollector(BaseCollector):
    name = "ithome"

    def __init__(self, limit: int = 20):
        self.limit = limit

    def fetch(self) -> list[dict]:
        resp = requests.get("https://www.ithome.com/rss/", timeout=30)
        resp.raise_for_status()
        return _parse_rss_items(resp.content, self.limit, source="IT之家", keyword_filter=KEYWORDS)
