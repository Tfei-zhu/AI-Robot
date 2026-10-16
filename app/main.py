# -*- coding: utf-8 -*-
"""FastAPI 入口：知识导入、LangGraph Agent 对话与运行观测。"""
import json
import logging
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, Query
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import settings
from app.rag.retriever import kb
from app.schemas import ChatRequest, ChatResponse, IngestResponse, StatsResponse
from app.services.article_consumer import ArticleIngestConsumer
from app.services.chat import chat, stream_chat
from app.services.go_client import go_client
from app.services.ratelimit import limiter
from app.services.semantic_cache import semantic_cache
from app.services.tracing import traces
from app.services.concurrency import run_blocking
from app.services.security import (SecurityMiddleware, SessionStreamResponse,
                                   session_identity, claim_session, release_session)
from app.go_validation.contracts import GoTaskRequest, GoTaskResult
from app.go_validation.service import service as go_service, store as go_store
from contextlib import aclosing
from app.context.contracts import ContextBudgetExceeded
import hashlib

BASE_DIR = Path(__file__).resolve().parent.parent
logger = logging.getLogger("airobot.main")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """启动时导入示例知识库并拉起文章入库消费者；关闭时释放资源。"""
    if settings.admin_token and settings.admin_token == settings.ai_internal_token:
        raise RuntimeError("管理员令牌与网关令牌必须不同")
    from app.context.token_counter import validate_config
    validate_config()
    await run_blocking(kb.restore)
    sample = BASE_DIR / "data" / "knowledge_base.md"
    if sample.exists() and kb.chunk_count == 0:
        try:
            await run_blocking(kb.ingest_file, sample)
        except Exception as exc:
            logger.warning("启动时导入示例知识库失败（请检查 AIROBOT_EMBEDDING_API_KEY）: %s", exc)
    consumer = ArticleIngestConsumer(kb, go_client)
    app.state.consumer = consumer  # 供 /health 上报放弃重投的文章数
    try:
        await consumer.restore()
        await consumer.start()
        yield
    finally:
        await consumer.stop()
        consumer.close()
        await run_blocking(kb.close)
        await go_client.aclose()
        await run_blocking(go_store.close)
        from app.context.store import close_stores
        await run_blocking(close_stores)


