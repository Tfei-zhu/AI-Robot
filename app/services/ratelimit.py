# -*- coding: utf-8 -*-
"""限流：进程内滑动窗口（按 IP，60 秒窗口），无外部依赖。"""
import threading
import time
from collections import deque

from app.config import settings


class SlidingWindowLimiter:
    def __init__(self, limit_per_minute: int = 30, window_sec: float = 60.0) -> None:
        self.limit = limit_per_minute
        self.window_sec = window_sec
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()
        self.blocked = 0

    def allow(self, key: str) -> bool:
        """返回是否放行；超出窗口内上限则拦截。"""
        now = time.monotonic()
        with self._lock:
            queue = self._hits.setdefault(key, deque())
            while queue and now - queue[0] >= self.window_sec:
                queue.popleft()
            if len(queue) >= self.limit:
                self.blocked += 1
                return False
            queue.append(now)
            self._cleanup()
            return True

    def _cleanup(self) -> None:
        if len(self._hits) > 10_000:
            for key in [k for k, q in self._hits.items() if not q]:
                self._hits.pop(key, None)

    def stats(self) -> dict:
        with self._lock:
            return {
                "window_sec": self.window_sec,
                "limit_per_minute": self.limit,
                "blocked": self.blocked,
                "active_keys": len(self._hits),
            }


limiter = SlidingWindowLimiter(limit_per_minute=settings.ratelimit_per_minute)
