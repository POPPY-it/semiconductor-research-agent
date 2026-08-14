"""可观测性与防护中间件：请求 ID 审计日志、速率限制、Prometheus 指标。"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger("access")


class Metrics:
    """进程内计数器（Prometheus 文本格式暴露）。"""

    def __init__(self):
        self._lock = threading.Lock()
        self.counters: dict[str, int] = defaultdict(int)

    def inc(self, name: str, labels: tuple[str, ...] = (), amount: int = 1) -> None:
        key = name + "|" + "|".join(labels)
        with self._lock:
            self.counters[key] += amount

    def render(self) -> str:
        with self._lock:
            items = sorted(self.counters.items())
        lines = []
        for key, val in items:
            name, labels = key.split("|", 1)
            lines.append(f"{name}{{{labels}}} {val}")
        return "\n".join(lines) + "\n"


metrics = Metrics()


class RequestLogMiddleware(BaseHTTPMiddleware):
    """X-Request-ID 注入 + 结构化访问日志 + 基础指标。"""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        start = time.perf_counter()
        metrics.inc("http_requests_total")
        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001
            metrics.inc("http_exceptions_total")
            raise
        duration_ms = (time.perf_counter() - start) * 1000
        if 400 <= response.status_code < 500:
            metrics.inc("http_4xx_total")
        elif response.status_code >= 500:
            metrics.inc("http_5xx_total")
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "%s %s %s %s %.1fms",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """滑动窗口令牌桶（进程内）。规则：路径前缀 → (窗口秒, 上限)。"""

    def __init__(self, app, rules: dict[str, tuple[int, int]] | None = None):
        super().__init__(app)
        self.rules = rules or {
            "POST /api/v1/sessions": (60, 5),       # 创建任务：5 次/分钟
            "POST /api/v1/auth/login": (60, 10),    # 登录：10 次/分钟
            "GET /api/v1/sessions": (60, 120),      # 查询：120 次/分钟
        }
        self._buckets: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def _client_ip(self, request: Request) -> str:
        fwd = request.headers.get("X-Forwarded-For")
        return (fwd.split(",")[0].strip() if fwd else request.client.host) or "unknown"

    async def dispatch(self, request: Request, call_next):
        key = f"{request.method} {request.url.path}"
        for prefix, (window, limit) in self.rules.items():
            if key.startswith(prefix.split(" ")[0]) and request.url.path in prefix:
                ip = self._client_ip(request)
                bucket_key = f"{ip}|{prefix}"
                now = time.time()
                with self._lock:
                    bucket = [t for t in self._buckets[bucket_key] if now - t < window]
                    if len(bucket) >= limit:
                        self._buckets[bucket_key] = bucket
                        metrics.inc("http_429_total")
                        return JSONResponse(
                            {"detail": "rate limit exceeded"}, status_code=429
                        )
                    bucket.append(now)
                    self._buckets[bucket_key] = bucket
        return await call_next(request)
