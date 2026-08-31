# -*- coding: utf-8 -*-
"""词面检索：jieba 中文分词 + BM25Okapi。
与向量检索互补：Go 包名、文章编号、精确措辞等词面命中更可靠（替代 MySQL LIKE）。
"""
import logging
from typing import List

import jieba
from rank_bm25 import BM25Okapi

logger = logging.getLogger("airobot.lexical")

jieba.setLogLevel(logging.WARNING)


def tokenize(text: str) -> List[str]:
    return [t for t in jieba.lcut(text) if t.strip()]


class BM25Index:
    """进程内 BM25 索引：以文档顺序对应 KnowledgeBase._documents。"""

    def __init__(self) -> None:
        self._corpus: List[str] = []
        self._bm25: BM25Okapi | None = None

    @property
    def ready(self) -> bool:
        return self._bm25 is not None

    def add_documents(self, texts: List[str]) -> None:
        # 增量追加后全量重建：调用方只传新增分块，语料顺序必须与 KnowledgeBase._documents 保持对齐
        self._corpus = [*self._corpus, *texts]
        self._bm25 = BM25Okapi([tokenize(t) for t in self._corpus])

    def search(self, query: str, top_k: int) -> List[int]:
        """返回按 BM25 得分排序的文档索引列表（仅保留得分>0 的命中）。"""
        if not self.ready or not self._corpus:
            return []
        scores = self._bm25.get_scores(tokenize(query))
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        return [i for i in order if scores[i] > 0][:top_k]
