# -*- coding: utf-8 -*-
"""FastAPI 入口：知识导入、LangGraph Agent 对话与运行观测。"""
import json
import logging
import secrets
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from app.config import settings
from app.rag.retriever import kb
from app.schemas import ChatRequest, ChatResponse, IngestResponse, StatsResponse
from app.services.article_consumer import ArticleIngestConsumer
from app.services.chat import chat, stream_chat
from app.services.go_client import go_client
from app.services.ratelimit import limiter
from app.services.semantic_cache import semantic_cache
from app.services.tracing import traces

BASE_DIR = Path(__file__).resolve().parent.parent
logger = logging.getLogger("airobot.main")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """启动时导入示例知识库并拉起文章入库消费者；关闭时释放资源。"""
    sample = BASE_DIR / "data" / "knowledge_base.md"
    if sample.exists() and kb.chunk_count == 0:
        try:
            kb.ingest_file(sample)
        except Exception as exc:
            logger.warning("启动时导入示例知识库失败（请检查 AIROBOT_EMBEDDING_API_KEY）: %s", exc)
    consumer = ArticleIngestConsumer(kb, go_client)
    await consumer.restore()
    consumer_task = await consumer.start()
    yield
    if consumer_task is not None:
        await consumer.stop()
    consumer.close()
    await go_client.aclose()


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
        key = None
        token = request.headers.get("X-Internal-Token", "")
        if settings.ai_internal_token and secrets.compare_digest(
                token.encode(), settings.ai_internal_token.encode()):
            key = request.headers.get("X-Account-Id") or None
        if key is None:
            key = request.client.host if request.client else "unknown"
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


@app.get("/health")
def health():
    return {"status": "ok", "llm_model": settings.llm_model,
            "embedding_model": settings.embedding_model, "engine": "langgraph"}


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
def traces_api(limit: int = 50):
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
        if declared_length > settings.max_upload_bytes:
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
        chunks = kb.ingest_file(tmp_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"解析失败: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)
    return IngestResponse(file_name=file.filename or "unknown", chunks=chunks,
                          total_chunks=kb.chunk_count)


@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat_ep(req: ChatRequest):
    result = await chat(req.message, req.session_id or "default")
    return ChatResponse(**result)


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.post("/api/v1/chat/stream")
async def chat_stream(req: ChatRequest):
    """SSE 版本消费与 ``/chat`` 相同的 LangGraph Agent Run。"""
    async def generate():
        async for event in stream_chat(req.message, req.session_id or "default"):
            yield _sse(event)

    return StreamingResponse(generate(), media_type="text/event-stream")
