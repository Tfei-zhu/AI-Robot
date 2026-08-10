# -*- coding: utf-8 -*-
"""轻量链路追踪：记录每次请求各阶段耗时（内存环形缓冲），供可视化控制台监控。
字段约定：ts / message / session_id / status / intent / engine / cache_checked /
cache_hit / cache_lookup_ms / intent_ms / retrieval_ms / llm_ms / first_token_ms /
tokens / sources / total_ms。
"""
import threading
import time
from collections import deque


class TraceRecorder:
    def __init__(self, max_entries: int = 300) -> None:
        self._entries: deque = deque(maxlen=max_entries)
        self._lock = threading.Lock()

    def record(self, entry: dict) -> None:
        entry["ts"] = time.time()
        with self._lock:
            self._entries.appendleft(entry)

    def recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return list(self._entries)[:limit]

    def summary(self) -> dict:
        with self._lock:
            total = len(self._entries)
            if total == 0:
                return {"total": 0, "avg_ms": 0.0, "p95_ms": 0.0,
                        "cache_hit_rate": 0.0, "blocked": 0, "by_intent": {}}
            lat = sorted(e.get("total_ms", 0) for e in self._entries)
            p95 = lat[min(int(len(lat) * 0.95), len(lat) - 1)]
            hits = sum(1 for e in self._entries if e.get("cache_hit"))
            checked = sum(1 for e in self._entries if e.get("cache_checked"))
            by_intent: dict[str, int] = {}
            for e in self._entries:
                k = e.get("intent") or "?"
                by_intent[k] = by_intent.get(k, 0) + 1
            return {
                "total": total,
                "avg_ms": round(sum(lat) / len(lat), 1),
                "p95_ms": round(p95, 1),
                "cache_hit_rate": round(hits / checked, 3) if checked else 0.0,
                "blocked": sum(1 for e in self._entries if e.get("status") == 429),
                "by_intent": by_intent,
            }


traces = TraceRecorder()
