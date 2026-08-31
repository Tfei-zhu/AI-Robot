# -*- coding: utf-8 -*-
"""Go 文章服务集成离线单测：文章 ID 提取 / 数据格式化 / GoArticleClient（MockTransport）/
文章分块构建 / BM25 增量对齐回归 / 文章事件消费者。

运行：python tests/test_integration.py（无第三方测试框架依赖，纯标准库断言）
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from app.rag.lexical import BM25Index
from app.rag.retriever import KnowledgeBase
from app.services.article_consumer import ArticleIngestConsumer
from app.services.go_client import GoArticleClient, GoServiceError

FAKE_ARTICLE = {
    "id": 9, "title": "用 context 管理 Go 并发任务", "summary": "context 最佳实践",
    "content": "# 标题\n\n正文内容，goroutine 与 context 的配合。",
    "username": "zzztf", "tags": ["Go", "并发"],
    "likes_count": 12, "comments_count": 3, "create_time": "2026-08-31T10:00:00+08:00",
}


# ---------- 文章 ID 提取 ----------

def test_extract_article_id():
    from app.agents.tools import _extract_article_id
    assert _extract_article_id("文章 12 的数据") == 12          # 真实自增 ID 是小数字
    assert _extract_article_id("查一下article #3") == 3
    assert _extract_article_id("帮我看下文章45的状态") == 45
    assert _extract_article_id("随便聊聊 2026 年的 Go 大事") == 2026  # 兜底：任意 1~10 位数字
    assert _extract_article_id("你好呀") is None


# ---------- 数据格式化 ----------

def test_format_article():
    from app.agents.tools import _format_article
    text = _format_article(FAKE_ARTICLE)
    assert "文章 9" in text and "已发布" in text
    assert "《用 context 管理 Go 并发任务》" in text and "作者=zzztf" in text
    assert "Go、并发" in text and "点赞 12" in text and "评论 3" in text
    no_tags = _format_article({**FAKE_ARTICLE, "tags": []})
    assert "标签=无" in no_tags


# ---------- GoArticleClient（httpx.MockTransport） ----------

def _mock_client(handler, base_url="http://go:8080", token="t") -> GoArticleClient:
    return GoArticleClient(base_url, token, 5.0, transport=httpx.MockTransport(handler))


def test_go_client_200_and_404():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/internal/ai/article/detail"
        assert request.headers["X-Internal-Token"] == "t"
        import json
        assert json.loads(request.content) == {"id": 9}
        return httpx.Response(200, json={"article": dict(FAKE_ARTICLE), "tags": FAKE_ARTICLE["tags"]})

    client = _mock_client(handler)
    data = asyncio.run(client.get_article_detail(9))
    assert data["id"] == 9 and data["title"] == FAKE_ARTICLE["title"] and data["tags"] == ["Go", "并发"]

    not_found = _mock_client(lambda request: httpx.Response(404, json={"error": "not found"}))
    assert asyncio.run(not_found.get_article_detail(999)) is None


def test_go_client_500_raises():
    client = _mock_client(lambda request: httpx.Response(500, json={"error": "boom"}))
    try:
        asyncio.run(client.get_article_detail(9))
        raise AssertionError("应抛出 GoServiceError")
    except GoServiceError:
        pass


def test_go_client_disabled():
    client = _mock_client(lambda request: httpx.Response(200), base_url="")
    assert client.enabled is False
    try:
        asyncio.run(client.get_article_detail(9))
        raise AssertionError("未启用应抛出 GoServiceError")
    except GoServiceError:
        pass


def test_go_client_sync_path():
    client = _mock_client(lambda request: httpx.Response(200, json={"article": dict(FAKE_ARTICLE), "tags": []}))
    data = client.get_article_detail_sync(9)
    assert data is not None and data["id"] == 9


# ---------- 文章分块构建（离线，不依赖向量库） ----------

def test_build_article_docs():
    kb = KnowledgeBase()
    content = "# 背景\n\nGo 的 context 用于传递取消信号。" * 3
    docs = kb.build_article_docs(9, "用 context 管理 Go 并发任务", content,
                                 summary="context 最佳实践", tags=["Go", "并发"])
    assert len(docs) >= 1
    for i, doc in enumerate(docs):
        assert doc.metadata["doc_id"] == f"article:9#{i}"
        assert doc.metadata["article_id"] == 9
        assert doc.metadata["source"] == "go_article"
        assert doc.metadata["tags"] == "Go,并发"
        assert doc.metadata["title"] == "用 context 管理 Go 并发任务"
    assert docs[0].metadata["chunk"] == 0
    empty = kb.build_article_docs(10, "标题", "")
    assert len(empty) == 0  # 空正文 -> 空分块


# ---------- BM25 增量对齐回归（修复：原实现整体替换语料导致第二次入库后错位） ----------

def test_bm25_incremental_alignment():
    # 注：rank_bm25 在极小语料上 IDF 非正会被 >0 过滤，故用 5 篇语料保证得分有效
    idx = BM25Index()
    idx.add_documents([
        "goroutine 调度器把并发任务分配到线程",        # 0
        "context 携带取消信号跨 API 传递",             # 1
        "channel 是 goroutine 之间通信的管道",          # 2
        "Go 垃圾回收器的工作原理",                      # 3
    ])
    idx.add_documents(["context 的超时与取消"])          # 4（增量追加）
    assert idx.search("超时", top_k=5) == [4]             # 新文档可检索
    assert idx.search("垃圾回收", top_k=5) == [3]         # 修复前：语料被整体替换，老文档检索不到
    assert idx.search("channel", top_k=5) == [2]
    hits = idx.search("context", top_k=5)
    assert 1 in hits and 4 in hits                        # 新旧同时命中，索引与语料对齐
    assert len(idx._corpus) == 5


# ---------- 文章事件消费者 ----------

class _StubKB:
    def __init__(self):
        self.chunk_count = 0
        self.calls: list[int] = []

    def ingest_article(self, article_id, title, content, summary="", tags=None):
        self.calls.append(article_id)
        self.chunk_count += 2
        return 2


class _StubClient:
    def __init__(self, result):
        self._result = result

    async def get_article_detail(self, article_id):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _run(consumer, payload):
    return asyncio.run(consumer.handle_event(payload))


def test_consumer_ingest_and_dedupe():
    kb = _StubKB()
    consumer = ArticleIngestConsumer(kb, _StubClient(dict(FAKE_ARTICLE)))
    assert _run(consumer, {"event_id": "a", "article_id": 9}) == "ingested"
    assert kb.calls == [9] and kb.chunk_count == 2
    assert _run(consumer, {"event_id": "b", "article_id": 9}) == "duplicate"
    assert kb.calls == [9] and kb.chunk_count == 2  # 重复投递不重复入库


def test_consumer_not_found_and_invalid_and_skipped():
    consumer = ArticleIngestConsumer(_StubKB(), _StubClient(None))
    assert _run(consumer, {"article_id": 404}) == "not_found"
    assert _run(consumer, {"article_id": 0}) == "invalid"
    assert _run(consumer, {"no_id": True}) == "invalid"
    assert _run(consumer, "not-a-dict") == "invalid"
    consumer_err = ArticleIngestConsumer(_StubKB(), _StubClient(GoServiceError("down")))
    assert _run(consumer_err, {"article_id": 7}) == "skipped"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
    sys.exit(1 if failed else 0)
