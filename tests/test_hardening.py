"""存储、缓存、鉴权、并发和真实流式回归，不依赖网络服务。"""
import asyncio
import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from app.config import settings
from app.rag.retriever import KnowledgeBase
from app.rag.lexical import BM25Index
from app.services.article_consumer import ArticleIngestConsumer, RetryLater
from app.services.semantic_cache import SemanticCache, semantic_cache
from app.services.memory import memory
from app.services.concurrency import run_blocking
from app.services.security import session_identity
from scripts.reset_collection import validate_target
from app.agents import tools, graph
import app.main as main
import importlib

chat_module = importlib.import_module("app.services.chat")


class Store:
    def __init__(self):
        self.rows = {}
        self.fail = False
        self.calls = 0

    def add_documents(self, docs, ids=None):
        self.calls += 1
        if self.fail:
            raise RuntimeError("模拟向量服务失败")
        self.rows.update(zip(ids, docs))

    def upsert(self, ids, documents):
        self.add_documents(documents, ids)

    def similarity_search(self, query, k):
        return list(self.rows.values())[:k]


class StorageTests(unittest.TestCase):
    def make_kb(self, path=None, store=None):
        kb = KnowledgeBase(manifest_path=path)
        kb.backend = "inmemory"
        kb._store = store or Store()
        return kb

    def test_isolated_collections_and_no_constructor_io(self):
        with patch("app.rag.retriever.build_vector_store", side_effect=AssertionError("不应初始化")):
            a, b = KnowledgeBase(), KnowledgeBase()
            production = KnowledgeBase(purpose="production")
        self.assertNotEqual(a.collection_name, b.collection_name)
        self.assertNotEqual(a.collection_name, production.collection_name)
        self.assertEqual(production.collection_name, settings.milvus_collection)
        with self.assertRaises(ValueError):
            validate_target(production.collection_name, production.collection_name)
        validate_target(a.collection_name, a.collection_name)
        with self.assertRaises(ValueError):
            validate_target(a.collection_name, b.collection_name)

    def test_old_auto_id_collection_is_rejected_without_drop(self):
        store = SimpleNamespace(col=SimpleNamespace(schema=SimpleNamespace(auto_id=True)))
        kb = KnowledgeBase()
        kb.backend = "milvus"
        with patch("app.rag.retriever.build_vector_store", return_value=store):
            with self.assertRaisesRegex(RuntimeError, "自动主键"):
                kb._ensure_store()

    def test_milvus_first_insert_then_idempotent_upsert(self):
        class MilvusStore(Store):
            col = None
            upserts = 0
            def add_documents(self, docs, ids=None):
                self.col = object()
                super().add_documents(docs, ids)
            def upsert(self, ids, documents):
                if self.col is None:
                    raise AssertionError("未创建集合就调用 upsert")
                self.upserts += 1
                super().upsert(ids, documents)
        store = MilvusStore()
        kb = self.make_kb(store=store)
        kb.backend = "milvus"
        kb.ingest_text("a.txt", "context")
        kb.ingest_text("b.txt", "channel")
        kb.ingest_text("b.txt", "channel")
        self.assertEqual(store.upserts, 1)
        self.assertEqual(len(store.rows), 2)

    def test_persistent_upload_restore_and_idempotency(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "kb.sqlite3"
            first = self.make_kb(path)
            self.assertEqual(first.ingest_text("notes.txt", "context cancellation"), 1)
            self.assertEqual(first.ingest_text("notes.txt", "context cancellation"), 0)
            first.close()
            second = self.make_kb(path)
            self.assertEqual(second.restore(), 1)
            self.assertEqual(second.restore(), 0)
            self.assertEqual(second.chunk_count, 1)
            self.assertEqual(second.search_bm25("context")[0].metadata["title"], "notes.txt")
            second.close()

    def test_vector_failure_keeps_local_indexes_atomic_and_recoverable(self):
        with tempfile.TemporaryDirectory() as tmp:
            kb = self.make_kb(Path(tmp) / "kb.sqlite3")
            kb._store.fail = True
            with patch("app.rag.retriever.invoke_with_retry", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
                with self.assertRaises(RuntimeError):
                    kb.ingest_text("a.txt", "context")
            self.assertEqual(kb.chunk_count, 0)
            self.assertFalse(kb.bm25_ready)
            kb._store.fail = False
            self.assertEqual(kb.restore(), 1)
            self.assertEqual(kb.chunk_count, len(kb._bm25._corpus))
            kb.close()

    def test_concurrent_ingest_search_and_duplicate(self):
        kb = self.make_kb()
        def work(i):
            kb.ingest_text(f"{i % 12}.txt", f"context topic{i % 12}")
            kb.search_bm25("context")
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(work, range(80)))
        self.assertEqual(kb.chunk_count, 12)
        self.assertEqual(len(kb._store.rows), 12)
        self.assertEqual(len(kb._bm25._corpus), 12)

    def test_bm25_tokenizes_only_new_documents(self):
        with patch("app.rag.lexical.tokenize", side_effect=lambda t: t.split()) as tokenize:
            index = BM25Index()
            index.add_documents(["a b", "b c"])
            index.add_documents(["d"])
            self.assertEqual(tokenize.call_count, 3)
            self.assertEqual(index.search("d", 3), [2])

    def test_incremental_bm25_equals_batch_and_empty_is_safe(self):
        docs = ["", "a b", "a c", "b b", "d"]
        a, b = BM25Index(), BM25Index()
        for d in docs:
            a.add_documents([d])
        b.add_documents(docs)
        for query in ["a", "b", "c d", "absent", ""]:
            self.assertEqual(a.search(query, 5), b.search(query, 5))


class CacheTests(unittest.IsolatedAsyncioTestCase):
    def test_cache_isolation_and_exact_guard(self):
        cache = SemanticCache()
        cache.put([1, 0], {"reply": "ok"}, "context", namespace="a", revision=1)
        self.assertIsNone(cache.get([1, 0], "context", namespace="b", revision=1))
        self.assertIsNone(cache.get([1, 0], "context", namespace="a", revision=2))
        self.assertIsNone(cache.get([1, 0], "context 文章点赞", namespace="a", revision=1, exact=True))
        self.assertEqual(cache.get([1, 0], "context", namespace="a", revision=1)["reply"], "ok")

    def test_dynamic_failure_and_mixed_tools_never_cached(self):
        def result(names, ok=True):
            return {"sources": ["s"], "steps": [
                *[{"type": "tool_call", "tool": n} for n in names],
                *[{"type": "tool_result", "tool": n, "ok": ok} for n in names]]}
        self.assertTrue(chat_module._cacheable(result(["search_knowledge"])))
        for names, ok in [(["query_article"], True), (["search_knowledge", "query_article"], True),
                          (["search_knowledge"], False), ([], True)]:
            self.assertFalse(chat_module._cacheable(result(names, ok)))

    async def test_cache_hits_write_memory_for_json_and_sse(self):
        async def lookup(*args):
            return [1], {"reply": "缓存答案", "sources": ["s"]}, 1, True
        with patch.object(settings, "llm_api_key", "fake"), patch.object(chat_module, "_cache_lookup", lookup):
            for streaming in [False, True]:
                sid = f"cached-{streaming}"
                memory.clear(sid)
                if streaming:
                    events = [e async for e in chat_module.stream_chat("问题", sid)]
                    self.assertTrue(events[-1]["cache_hit"])
                else:
                    self.assertTrue((await chat_module.chat("问题", sid))["cache_hit"])
                self.assertEqual(memory.get_messages(sid)[-1].content, "缓存答案")
                memory.clear(sid)

    async def test_cache_lookup_hits_rephrased_question_inside_account(self):
        """改写提问应在同一账户内命中缓存；exact 精确匹配会让语义缓存彻底失去收益。"""
        vector, namespace = [1.0, 0.0], "acct-cache"
        revision = getattr(chat_module.kb, "revision", 0)
        session = f"{namespace}:session-1"
        semantic_cache.clear()
        memory.clear(session)
        semantic_cache.put(vector, {"reply": "语义答案", "sources": ["s#0"]},
                           "Go 的 context 如何取消", namespace=namespace, revision=revision)
        try:
            with patch.object(settings, "cache_enabled", True), \
                 patch.object(settings, "embedding_api_key", "fake"), \
                 patch.object(chat_module.kb, "embed_query", lambda _m: vector):
                _, hit, _, checked = await chat_module._cache_lookup(
                    "Go 并发代码里 context 怎么取消任务", session)
        finally:
            semantic_cache.clear()
        self.assertTrue(checked)
        self.assertIsNotNone(hit, "改写提问未命中，语义缓存退化为精确匹配")
        self.assertEqual(hit["reply"], "语义答案")

    async def test_knowledge_tool_returns_raw_evidence_without_llm(self):
        docs = [Document(page_content="原文资料", metadata={"doc_id": "doc#0"})]
        with patch.object(tools.kb, "search_detailed", return_value=(docs, {"vector_hits": 1})):
            result = json.loads(await tools.search_knowledge_tool.ainvoke({"query": "问题"}))
        self.assertNotIn("answer", result)
        self.assertEqual(result["chunks"], [{"text": "原文资料", "source": "doc#0"}])


class AsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_thread_cancellation_waits_before_cleanup(self):
        entered, leave = threading.Event(), threading.Event()
        completed = []
        def job():
            entered.set()
            leave.wait(2)
            completed.append(True)
        task = asyncio.create_task(run_blocking(job))
        await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        leave.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(completed, [True])

    async def test_consumer_pending_retry_concurrency_and_event_loop(self):
        entered = threading.Event()
        class KB:
            chunk_count = 0
            attempts = 0
            def ingest_article(self, *args, **kwargs):
                entered.set()
                time.sleep(0.04)
                self.attempts += 1
                if self.attempts == 1:
                    raise RuntimeError("临时故障")
                self.chunk_count = 1
                return 1
        class Client:
            async def get_article_detail(self, n):
                return {"title": "a", "content": "b"}
        kb = KB()
        consumer = ArticleIngestConsumer(kb, Client(), state_path=":memory:")
        task = asyncio.create_task(consumer.handle_event({"article_id": 1}))
        await asyncio.to_thread(entered.wait, 1)
        self.assertFalse(task.done())
        self.assertEqual(await task, "skipped")
        self.assertEqual(consumer._article_status(1), "pending")
        results = await asyncio.gather(*[consumer.handle_event({"article_id": 1}) for _ in range(5)])
        self.assertEqual(results.count("ingested"), 1)
        self.assertEqual(results.count("duplicate"), 4)
        self.assertEqual(kb.attempts, 2)
        consumer.close()

    async def test_consumer_retries_are_bounded_and_back_off(self):
        """回归：下游宕机时可恢复失败必须有限重投并退避，不能形成高速重投风暴。"""
        class KB:
            chunk_count = 0
            def ingest_article(self, *args, **kwargs):
                self.chunk_count += 1
                return 1
        class FlakyClient:
            down = True
            async def get_article_detail(self, _n):
                if FlakyClient.down:
                    raise RuntimeError("Go 文章服务不可用")
                return {"title": "a", "content": "b", "summary": "", "tags": []}
        consumer = ArticleIngestConsumer(KB(), FlakyClient(), state_path=":memory:")
        message = SimpleNamespace(body=b'{"article_id": 7, "event_id": "e-7"}')
        self.assertEqual(RetryLater("x", 2.5).delay, 2.5)
        self.assertIsInstance(RetryLater("x"), RuntimeError)  # 兼容按 RuntimeError 捕获的调用方
        try:
            with patch.object(settings, "amqp_max_retries", 3), \
                 patch.object(settings, "amqp_retry_backoff_seconds", 1.0), \
                 patch.object(settings, "amqp_retry_max_backoff_seconds", 8.0):
                delays = []
                for _ in range(2):
                    with self.assertRaises(RetryLater) as ctx:
                        await consumer._process_delivery(message)
                    delays.append(ctx.exception.delay)
                # 第 3 次达到上限：改为登记待重放并放行（消息被 ack，不再无限重投）
                await consumer._process_delivery(message)
                self.assertEqual(delays, [1.0, 2.0])
                self.assertEqual(consumer.failed_event_count, 1)
                FlakyClient.down = False
                await consumer._process_delivery(message)   # 下游恢复后重放成功
                self.assertEqual(consumer.failed_event_count, 0)
                self.assertEqual(consumer._attempts, {})   # 重投计数随成功归零
        finally:
            consumer.close()

    async def test_stream_tokens_arrive_before_final_generation_completes(self):
        release = asyncio.Event()
        class Model:
            def bind_tools(self, tools):
                return self
            async def ainvoke(self, messages):
                return AIMessage(content="不能泄露的规划文本")
            async def astream(self, messages):
                yield AIMessageChunk(content="第一段")
                await release.wait()
                yield AIMessageChunk(content="第二段")
        sid = "early-stream"
        memory.clear(sid)
        with patch.object(graph, "get_llm", return_value=Model()), \
             patch.object(settings, "llm_api_key", "fake"), patch.object(settings, "cache_enabled", False):
            stream = chat_module.stream_chat("问题", sid)
            events = []
            while not any(e["type"] == "token" for e in events):
                events.append(await asyncio.wait_for(anext(stream), 2))
            self.assertEqual(events[-1]["content"], "第一段")
            self.assertEqual(memory.get_messages(sid), [])
            release.set()
            events.extend([e async for e in stream])
        self.assertEqual("".join(e["content"] for e in events if e["type"] == "token"), "第一段第二段")
        self.assertEqual(memory.get_messages(sid)[-1].content, "第一段第二段")
        memory.clear(sid)

    async def test_stream_failure_does_not_commit_partial_answer(self):
        class Model:
            def bind_tools(self, tools):
                return self
            async def ainvoke(self, messages):
                return AIMessage(content="完成")
            async def astream(self, messages):
                yield AIMessageChunk(content="部分答案")
                raise RuntimeError("流中断")
        sid = "failed-stream"
        memory.clear(sid)
        with patch.object(graph, "get_llm", return_value=Model()), \
             patch.object(settings, "llm_api_key", "fake"), patch.object(settings, "cache_enabled", False):
            events = [e async for e in chat_module.stream_chat("问题", sid)]
        self.assertEqual(sum(e["type"] == "error" for e in events), 1)
        self.assertEqual(memory.get_messages(sid), [])

    async def test_closing_stream_cancels_graph_without_committing_memory(self):
        closed = asyncio.Event()
        class Model:
            def bind_tools(self, tools):
                return self
            async def ainvoke(self, messages):
                return AIMessage(content="完成")
            async def astream(self, messages):
                try:
                    yield AIMessageChunk(content="部分")
                    await asyncio.Event().wait()
                finally:
                    closed.set()
        sid = "cancel-stream"
        memory.clear(sid)
        with patch.object(graph, "get_llm", return_value=Model()), \
             patch.object(settings, "llm_api_key", "fake"), patch.object(settings, "cache_enabled", False):
            stream = chat_module.stream_chat("问题", sid)
            while (await anext(stream))["type"] != "token":
                pass
            await stream.aclose()
            await asyncio.wait_for(closed.wait(), 2)
        self.assertEqual(memory.get_messages(sid), [])


class SecurityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.patches = [patch.object(settings, "admin_token", "admin-secret"),
                        patch.object(settings, "ai_internal_token", "gateway-secret"),
                        patch.object(settings, "ratelimit_enabled", False)]
        for p in self.patches:
            p.start()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test")
        self.admin = {"Authorization": "Bearer admin-secret"}
        self.gateway = {"X-Internal-Token": "gateway-secret", "X-Account-Id": "1"}

    async def asyncTearDown(self):
        await self.client.aclose()
        for p in reversed(self.patches):
            p.stop()

    async def test_anonymous_and_forged_identity_rejected(self):
        for headers in [{}, {"X-Account-Id": "1"}, {**self.gateway, "X-Internal-Token": "wrong"}]:
            response = await self.client.post("/api/v1/chat", headers=headers, json={"message": "hi"})
            self.assertEqual(response.status_code, 401)
        with patch.object(settings, "admin_token", ""), patch.object(settings, "ai_internal_token", ""):
            self.assertEqual((await self.client.get("/api/v1/stats")).status_code, 503)

    async def test_gateway_cannot_access_management_and_admin_can(self):
        self.assertEqual((await self.client.get("/api/v1/stats", headers=self.gateway)).status_code, 403)
        self.assertEqual((await self.client.get("/api/v1/traces", headers=self.admin)).status_code, 200)
        self.assertEqual((await self.client.get("/api/v1/traces?limit=100000", headers=self.admin)).status_code, 422)

    async def test_accounts_sessions_and_generated_ids_are_isolated(self):
        keys = []
        async def fake_chat(message, sid):
            keys.append(sid)
            return {"reply": "ok"}
        with patch.object(main, "chat", fake_chat):
            for account in ["1", "2", "1"]:
                response = await self.client.post("/api/v1/chat",
                    headers={**self.gateway, "X-Account-Id": account},
                    json={"message": "hi", "session_id": "same"})
                self.assertEqual(response.status_code, 200)
            a = await self.client.post("/api/v1/chat", headers=self.admin, json={"message": "hi"})
            b = await self.client.post("/api/v1/chat", headers=self.admin, json={"message": "hi"})
        self.assertNotEqual(keys[0], keys[1])
        self.assertEqual(keys[0], keys[2])
        self.assertNotEqual(a.json()["session_id"], b.json()["session_id"])
        self.assertEqual(session_identity("account/1", "same")[1], keys[0])

    async def test_concurrent_same_session_returns_conflict_then_releases(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def fake_chat(message, sid):
            entered.set()
            await release.wait()
            return {"reply": "ok"}
        args = {"headers": self.admin, "json": {"message": "hi", "session_id": "busy"}}
        with patch.object(main, "chat", fake_chat):
            first = asyncio.create_task(self.client.post("/api/v1/chat", **args))
            await entered.wait()
            second = await self.client.post("/api/v1/chat", **args)
            self.assertEqual(second.status_code, 409)
            release.set()
            self.assertEqual((await first).status_code, 200)
            self.assertEqual((await self.client.post("/api/v1/chat", **args)).status_code, 200)

    async def test_upload_size_before_parser_and_original_title(self):
        with patch.object(settings, "max_upload_bytes", 8), patch.object(settings, "embedding_api_key", "fake"):
            # 边界文件允许 multipart 开销，但文件内容本身不能超过上限。
            with patch.object(main.kb, "ingest_file", return_value=1) as ingest:
                response = await self.client.post("/api/v1/ingest", headers=self.admin,
                                                   files={"file": ("notes.txt", b"12345678")})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(ingest.call_args.args[1], "notes.txt")
                self.assertFalse(ingest.call_args.args[0].exists())
                response = await self.client.post("/api/v1/ingest", headers=self.admin,
                                                   files={"file": ("notes.txt", b"123456789")})
                self.assertEqual(response.status_code, 413)
                self.assertEqual(ingest.call_count, 1)
            async def chunks():
                yield b"x" * 40000
                yield b"x" * 40000
            response = await self.client.post("/api/v1/ingest", headers=self.admin, content=chunks())
            self.assertEqual(response.status_code, 413)

    async def test_json_body_limit_before_parser(self):
        """回归：非上传类接口的请求体也必须在 Pydantic 解析前限量。"""
        seen = []
        async def fake_chat(message, sid):
            seen.append(message)
            return {"reply": "ok"}
        oversized = "x" * (settings.max_request_bytes + 1024)
        with patch.object(main, "chat", fake_chat):
            response = await self.client.post("/api/v1/chat", headers=self.admin,
                                              json={"message": "hi"})
            self.assertEqual(response.status_code, 200, response.text)
            response = await self.client.post("/api/v1/chat", headers=self.admin,
                                              json={"message": oversized})
            self.assertEqual(response.status_code, 413)   # 不是 422：解析前就被拦截
            async def chunks():
                for _ in range(5):
                    yield b"x" * 100000
            response = await self.client.post("/api/v1/chat", headers=self.admin, content=chunks())
            self.assertEqual(response.status_code, 413)   # 无 Content-Length 的分块请求
        self.assertEqual(seen, ["hi"])

    async def test_stream_session_lock_released_on_completion(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def fake_stream(message, sid):
            entered.set()
            yield {"type": "token", "content": "a"}
            await release.wait()
            yield {"type": "done"}
        args = {"headers": self.admin, "json": {"message": "hi", "session_id": "stream-busy"}}
        with patch.object(main, "stream_chat", fake_stream):
            first = asyncio.create_task(self.client.post("/api/v1/chat/stream", **args))
            await entered.wait()
            self.assertEqual((await self.client.post("/api/v1/chat/stream", **args)).status_code, 409)
            release.set()
            response = await first
            self.assertEqual(response.status_code, 200)
            self.assertIn('"session_id": "stream-busy"', response.text)
            self.assertEqual((await self.client.post("/api/v1/chat/stream", **args)).status_code, 200)


if __name__ == "__main__":
    unittest.main()
