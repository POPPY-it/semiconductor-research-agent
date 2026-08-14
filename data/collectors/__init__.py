"""数据源适配器包与注册表。"""
from .base import BaseCollector, CollectError
from .news_rss import GoogleNewsRSSCollector, ITHomeRSSCollector
from .sec_edgar import SECEdgarCollector

ALL_COLLECTORS: list[BaseCollector] = [
    SECEdgarCollector(),
    GoogleNewsRSSCollector(),
    ITHomeRSSCollector(),
]

__all__ = [
    "BaseCollector",
    "CollectError",
    "SECEdgarCollector",
    "GoogleNewsRSSCollector",
    "ITHomeRSSCollector",
    "ALL_COLLECTORS",
]
