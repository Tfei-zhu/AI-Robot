# -*- coding: utf-8 -*-
"""语义缓存：查询向量余弦相似度 + 词面重叠双门限命中即复用答案。
面向无上下文的首轮问题；相似问题（如“Go 的 context 如何取消”与“context 怎么终止任务”）命中同一份回答，
降低 LLM 调用与成本。双门限可避免本地小 embedding 模型相似度不具区分度导致的误命中。
"""
import math
import time

from app.rag.lexical import tokenize


class SemanticCache:
    def __init__(self, threshold: float = 0.75, lexical_threshold: float = 0.5,
                 max_entries: int = 1000) -> None:
        self.threshold = threshold
        self.lexical_threshold = lexical_threshold
        self.max_entries = max_entries
        self._items: list[dict] = []
        self.hits = 0
        self.misses = 0
        self.cleared = 0

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    @staticmethod
    def _lexical_overlap(a: str, b: str) -> float:
        """jieba 分词集合的重叠率（交集 / 较小集合），抵御 embedding 相似度误判。"""
        ta = set(tokenize(a))
        tb = set(tokenize(b))
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / min(len(ta), len(tb))

    def get(self, query_vec: list[float], query_text: str = "") -> dict | None:
        """双门限命中返回缓存的对话结果 dict；未命中返回 None。
        余弦最高的候选若词面不合格，继续检查其余候选，取双门限均通过的余弦最高者。"""
        best_item = None
        best_sim = -1.0
        for item in self._items:
            sim = self._cosine(query_vec, item["vec"])
            if sim < self.threshold:
                continue
            if (query_text and item.get("query")
                    and self._lexical_overlap(query_text, item["query"])
                    < self.lexical_threshold):
                continue  # 词面不合格，跳过该候选
            if sim > best_sim:
                best_sim = sim
                best_item = item
        if best_item is not None:
            self.hits += 1
            return dict(best_item["result"])
        self.misses += 1
        return None

    def put(self, query_vec: list[float], result: dict, query_text: str = "") -> None:
        self._items.append({
            "vec": query_vec, "query": query_text,
            "result": dict(result), "ts": time.time(),
        })
        if len(self._items) > self.max_entries:
            self._items = sorted(self._items, key=lambda x: x["ts"])[len(self._items) // 2:]

    def clear(self) -> None:
        self.cleared += len(self._items)
        self._items = []

    def stats(self) -> dict:
        return {
            "enabled": True,
            "threshold": self.threshold,
            "lexical_threshold": self.lexical_threshold,
            "size": len(self._items),
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / (self.hits + self.misses), 4)
            if (self.hits + self.misses) else 0.0,
        }


semantic_cache = SemanticCache()
