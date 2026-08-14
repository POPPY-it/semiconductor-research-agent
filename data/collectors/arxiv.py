"""arXiv 学术论文采集器（官方 Atom API，直连免代理）。"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import requests

from .base import BaseCollector

NS = {"atom": "http://www.w3.org/2005/Atom"}

# 半导体/芯片相关领域分类（arXiv 分类代码）
DEFAULT_CATEGORIES = [
    "cs.AR",              # 计算机硬件架构
    "eess.SP",            # 信号处理
    "physics.app-ph",     # 应用物理（器件/工艺）
    "cond-mat.mes-hall",  # 介观与纳米器件物理
    "quant-ph",           # 量子物理（量子芯片）
]


class ArxivCollector(BaseCollector):
    name = "arxiv"

    def __init__(self, categories: list[str] | None = None, per_category: int = 10):
        self.categories = categories or DEFAULT_CATEGORIES
        self.per_category = per_category

    def fetch(self) -> list[dict]:
        items: list[dict] = []
        for cat in self.categories:
            url = (
                "https://export.arxiv.org/api/query?"
                f"search_query=cat:{cat}&sortBy=submittedDate&sortOrder=descending"
                f"&max_results={self.per_category}"
            )
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            for entry in root.findall("atom:entry", NS):
                title = re.sub(r"\s+", " ", entry.findtext("atom:title", "", NS)).strip()
                summary = re.sub(r"\s+", " ", entry.findtext("atom:summary", "", NS)).strip()
                link = entry.findtext("atom:id", "", NS)
                published = entry.findtext("atom:published", "", NS)[:10]
                authors = [
                    a.findtext("atom:name", "", NS) for a in entry.findall("atom:author", NS)
                ]
                cats = [c.get("term", "") for c in entry.findall("atom:category", NS)]
                items.append(
                    {
                        "source": "arXiv",
                        "title": title,
                        "url": link,
                        "published_at": published,
                        "content": (
                            f"{title}\n作者：{', '.join(authors[:8])}\n"
                            f"分类：{', '.join(cats)}\n摘要：{summary}"
                        ),
                        "extra": {"authors": authors, "categories": cats},
                    }
                )
        return items
