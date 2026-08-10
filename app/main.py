# -*- coding: utf-8 -*-
"""FastAPI 入口：健康检查 / 知识导入 / 对话 / SSE 流式对话。
含请求日志中间件与统一异常兜底；chat 接口为异步实现（ainvoke / astream）。
"""
import asyncio
import json
import logging
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from app.agents.tools import CREW_TOOLS_READY
from app.config import settings
from app.rag.retriever import kb
from app.schemas import ChatRequest, ChatResponse, IngestResponse, StatsResponse
from app.services.chat import CHAT_PROMPT, chat, classify_intent
from app.services.ratelimit import limiter
from app.services.semantic_cache import semantic_cache
from app.services.tracing import traces

BASE_DIR = Path(__file__).resolve().parent.parent
logger = logging.getLogger("airobot.main")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """启动时自动导入示例知识库，保证开箱即用。"""
    sample = BASE_DIR / "data" / "knowledge_base.md"
    if sample.exists() and kb.chunk_count == 0:
        try:
            kb.ingest_file(sample)
        except Exception as exc:
            logger.warning("启动时导入示例知识库失败（请检查 AIROBOT_EMBEDDING_API_KEY）: %s", exc)
    yield


app = FastAPI(
    title="AI Robot 智能客服服务（FastAPI + LangChain RAG + CrewAI 多 Agent）",
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """请求日志 + 耗时统计（后续可接 OpenTelemetry / 指标埋点）。"""
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info("%s %s -> %s (%.1f ms)", request.method, request.url.path,
                response.status_code, elapsed_ms)
    response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.1f}"
    return response


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """接口限流：滑动窗口（按 IP，60 秒），返回 JSON 429。"""
    if (settings.ratelimit_enabled and request.url.path.startswith("/api/v1")
            and request.url.path not in ("/api/v1/stats", "/api/v1/traces")):
        client_ip = request.client.host if request.client else "unknown"
        if not limiter.allow(client_ip):
            logger.warning("限流拦截: %s %s from %s", request.method, request.url.path, client_ip)
            traces.record({"message": f"{request.method} {request.url.path}",
                           "session_id": client_ip, "intent": "ratelimited",
                           "status": 429, "cache_checked": False, "total_ms": 0.0})
            return JSONResponse(status_code=429, content={"detail": "请求过于频繁，请稍后再试。"})
    return await call_next(request)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """统一异常兜底：非流式接口返回 JSON 500，避免堆栈泄露给客户端。"""
    logger.exception("未处理异常: %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "服务内部错误，请稍后重试。"})


@app.get("/health")
def health():
    return {"status": "ok", "llm_model": settings.llm_model,
            "embedding_model": settings.embedding_model}


@app.get("/api/v1/stats", response_model=StatsResponse)
def stats():
    cache = semantic_cache.stats()
    rl = limiter.stats()
    return StatsResponse(
        total_chunks=kb.chunk_count,
        llm_model=settings.llm_model,
        embedding_model=settings.embedding_model,
        use_crew=settings.use_crew,
        crew_available=CREW_TOOLS_READY,
        hybrid_enabled=settings.hybrid_enabled,
        bm25_ready=kb.bm25_ready,
        rerank_enabled=settings.rerank_enabled,
        cache_enabled=settings.cache_enabled,
        cache_size=cache["size"],
        cache_hits=cache["hits"],
        cache_misses=cache["misses"],
        cache_threshold=cache["threshold"],
        ratelimit_enabled=settings.ratelimit_enabled,
        ratelimit_per_minute=rl["limit_per_minute"],
        ratelimit_blocked=rl["blocked"],
    )


@app.get("/dashboard")
def dashboard():
    """可视化控制台：功能导览 + 实时请求监控（页面轮询 /api/v1/stats 与 /api/v1/traces）。"""
    html = (BASE_DIR / "app" / "static" / "dashboard.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.get("/api/v1/traces")
def traces_api(limit: int = 50):
    """链路追踪：最近请求各阶段耗时 + 聚合统计（P95 / 缓存命中率 / 限流拦截数）。"""
    return {"entries": traces.recent(limit), "summary": traces.summary()}


@app.post("/api/v1/ingest", response_model=IngestResponse)
async def ingest(file: UploadFile = File(...)):
    if not settings.embedding_api_key:
        raise HTTPException(status_code=400, detail="未配置 AIROBOT_EMBEDDING_API_KEY，无法向量化入库")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".pdf", ".docx", ".md", ".txt", ".markdown"):
        raise HTTPException(status_code=400, detail="仅支持 pdf / docx / md / txt")
    content = await file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        chunks = kb.ingest_file(tmp_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"解析失败: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)
    return IngestResponse(file_name=file.filename or "unknown",
                          chunks=chunks, total_chunks=kb.chunk_count)


@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat_ep(req: ChatRequest):
    result = await chat(req.message, req.session_id)
    return ChatResponse(
        reply=result["reply"],
        intent=result.get("intent"),
        sources=result.get("sources", []),
        engine=result.get("engine", "langchain"),
        used_crew=result.get("used_crew", False),
        cache_hit=result.get("cache_hit", False),
    )


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.post("/api/v1/chat/stream")
async def chat_stream(req: ChatRequest):
    """SSE 流式对话：意图 -> (RAG/闲聊) 逐 token 输出；订单查询整段返回；带会话记忆。"""

    async def _error(message: str):
        yield _sse({"type": "token", "content": message})
        yield _sse({"type": "done"})

    if not settings.llm_api_key:
        return StreamingResponse(_error("未配置 AIROBOT_LLM_API_KEY，请复制 .env.example 为 .env。"),
                                 media_type="text/event-stream")

    from langchain_core.output_parsers import StrOutputParser

    from app.agents.tools import query_order
    from app.rag.retriever import RAG_PROMPT, build_llm
    from app.services.memory import memory

    async def gen():
        t_start = time.perf_counter()
        entry = {"message": req.message[:80], "session_id": req.session_id,
                 "status": 200, "engine": "sse"}
        try:
            yield _sse({"type": "stage", "stage": "rate_limit",
                        "msg": "限流检查通过，请求进入服务", "ms": 0.0, "ok": True})
            history = memory.get_messages(req.session_id)
            query_vec = None
            if settings.cache_enabled and settings.embedding_api_key and not history:
                t_cache = time.perf_counter()
                yield _sse({"type": "stage", "stage": "cache", "msg": "语义缓存查询中…", "ms": 0.0})
                query_vec = await asyncio.to_thread(kb.embed_query, req.message)
                cached = semantic_cache.get(query_vec, req.message)
                cache_ms = round((time.perf_counter() - t_cache) * 1000, 1)
                entry["cache_lookup_ms"] = cache_ms
                entry["cache_checked"] = True
                if cached is not None:
                    entry.update(cache_hit=True, intent=cached.get("intent"), tokens=1,
                                 total_ms=round((time.perf_counter() - t_start) * 1000, 1))
                    traces.record(entry)
                    yield _sse({"type": "stage", "stage": "cache", "msg": "语义缓存命中，直接返回",
                                "ms": cache_ms, "hit": True, "ok": True})
                    yield _sse({"type": "intent", "intent": cached.get("intent")})
                    yield _sse({"type": "token", "content": cached["reply"]})
                    yield _sse({"type": "stage", "stage": "write", "msg": "命中缓存，无需写入",
                                "ms": 0.0, "ok": True})
                    yield _sse({"type": "done", "cache_hit": True, "intent": cached.get("intent"),
                                "sources": cached.get("sources", []),
                                "total_ms": entry["total_ms"]})
                    return
                yield _sse({"type": "stage", "stage": "cache", "msg": "语义缓存未命中", "ms": cache_ms,
                            "hit": False, "ok": True})
            else:
                reason = "未开启" if not (settings.cache_enabled and settings.embedding_api_key) else "多轮会话，跳过缓存"
                yield _sse({"type": "stage", "stage": "cache", "msg": f"跳过语义缓存（{reason}）",
                            "ms": 0.0, "ok": True, "skipped": True})
            t_intent = time.perf_counter()
            intent = await classify_intent(req.message)
            intent_ms = round((time.perf_counter() - t_intent) * 1000, 1)
            entry["intent_ms"] = intent_ms
            entry["intent"] = intent
            yield _sse({"type": "intent", "intent": intent})
            yield _sse({"type": "stage", "stage": "intent", "msg": f"意图识别为 {intent}",
                        "intent": intent, "ms": intent_ms, "ok": True})

            if intent == "order":
                t_tool = time.perf_counter()
                reply = query_order(req.message)
                tool_ms = round((time.perf_counter() - t_tool) * 1000, 1)
                yield _sse({"type": "stage", "stage": "tool", "tool": "query_order",
                            "msg": "调用订单查询工具 query_order", "ms": tool_ms, "ok": True})
                yield _sse({"type": "token", "content": reply})
                yield _sse({"type": "done", "intent": intent,
                            "total_ms": round((time.perf_counter() - t_start) * 1000, 1)})
                memory.add(req.session_id, req.message, reply)
                entry.update(tokens=1, llm_ms=tool_ms,
                             total_ms=round((time.perf_counter() - t_start) * 1000, 1))
                traces.record(entry)
                return

            if intent == "knowledge" and kb.chunk_count > 0:
                t_retr = time.perf_counter()
                docs, detail = await asyncio.to_thread(kb.search_detailed, req.message)
                retr_ms = round((time.perf_counter() - t_retr) * 1000, 1)
                entry["retrieval_ms"] = retr_ms
                entry["retrieval_detail"] = detail
                sources = [f"{d.metadata.get('title', '')}#{d.metadata.get('chunk', 0)}" for d in docs]
                yield _sse({"type": "stage", "stage": "retrieval", "msg": "混合检索完成",
                            "ms": retr_ms, "detail": detail, "sources": sources, "ok": True})
                context = "\n\n".join(d.page_content for d in docs)
                chain = RAG_PROMPT | build_llm() | StrOutputParser()
                parts: list[str] = []
                t_gen = time.perf_counter()
                async for chunk in chain.astream({"context": context, "question": req.message, "history": history}):
                    if chunk:
                        if not parts:
                            entry["first_token_ms"] = round(
                                (time.perf_counter() - t_start) * 1000, 1)
                        parts.append(chunk)
                        yield _sse({"type": "token", "content": chunk})
                llm_ms = round((time.perf_counter() - t_gen) * 1000, 1)
                entry["llm_ms"] = llm_ms
                entry["tokens"] = len(parts)
                yield _sse({"type": "stage", "stage": "generate",
                            "msg": f"RAG 生成完成（{len(parts)} tokens）", "ms": llm_ms,
                            "tokens": len(parts), "ok": True})
                yield _sse({"type": "stage", "stage": "write",
                            "msg": "写入会话记忆与语义缓存", "ms": 0.0, "ok": True})
                yield _sse({"type": "done", "intent": intent, "sources": sources,
                            "total_ms": round((time.perf_counter() - t_start) * 1000, 1)})
                memory.add(req.session_id, req.message, "".join(parts))
                if query_vec is not None:
                    semantic_cache.put(query_vec, {
                        "reply": "".join(parts), "intent": "knowledge",
                        "sources": sources, "engine": "langchain"}, req.message)
                entry.update(sources=len(sources),
                             total_ms=round((time.perf_counter() - t_start) * 1000, 1))
                traces.record(entry)
                return

            chain = CHAT_PROMPT | build_llm() | StrOutputParser()
            parts = []
            t_gen = time.perf_counter()
            async for chunk in chain.astream({"message": req.message, "history": history}):
                if chunk:
                    if not parts:
                        entry["first_token_ms"] = round(
                            (time.perf_counter() - t_start) * 1000, 1)
                    parts.append(chunk)
                    yield _sse({"type": "token", "content": chunk})
            llm_ms = round((time.perf_counter() - t_gen) * 1000, 1)
            entry["llm_ms"] = llm_ms
            entry["tokens"] = len(parts)
            yield _sse({"type": "stage", "stage": "generate",
                        "msg": f"闲聊生成完成（{len(parts)} tokens）", "ms": llm_ms,
                        "tokens": len(parts), "ok": True})
            yield _sse({"type": "stage", "stage": "write",
                        "msg": "写入会话记忆与语义缓存", "ms": 0.0, "ok": True})
            yield _sse({"type": "done", "intent": intent,
                        "total_ms": round((time.perf_counter() - t_start) * 1000, 1)})
            memory.add(req.session_id, req.message, "".join(parts))
            if query_vec is not None:
                semantic_cache.put(query_vec, {
                    "reply": "".join(parts), "intent": "chat",
                    "sources": [], "engine": "langchain"}, req.message)
            entry.update(total_ms=round((time.perf_counter() - t_start) * 1000, 1))
            traces.record(entry)
        except Exception as exc:
            logger.exception("流式对话异常: %s", exc)
            entry.update(status=500,
                         total_ms=round((time.perf_counter() - t_start) * 1000, 1))
            traces.record(entry)
            yield _sse({"type": "stage", "stage": "error", "msg": f"处理失败：{exc}", "ok": False})
            yield _sse({"type": "token", "content": f"服务开小差了：{exc}"})
            yield _sse({"type": "done"})
    return StreamingResponse(gen(), media_type="text/event-stream")
