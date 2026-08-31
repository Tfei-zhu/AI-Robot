# -*- coding: utf-8 -*-
"""第 4 批稳定性工程离线单测：语义缓存双门限 / 滑动窗口限流 / 重试异常分类。

运行：python tests/test_stability.py（无第三方测试框架依赖，纯标准库断言）
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import openai

from app.services.ratelimit import SlidingWindowLimiter
from app.services.resilience import _is_retryable
from app.services.semantic_cache import SemanticCache


def test_semantic_cache_double_gate():
    """同义改写（余弦 + 词面双门限）命中；仅词面不同或仅向量相似均拒绝。"""
    cache = SemanticCache(threshold=0.75, lexical_threshold=0.5)
    vec_a = [1.0, 0.0, 0.0]
    vec_b = [0.8, 0.6, 0.0]  # 与 vec_a 余弦 = 0.8 >= 0.75
    cache.put(vec_a, {"reply": "需说明 context 的传播和错误处理", "intent": "knowledge"}, "Go 并发示例如何处理 context")

    hit = cache.get(vec_b, "Go 并发代码里的 context 怎么传递")
    assert hit is not None and hit["reply"] == "需说明 context 的传播和错误处理"

    # 向量相似但词面零重叠 -> 拒
    assert cache.get(vec_b, "今天天气怎么样") is None
    # 向量不相似（同为运费问题）-> 拒
    assert cache.get([0.0, 1.0, 0.0], "Go 并发示例如何处理 context") is None


def test_semantic_cache_stats():
    cache = SemanticCache()
    cache.get([1.0, 0.0], "a")
    cache.put([1.0, 0.0], {"reply": "r"}, "a")
    cache.get([1.0, 0.0], "a")
    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["size"] == 1
    assert stats["hit_rate"] == 0.5


def test_semantic_cache_second_best_candidate():
    """余弦最高的候选词面不合格时，应继续检查其余候选（回归：SSE 缓存未命中）。"""
    cache = SemanticCache(threshold=0.75, lexical_threshold=0.5)
    # 与查询余弦最高（0.985）但词面零重叠 -> 应被跳过
    cache.put([1.0, 0.0, 0.0], {"reply": "文章答案"}, "Go 文章如何添加标签")
    # 余弦次高（0.854）且词面重叠 0.8 -> 应命中
    cache.put([0.75, 0.661, 0.0], {"reply": "context 答案"}, "Go 并发示例如何处理 context")
    hit = cache.get([0.985, 0.174, 0.0], "并发代码的 context 如何处理")
    assert hit is not None and hit["reply"] == "context 答案"


def test_ratelimit_sliding_window():
    limiter = SlidingWindowLimiter(limit_per_minute=5, window_sec=60)
    assert all(limiter.allow("ip-1") for _ in range(5))
    assert not limiter.allow("ip-1")  # 第 6 个被拦截
    assert limiter.allow("ip-2")      # 其他 key 不受影响
    assert limiter.stats()["blocked"] == 1


def test_ratelimit_window_expiry():
    limiter = SlidingWindowLimiter(limit_per_minute=2, window_sec=0.2)
    assert limiter.allow("ip-x") and limiter.allow("ip-x")
    assert not limiter.allow("ip-x")
    time.sleep(0.3)
    assert limiter.allow("ip-x")  # 窗口滑动后恢复


def test_retryable_classification():
    req = httpx.Request("POST", "http://localhost/v1/chat/completions")
    r429 = httpx.Response(429, request=req)
    r500 = httpx.Response(500, request=req)
    r400 = httpx.Response(400, request=req)
    assert _is_retryable(openai.RateLimitError("too many", response=r429, body=None))
    assert _is_retryable(openai.InternalServerError("boom", response=r500, body=None))
    assert not _is_retryable(openai.BadRequestError("bad", response=r400, body=None))
    assert not _is_retryable(ValueError("not an openai error"))


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
    sys.exit(1 if failed else 0)
