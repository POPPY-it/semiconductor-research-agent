"""数据源适配器包与注册表。"""
from .base import BaseCollector, CollectError
from .news_rss import GoogleNewsRSSCollector, ITHomeRSSCollector, SinaTechRSSCollector
from .sec_edgar import SECEdgarCollector

ALL_COLLECTORS: list[BaseCollector] = [
    SECEdgarCollector(),
    SinaTechRSSCollector(),
    ITHomeRSSCollector(),
    GoogleNewsRSSCollector(),  # 需代理；失败自动降级
]

__all__ = [
    "BaseCollector",
    "CollectError",
    "SECEdgarCollector",
    "SinaTechRSSCollector",
    "GoogleNewsRSSCollector",
    "ITHomeRSSCollector",
    "ALL_COLLECTORS",
]
