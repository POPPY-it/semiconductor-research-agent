"""PubMed（生物医药文献）采集器：E-utilities esearch + efetch，解析标题/作者/摘要。

复用学术调研能力，把平台从"半导体"扩展到"生物医药"领域。
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET

import requests

from .base import BaseCollector

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def search_pubmed(query: str, limit: int = 8) -> list[dict]:
    """检索 PubMed 并返回 [{pmid, title, authors, journal, pubdate, doi, abstract}]。"""
    # 1) esearch → PMIDs
    es = requests.get(
        f"{BASE}/esearch.fcgi",
        params={"db": "pubmed", "term": query, "retmax": limit, "retmode": "json", "sort": "relevance"},
        timeout=20,
    )
    es.raise_for_status()
    pmids = es.json().get("esearchresult", {}).get("idlist", [])
    if not pmids:
        return []

    # 2) efetch → XML 摘要
    ef = requests.get(
        f"{BASE}/efetch.fcgi",
        params={"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"},
        timeout=30,
    )
    ef.raise_for_status()
    root = ET.fromstring(ef.content)

    items = []
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//PMID", "")
        title = " ".join(art.findtext(".//ArticleTitle", "").split())
        abstract_parts = [
            " ".join(t.text.split()) if t.text else ""
            for t in art.findall(".//Abstract/AbstractText")
        ]
        abstract = " ".join(abstract_parts)
        journal = art.findtext(".//Journal/Title", "")
        authors = [
            f"{a.findtext('LastName', '')} {a.findtext('ForeName', '')}".strip()
            for a in art.findall(".//AuthorList/Author")
        ]
        pubdate = art.findtext(".//JournalIssue/PubDate/Year", "")
        doi = ""
        for idel in art.findall(".//ArticleIdList/ArticleId"):
            if idel.get("IdType") == "doi":
                doi = idel.text or ""
                break
        items.append(
            {
                "pmid": pmid,
                "title": title,
                "authors": authors[:8],
                "journal": journal,
                "pubdate": pubdate,
                "doi": doi,
                "abstract": abstract,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            }
        )
    return items


class PubMedCollector(BaseCollector):
    name = "pubmed"

    # 生物医药领域高频主题（可按需扩展）
    DEFAULT_TOPICS = [
        "cancer immunotherapy",
        "CRISPR gene editing",
        "machine learning drug discovery",
        "genomics",
    ]

    def __init__(self, topics: list[str] | None = None, per_topic: int = 8):
        self.topics = topics or self.DEFAULT_TOPICS
        self.per_topic = per_topic

    def fetch(self) -> list[dict]:
        items: list[dict] = []
        for topic in self.topics:
            papers = search_pubmed(topic, self.per_topic)
            for p in papers:
                items.append(
                    {
                        "source": "PubMed",
                        "title": p["title"],
                        "url": p["url"],
                        "published_at": p["pubdate"],
                        "content": (
                            f"{p['title']}\n作者：{', '.join(p['authors'])}\n"
                            f"期刊：{p['journal']} ({p['pubdate']})\n摘要：{p['abstract']}"
                        ),
                        "extra": {
                            "authors": p["authors"],
                            "journal": p["journal"],
                            "doi": p["doi"],
                            "pmid": p["pmid"],
                        },
                    }
                )
            time.sleep(0.4)  # PubMed 限速 3 req/s，礼貌间隔
        return items
