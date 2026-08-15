"""数据源适配器包与注册表。"""
from .arxiv import ArxivCollector
from .base import BaseCollector, CollectError
from .news_rss import GoogleNewsRSSCollector, ITHomeRSSCollector, SinaTechRSSCollector
from .pubmed import PubMedCollector
from .sec_edgar import SECEdgarCollector

ALL_COLLECTORS: list[BaseCollector] = [
    SECEdgarCollector(),
    ArxivCollector(),
    PubMedCollector(),
    SinaTechRSSCollector(),
    ITHomeRSSCollector(),
    GoogleNewsRSSCollector(),  # 需代理；失败自动降级
]

__all__ = [
    "BaseCollector",
    "CollectError",
    "SECEdgarCollector",
    "ArxivCollector",
    "PubMedCollector",
    "SinaTechRSSCollector",
    "GoogleNewsRSSCollector",
    "ITHomeRSSCollector",
    "ALL_COLLECTORS",
]
