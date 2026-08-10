# -*- coding: utf-8 -*-
"""链路追踪模块单测：环形缓冲容量 / 汇总统计。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.tracing import TraceRecorder  # noqa: E402


def test_trace_recorder_ring_and_summary():
    r = TraceRecorder(max_entries=5)
    r.record({"total_ms": 100, "cache_hit": True, "cache_checked": True, "intent": "knowledge"})
    r.record({"total_ms": 200, "cache_hit": False, "cache_checked": True, "intent": "chat"})
    r.record({"total_ms": 300, "cache_hit": False, "cache_checked": False, "intent": "order"})
    r.record({"total_ms": 400, "status": 200})
    assert len(r.recent()) == 4
    s = r.summary()
    assert s["total"] == 4
    assert s["p95_ms"] == 400
    assert s["avg_ms"] == 250.0
    assert s["cache_hit_rate"] == 0.5  # 检查过缓存的 2 条中命中 1 条
    assert s["by_intent"]["knowledge"] == 1


def test_trace_recorder_ring_capacity():
    r = TraceRecorder(max_entries=2)
    r.record({"total_ms": 1})
    r.record({"total_ms": 2})
    r.record({"total_ms": 3})  # 最旧一条被丢弃
    assert [e["total_ms"] for e in r.recent()] == [3, 2]


def test_trace_recorder_empty():
    assert TraceRecorder().summary()["total"] == 0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
