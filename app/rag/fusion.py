# -*- coding: utf-8 -*-
"""RRF（Reciprocal Rank Fusion）：按排名倒数融合多路检索结果，无需归一化分数。"""
from typing import Dict, List


def reciprocal_rank_fusion(rankings: List[List], k: int = 60, top_k: int = 10) -> List:
    """rankings: 多路文档标识排序列表（越靠前排名越高）。返回融合后的文档标识。"""
    scores: Dict = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return [doc_id for doc_id, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)][:top_k]