app = FastAPI(
    title="Go 文章社区 Agent（FastAPI + LangGraph + RAG）",
    version="2.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info("%s %s -> %s (%.1f ms)", request.method, request.url.path,
                response.status_code, elapsed_ms)
    response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.1f}"
    return response


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """按账户（可信 Go 网关）或客户端 IP 实施滑动窗口限流。"""
    if (settings.ratelimit_enabled and request.url.path.startswith("/api/v1")
            and request.url.path not in ("/api/v1/stats", "/api/v1/traces")):
        key = request.state.principal
        if not limiter.allow(key):
            logger.warning("限流拦截: %s %s from %s", request.method, request.url.path, key)
            traces.record({"message": f"{request.method} {request.url.path}",
                           "session_id": key, "intent": "ratelimited",
                           "status": 429, "cache_checked": False, "total_ms": 0.0})
            return JSONResponse(status_code=429, content={"detail": "请求过于频繁，请稍后再试。"})
    return await call_next(request)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("未处理异常: %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "服务内部错误，请稍后重试。"})


@app.exception_handler(ContextBudgetExceeded)
async def context_budget_error(request:Request,exc:ContextBudgetExceeded):
    return JSONResponse(status_code=422,content={"detail":{"code":exc.code,"message":str(exc)}})


@app.get("/health")
def health():
    # ingest_failed_events > 0 表示有文章连续重投失败已停止重试，需人工或重启重放
    return {"status": "ok", "llm_model": settings.llm_model,
            "embedding_model": settings.embedding_model, "engine": "langgraph",
            "ingest_failed_events": getattr(getattr(app.state, "consumer", None),
                                            "failed_event_count", 0)}


@app.get("/api/v1/stats", response_model=StatsResponse)
def stats():
    cache = semantic_cache.stats()
    rl = limiter.stats()
    return StatsResponse(
        total_chunks=kb.chunk_count,
        llm_model=settings.llm_model,
        embedding_model=settings.embedding_model,
        agent_engine="langgraph",
        agent_max_tool_rounds=settings.agent_max_tool_rounds,
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
    html = (BASE_DIR / "app" / "static" / "dashboard.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.get("/api/v1/traces")
def traces_api(limit: int = Query(default=50, ge=1, le=200)):
    return {"entries": traces.recent(limit), "summary": traces.summary()}


@app.post("/api/v1/ingest", response_model=IngestResponse)
async def ingest(request: Request, file: UploadFile = File(...)):
    if not settings.embedding_api_key:
        raise HTTPException(status_code=400, detail="未配置 AIROBOT_EMBEDDING_API_KEY，无法向量化入库")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".pdf", ".docx", ".md", ".markdown", ".txt"}:
        raise HTTPException(status_code=400, detail="仅支持 PDF、DOCX、Markdown 和 TXT 文件")
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_length = int(content_length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Content-Length 无效") from exc
        if declared_length > settings.max_upload_bytes + 64 * 1024:
            raise HTTPException(status_code=413, detail=f"文件过大，上传上限为 {settings.max_upload_bytes} 字节")
    content = bytearray()
    while True:
        chunk = await file.read(min(1024 * 1024, settings.max_upload_bytes + 1 - len(content)))
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail=f"文件过大，上传上限为 {settings.max_upload_bytes} 字节")
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        chunks = await run_blocking(kb.ingest_file, tmp_path, Path(file.filename or "upload").name)
    except Exception as exc:
        logger.exception("文档入库失败")
        raise HTTPException(status_code=500, detail="文档入库失败，请稍后重试") from exc
    finally:
        tmp_path.unlink(missing_ok=True)
    return IngestResponse(file_name=file.filename or "unknown", chunks=chunks,
                          total_chunks=kb.chunk_count)


@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat_ep(req: ChatRequest, request: Request):
    public, key = session_identity(request.state.principal, req.session_id)
    claim_session(key)
    try:
        result = await chat(req.message, key)
        return ChatResponse(**result, session_id=public)
    finally:
        release_session(key)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.post("/api/v1/chat/stream")
async def chat_stream(req: ChatRequest, request: Request):
    """SSE 版本消费与 ``/chat`` 相同的 LangGraph Agent Run。"""
    public, key = session_identity(request.state.principal, req.session_id)
    claim_session(key)
    async def generate():
        async for event in stream_chat(req.message, key):
            if event.get("type") == "done":
                event["session_id"] = public
            yield _sse(event)

    return SessionStreamResponse(generate(), session_key=key, media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/v1/go/tasks", response_model=GoTaskResult)
async def go_task(req: GoTaskRequest, request: Request):
    principal = request.state.principal
    _, key = session_identity(principal, req.session_id)
    claim_session(key)
    try:
        return await go_service.run(req, principal, key)
    finally:
        release_session(key)


@app.post("/api/v1/go/tasks/stream")
async def go_task_stream(req: GoTaskRequest, request: Request):
    principal = request.state.principal
    _, key = session_identity(principal, req.session_id)
    claim_session(key)
    async def generate():
        async with aclosing(go_service.stream(req, principal, key)) as events:
            async for event in events:
                yield _sse(event)
    return SessionStreamResponse(generate(), session_key=key, media_type="text/event-stream",
                                  headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/v1/go/tasks/{run_id}", response_model=GoTaskResult)
async def get_go_task(run_id: str, request: Request):
    owner = hashlib.sha256(request.state.principal.encode()).hexdigest()
    result = await run_blocking(go_store.get, run_id, owner)
    if result is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return result


# 最外层：在限流、解析上传文件及业务路由之前验证身份。
app.add_middleware(SecurityMiddleware)
