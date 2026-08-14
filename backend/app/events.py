"""事件总线：编排器阶段事件 → 每个会话的订阅队列 → SSE。

Worker 线程 publish，SSE 生成器 subscribe 后阻塞 drain；
事件 {"type": "...", "data": {...}}，以 type=done/error 结束流。
"""
from __future__ import annotations

import queue
import threading
import time


class EventBus:
    def __init__(self):
        self._subscribers: dict[int, list[queue.Queue]] = {}
        self._last_terminal: dict[int, dict] = {}  # 终态事件积压：晚连接的订阅者立即可得
        self._lock = threading.Lock()

    def publish(self, session_id: int, event: dict) -> None:
        if event.get("type") in ("done", "error"):
            with self._lock:
                self._last_terminal[session_id] = event
        with self._lock:
            subs = list(self._subscribers.get(session_id, []))
        for q in subs:
            q.put(event)

    def subscribe(self, session_id: int) -> "Subscription":
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.setdefault(session_id, []).append(q)
            terminal = self._last_terminal.get(session_id)
        if terminal:
            q.put(terminal)  # 已终态：立即补发
        return Subscription(self, session_id, q)

    def _unsubscribe(self, session_id: int, q: queue.Queue) -> None:
        with self._lock:
            subs = self._subscribers.get(session_id, [])
            if q in subs:
                subs.remove(q)


class Subscription:
    def __init__(self, bus: EventBus, session_id: int, q: queue.Queue):
        self._bus = bus
        self._session_id = session_id
        self._q = q

    def next_event(self, timeout: float = 25.0) -> dict | None:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None  # 超时返回 None，由调用方决定是否续等

    def close(self) -> None:
        self._bus._unsubscribe(self._session_id, self._q)


def wait_for_terminal(bus: EventBus, session_id: int, timeout: float = 600.0) -> dict | None:
    """测试/脚本用：阻塞等到 done/error 事件。"""
    sub = bus.subscribe(session_id)
    try:
        deadline = time.time() + timeout
        while time.time() < deadline:
            ev = sub.next_event(timeout=30.0)
            if ev and ev.get("type") in ("done", "error"):
                return ev
        return None
    finally:
        sub.close()
