"""任务队列抽象：开发态 ThreadPool 实现；生产态 RQ 实现（见 requirements-prod）。"""
from __future__ import annotations

import threading
import uuid
from abc import ABC, abstractmethod
from concurrent.futures import Future, ThreadPoolExecutor


class TaskQueue(ABC):
    @abstractmethod
    def submit(self, fn, *args, **kwargs) -> str:
        """提交任务，返回 task_id。"""

    @abstractmethod
    def status(self, task_id: str) -> str:
        """queued / running / done / error / unknown。"""

    @abstractmethod
    def result(self, task_id: str, timeout: float | None = None):
        """阻塞取结果（异常时抛出）。"""


class ThreadPoolQueue(TaskQueue):
    """开发态：进程内线程池（无 Redis 依赖，接口与 RQQueue 一致）。"""

    def __init__(self, max_workers: int = 2):
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._futures: dict[str, Future] = {}
        self._lock = threading.Lock()

    def submit(self, fn, *args, **kwargs) -> str:
        task_id = uuid.uuid4().hex[:12]
        future = self._executor.submit(fn, *args, **kwargs)
        with self._lock:
            self._futures[task_id] = future
        return task_id

    def status(self, task_id: str) -> str:
        future = self._futures.get(task_id)
        if future is None:
            return "unknown"
        if future.running():
            return "running"
        if future.done():
            return "error" if future.exception() else "done"
        return "queued"

    def result(self, task_id: str, timeout: float | None = None):
        future = self._futures.get(task_id)
        if future is None:
            raise KeyError(task_id)
        return future.result(timeout=timeout)


class RQQueue(TaskQueue):
    """生产态：RQ + Redis（部署环境通过 requirements-prod.txt 安装 rq 并起 Redis）。"""

    def __init__(self, redis_url: str = "redis://127.0.0.1:6379/0"):
        from redis import Redis  # noqa: F401
        from rq import Queue  # 延迟导入：本地开发无 Redis 不安装

        self._queue = Queue(connection=Redis.from_url(redis_url))

    def submit(self, fn, *args, **kwargs) -> str:
        job = self._queue.enqueue(fn, *args, **kwargs)
        return job.id

    def status(self, task_id: str) -> str:
        from rq.job import Job

        job = Job.fetch(task_id, connection=self._queue.connection)
        if job is None:
            return "unknown"
        return job.get_status(refresh=True)  # queued/started/finished/failed

    def result(self, task_id: str, timeout: float | None = None):
        from rq.job import Job

        job = Job.fetch(task_id, connection=self._queue.connection)
        if job is None:
            raise KeyError(task_id)
        return job.result
