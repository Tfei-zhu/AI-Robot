# -*- coding: utf-8 -*-
"""对话编排服务（异步版）：
1) 优先 CrewAI 多智能体（未安装/异常时自动降级，多 Agent 在独立线程运行）；
2) 降级路径：LangChain 意图分类路由 + RAG/工具；
3) 所有路径带会话记忆（session_id），支持多轮上下文。
"""
import asyncio
import json
import logging
import time

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI

from app.agents.tools import CREW_TOOLS_READY, query_article
from app.config import settings
from app.rag.retriever import aanswer_with_rag, kb
from app.services.resilience import ainvoke_with_retry
from app.services.semantic_cache import semantic_cache
from app.services.memory import format_history, memory
from app.services.tracing import traces

logger = logging.getLogger("airobot.chat")

INTENT_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "你是 Go 文章社区助手的意图分类器，只输出 JSON：{{\"intent\": \"knowledge|article|chat\", \"reason\": \"简短理由\"}}。"
     "article 用于查询指定文章的状态或数据；knowledge 用于 Go 技术、发文与社区规则问题。"),
    ("human", "{message}"),
])

CHAT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "你是 Go 文章社区助手，语气友好、准确、简洁。帮助用户阅读和发布 Go 技术文章、理解社区规范；不确定时如实说明。"),
    MessagesPlaceholder("history"),
    ("human", "{message}"),
])

_llm_cache: dict = {}


def get_llm() -> ChatOpenAI:
    key = (settings.llm_model, settings.llm_base_url, settings.llm_api_key)
    if key not in _llm_cache:
        _llm_cache[key] = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key or "sk-placeholder-not-configured",
            base_url=settings.llm_base_url,
            temperature=0.3,
        )
    return _llm_cache[key]


async def classify_intent(message: str) -> str:
    chain = INTENT_PROMPT | get_llm() | StrOutputParser()
    raw = await ainvoke_with_retry(chain.ainvoke, {"message": message})
    try:
        data = json.loads(raw.strip().strip("`"))
        return data.get("intent", "chat")
    except Exception:
        logger.warning("意图 JSON 解析失败，默认 chat: %s", raw[:80])
        return "chat"


async def fallback_chat(message: str, session_id: str) -> dict:
    """内置路由：不依赖 CrewAI，逻辑与 Crew 中 Task 一致；带会话记忆。"""
    history = memory.get_messages(session_id)
    intent = await classify_intent(message)
    if intent == "article":
        reply = await query_article(message)
        return {"reply": reply, "intent": intent, "sources": [], "engine": "langchain"}
    if intent == "knowledge":
        answer, sources = await aanswer_with_rag(message, get_llm(), history)
        return {"reply": answer, "intent": intent, "sources": sources, "engine": "langchain"}
    chain = CHAT_PROMPT | get_llm() | StrOutputParser()
    reply = await ainvoke_with_retry(chain.ainvoke, {"message": message, "history": history})
    return {"reply": reply, "intent": "chat", "sources": [], "engine": "langchain"}


def _maybe_cache(query_vec: list | None, result: dict, message: str = "") -> None:
    """动态文章数据不缓存；无上下文问题才写入语义缓存。"""
    if query_vec is not None and result.get("intent") != "article":
        semantic_cache.put(query_vec, result, message)


async def chat(message: str, session_id: str = "default") -> dict:
    """对话入口：CrewAI 优先（线程池执行），失败自动降级内置路由；成功后写入会话记忆。"""
    entry = {"message": message[:80], "session_id": session_id, "status": 200}
    t_start = time.perf_counter()
    if not settings.llm_api_key:
        traces.record({**entry, "intent": "no-key", "total_ms": 0.0})
        return {"reply": "未配置 AIROBOT_LLM_API_KEY，请复制 .env.example 为 .env 并填入密钥。",
                "intent": None, "sources": [], "engine": "langchain"}

    # 语义缓存：仅无上下文的首轮问题参与命中/写入（避免与会话记忆耦合）
    query_vec = None
    if settings.cache_enabled and settings.embedding_api_key and not memory.get_messages(session_id):
        t_cache = time.perf_counter()
        query_vec = await asyncio.to_thread(kb.embed_query, message)
        cached = semantic_cache.get(query_vec, message)
        entry["cache_lookup_ms"] = round((time.perf_counter() - t_cache) * 1000, 1)
        entry["cache_checked"] = True
        if cached is not None:
            entry.update(cache_hit=True, intent=cached.get("intent"),
                         total_ms=round((time.perf_counter() - t_start) * 1000, 1))
            traces.record(entry)
            return {**cached, "cache_hit": True}
    else:
        entry["cache_lookup_ms"] = 0.0

    t_llm = time.perf_counter()
    if settings.use_crew and CREW_TOOLS_READY:
        try:
            history_text = format_history(memory.get_messages(session_id))
            from app.agents.crew import run_crew
            reply = await asyncio.to_thread(run_crew, message, history_text)
            result = {"reply": reply, "intent": "crew", "sources": [],
                      "engine": "crew", "used_crew": True}
            entry.update(intent="crew", engine="crew",
                         llm_ms=round((time.perf_counter() - t_llm) * 1000, 1),
                         sources=0, total_ms=round((time.perf_counter() - t_start) * 1000, 1))
            _maybe_cache(query_vec, result, message)
            memory.add(session_id, message, reply)
            traces.record(entry)
            return result
        except Exception as exc:  # CrewAI 调用失败 -> 降级
            logger.warning("CrewAI 调用失败，降级到内置路由: %s", exc)

    result = await fallback_chat(message, session_id)
    entry.update(intent=result.get("intent"), engine=result.get("engine"),
                 llm_ms=round((time.perf_counter() - t_llm) * 1000, 1),
                 sources=len(result.get("sources", [])),
                 total_ms=round((time.perf_counter() - t_start) * 1000, 1))
    _maybe_cache(query_vec, result, message)
    memory.add(session_id, message, result["reply"])
    traces.record(entry)
    return result
