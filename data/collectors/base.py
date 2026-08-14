"""数据源适配器基类：统一接口 + 重试机制。

约定：
- 每个采集器实现 fetch() -> list[dict]，dict 必须含 title/url/source/published_at
- 网络策略（直连/代理）由各适配器自己声明
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class CollectError(Exception):
    """采集失败（重试耗尽后抛出）。"""


class BaseCollector(ABC):
    name: str = "base"
    retries: int = 2
    retry_delay: float = 2.0

    @abstractmethod
    def fetch(self) -> list[dict]:
        """抓取并返回规范化条目列表。"""

    def collect(self) -> list[dict]:
        """带重试的采集入口。"""
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                items = self.fetch()
                logger.info("[%s] 采集成功: %d 条", self.name, len(items))
                return items
            except Exception as e:  # noqa: BLE001 —— 采集源异常统一重试
                last_exc = e
                logger.warning("[%s] 第 %d/%d 次失败: %s", self.name, attempt + 1, self.retries + 1, e)
                if attempt < self.retries:
                    time.sleep(self.retry_delay)
        raise CollectError(f"[{self.name}] 重试 {self.retries} 次后仍失败: {last_exc}")
