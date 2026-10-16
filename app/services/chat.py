# -*- coding: utf-8 -*-
"""LangGraph Agent 的 HTTP 无关运行服务。

普通请求和 SSE 请求都通过同一张图执行，区别只在于调用方是否消费每个状态更新。
这样不会再出现流式接口绕过 Agent 编排的问题。
"""
import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Any

from langchain_core.messages import HumanMessage

from app.agents.graph import get_agent_graph
from app.config import settings
from app.rag.retriever import kb
from app.services.memory import memory
from app.services.semantic_cache import semantic_cache
from app.services.tracing import traces
from app.context import usage
from app.context import session as context_session
from app.services.concurrency import run_blocking

logger = logging.getLogger("airobot.agent")


def _sources(items: list[Any] | None) -> list[str]:
    """保留来源首次出现的顺序，避免多次工具调用产生重复引用。"""
    result: list[str] = []
    for item in items or []:
        source = str(item)
        if source and source not in result:
            result.append(source)
    return result


def _cache_namespace(session_id):
    base=session_id.split(":",1)[0]
    return base if settings.context_mode=="off" else base+":"+settings.context_mode+":"+settings.context_strategy_version


def _initial_state(message: str, session_id: str, run_id: str) -> dict[str, Any]:
    context_session.prepare(session_id, memory.get_messages(session_id,limit=memory.max_turns))
    history,start=context_session.history(session_id,memory.get_messages(session_id))
    return {
        "messages": [*history, HumanMessage(content=message)],
        "context_history_count":len(history),"context_history_start":start,
        "session_id": session_id,
        "run_id": run_id,
        "sources": [],
        "steps": [],
        "tool_rounds": 0,
    }


async def _prepared_state(message,session_id,run_id):
    from app.context.summary import prepare
    return await prepare(_initial_state(message,session_id,run_id))


async def _cache_lookup(message: str, session_id: str, run_id: str | None = None) -> tuple[list[float] | None, dict | None, float, bool]:
    """只为无历史会话的首轮请求使用语义缓存，失败时不影响 Agent 本身。"""
    if not (settings.cache_enabled and settings.embedding_api_key and not context_session.has_history(session_id,memory.get_messages(session_id))):
        return None, None, 0.0, False
    started = time.perf_counter()
    try:
        token=usage.current_run.set(run_id)
        try:vector = await run_blocking(kb.embed_query, message)
        finally:usage.current_run.reset(token)
        # 三层防护已足够：namespace 按账户哈希隔离（跨账户不可能命中）、revision 锁定
        # 知识库版本、get() 内再要求余弦与词面重叠双门限通过。因此这里不做 exact 精确
        # 匹配，否则改写提问（语义缓存的主要收益）永远不命中，等于关掉该特性。
        cached = await asyncio.to_thread(
            semantic_cache.get, vector, message, namespace=_cache_namespace(session_id),
            revision=getattr(kb, "revision", 0))
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        return vector, cached, elapsed, True
    except Exception as exc:
        logger.warning("语义缓存不可用，本次继续执行 Agent：%s", exc)
        return None, None, round((time.perf_counter() - started) * 1000, 1), False


def _result(state: dict[str, Any], run_id: str, cache_hit: bool = False) -> dict[str, Any]:
    return {
        "reply": str(state.get("final") or "抱歉，我没有生成有效答复。"),
        "intent": "agent",
        "sources": _sources(state.get("sources")),
        "engine": "langgraph",
        "run_id": run_id,
        "steps": state.get("steps", []),
        "cache_hit": cache_hit,
    }


def _cacheable(result: dict) -> bool:
    """默认不缓存；仅缓存具有来源、全部成功的纯知识检索回答。"""
    calls = [s.get("tool") for s in result.get("steps", []) if s.get("type") == "tool_call"]
    results = [s for s in result.get("steps", []) if s.get("type") == "tool_result"]
    return bool(result.get("sources") and calls and len(calls) == len(results)
                and all(t == "search_knowledge" for t in calls)
                and all(s.get("ok") for s in results))


def _cache_store(vector, result, message, session_id, revision):
    if vector is not None and _cacheable(result) and revision == getattr(kb, "revision", 0):
        semantic_cache.put(vector, {k: result[k] for k in ("reply", "intent", "sources", "engine")},
                           message, namespace=_cache_namespace(session_id), revision=revision)


def _trace(entry: dict[str, Any], result: dict[str, Any], started: float) -> None:
    measured = usage.ledger(entry["run_id"]).report()
    entry["context_usage"] = measured
    result["context_stats"] = measured
    result["token_usage"] = measured["token_usage"]
    context_session.persist_run(entry["session_id"],entry["run_id"],measured)
    entry.update(
        intent="agent",
        engine="langgraph",
        sources=len(result.get("sources", [])),
        tool_calls=sum(1 for step in result.get("steps", []) if step.get("type") == "tool_call"),
        total_ms=round((time.perf_counter() - started) * 1000, 1),
    )
    traces.record(entry)
    usage.discard(entry["run_id"])


def _failure_trace(entry,started,status):
    entry.update(status=status,total_ms=round((time.perf_counter()-started)*1000,1),
                 context_usage=usage.ledger(entry["run_id"]).report())
    traces.record(entry)
    context_session.persist_run(entry["session_id"],entry["run_id"],entry)


async def chat(message: str, session_id: str = "default") -> dict[str, Any]:
    """运行一次完整 LangGraph Agent，供普通 JSON 接口使用。"""
    run_id = uuid.uuid4().hex
    started = time.perf_counter()
    entry = {"message": message[:80], "session_id": session_id, "run_id": run_id, "status": 200}
    if not settings.llm_api_key:
        entry.update(intent="no-key", total_ms=0.0)
        traces.record(entry)
        return {"reply": "未配置 AIROBOT_LLM_API_KEY，请复制 .env.example 为 .env 并填入密钥。",
                "intent": None, "sources": [], "engine": "langgraph", "run_id": run_id,
                "steps": [], "cache_hit": False}

    try:
        revision = getattr(kb, "revision", 0)
        vector, cached, cache_ms, cache_checked = await _cache_lookup(message, session_id,run_id)
        entry.update(cache_lookup_ms=cache_ms, cache_checked=cache_checked)
        if cached is not None:
            result = {**cached, "engine": "langgraph", "intent": "agent", "run_id": run_id,
                      "steps": [{"type": "cache", "msg": "语义缓存命中"}], "cache_hit": True}
            entry["cache_hit"] = True
            context_session.commit(session_id,run_id,message,result["reply"])
            memory.add(session_id, message, result["reply"])
            _trace(entry, result, started)
            return result

        try:
            state = await get_agent_graph().ainvoke(await _prepared_state(message, session_id, run_id))
            result = _result(state, run_id)
            context_session.commit(session_id,run_id,message,result["reply"])
            memory.add(session_id, message, result["reply"])
            _cache_store(vector, result, message, session_id, revision)
            _trace(entry, result, started)
            return result
        except asyncio.CancelledError:
            _failure_trace(entry,started,499)
            raise
        except Exception:
            entry.update(status=500, intent="agent_error", total_ms=round((time.perf_counter() - started) * 1000, 1))
            entry["context_usage"] = usage.ledger(run_id).report()
            traces.record(entry)
            context_session.persist_run(session_id,run_id,entry)
            usage.discard(run_id)
            logger.exception("Agent 运行失败：run_id=%s", run_id)
            raise
        finally:
            from app.context.summary import discard
            discard(run_id)
            usage.discard(run_id)
    except (asyncio.CancelledError,GeneratorExit):
        # 首轮缓存与模型执行使用同一取消清理边界，避免在缓存阶段遗留计量。
        if "context_usage" not in entry:_failure_trace(entry,started,499)
        raise
    finally:
        usage.discard(run_id)
        from app.context.summary import discard
        discard(run_id)


def _step_events(step: dict[str, Any]) -> list[dict[str, Any]]:
    """将内部步骤映射为兼容现有 UI 的 stage 事件，并保留结构化 Agent 事件。"""
    kind = step.get("type")
    if kind == "retrieval":
        return [{"type": "stage", "stage": "retrieval", "msg": "知识检索完成",
                 "ok": step.get("ok", True), "sources": step.get("sources", []),
                 "detail": step.get("detail", {})}]
    if kind == "plan":
        return [{"type": "stage", "stage": "agent", "msg": step.get("msg", "Agent 正在规划"),
                 "ok": True}, {"type": "plan", **step}]
    if kind == "tool_call":
        tool = step.get("tool", "tool")
        return [{"type": "stage", "stage": "tool", "tool": tool,
                 "msg": f"Agent 调用工具 {tool}", "ok": True}, {"type": "tool_call", **step}]
    if kind == "tool_result":
        return [{"type": "stage", "stage": "tool", "tool": step.get("tool"),
                 "msg": step.get("msg", "工具调用完成"), "ok": step.get("ok", False)},
                {"type": "tool_result", **step}]
    if kind == "final":
        return [{"type": "stage", "stage": "generate", "msg": step.get("msg", "生成最终答复"),
                 "ok": True}]
    return []


async def stream_chat(message: str, session_id: str = "default") -> AsyncIterator[dict[str, Any]]:
    """流式消费同一张 LangGraph 图，逐步输出计划、工具与最终答复。"""
    run_id = uuid.uuid4().hex
    started = time.perf_counter()
    entry = {"message": message[:80], "session_id": session_id, "run_id": run_id, "status": 200}
    yield {"type": "stage", "stage": "rate_limit", "msg": "限流检查通过，请求进入 Agent", "ok": True}

    if not settings.llm_api_key:
        entry.update(intent="no-key", total_ms=0.0)
        traces.record(entry)
        yield {"type": "token", "content": "未配置 AIROBOT_LLM_API_KEY，请复制 .env.example 为 .env。"}
        yield {"type": "done", "run_id": run_id}
        return

    try:
        revision = getattr(kb, "revision", 0)
        vector, cached, cache_ms, cache_checked = await _cache_lookup(message, session_id,run_id)
        entry.update(cache_lookup_ms=cache_ms, cache_checked=cache_checked)
        if cached is not None:
            result = {**cached, "engine": "langgraph", "intent": "agent", "run_id": run_id,
                      "steps": [{"type": "cache", "msg": "语义缓存命中"}], "cache_hit": True}
            entry["cache_hit"] = True
            context_session.commit(session_id,run_id,message,result["reply"])
            memory.add(session_id, message, result["reply"])
            _trace(entry, result, started)
            yield {"type": "stage", "stage": "cache", "msg": "语义缓存命中，直接返回", "ms": cache_ms,
                   "hit": True, "ok": True}
            yield {"type": "token", "content": result["reply"]}
            yield {"type": "done", "run_id": run_id, "intent": "agent", "sources": result.get("sources", []),
                   "cache_hit": True, "total_ms": entry["total_ms"],
                   "context_stats": result["context_stats"], "token_usage": result["token_usage"]}
            return

        cache_reason = "未开启或不可用" if not cache_checked else "未命中"
        yield {"type": "stage", "stage": "cache", "msg": f"语义缓存{cache_reason}", "ms": cache_ms,
               "ok": True, "skipped": not cache_checked}
        yield {"type": "intent", "intent": "agent"}

        final_state: dict[str, Any] = {}
        collected_sources: list[Any] = []
        collected_steps: list[dict[str, Any]] = []
        try:
            async with aclosing(get_agent_graph().astream(
                {**await _prepared_state(message, session_id, run_id), "streaming": True},
                stream_mode=["updates", "custom"]
            )) as updates:
                async for mode, update in updates:
                    if mode == "custom":
                        if update.get("type") == "token":
                            entry.setdefault("first_token_ms", round((time.perf_counter() - started) * 1000, 1))
                            entry["stream_chunks"] = entry.get("stream_chunks", 0) + 1
                        yield update
                        continue
                    for node_update in update.values():
                        for step in node_update.get("steps", []):
                            collected_steps.append(step)
                            for event in _step_events(step):
                                yield event
                        collected_sources.extend(node_update.get("sources", []))
                        if node_update.get("final"):
                            final_state = node_update

            result = _result({**final_state, "sources": collected_sources, "steps": collected_steps}, run_id)
            context_session.commit(session_id,run_id,message,result["reply"])
            memory.add(session_id, message, result["reply"])
            _cache_store(vector, result, message, session_id, revision)
            _trace(entry, result, started)
            yield {"type": "stage", "stage": "write", "msg": "写入会话记忆与执行轨迹", "ok": True}
            yield {"type": "done", "run_id": run_id, "intent": "agent", "sources": result["sources"],
                   "total_ms": entry["total_ms"], "first_token_ms": entry.get("first_token_ms"),
                   "cache_hit": False, "context_stats": result["context_stats"], "token_usage": result["token_usage"]}
        except (asyncio.CancelledError,GeneratorExit):
            _failure_trace(entry,started,499)
            raise
        except Exception:
            entry.update(status=500, intent="agent_error", total_ms=round((time.perf_counter() - started) * 1000, 1))
            entry["context_usage"] = usage.ledger(run_id).report()
            traces.record(entry)
            context_session.persist_run(session_id,run_id,entry)
            usage.discard(run_id)
            logger.exception("Agent 流式运行失败：run_id=%s", run_id)
            import sys
            from app.context.contracts import ContextBudgetExceeded
            exc=sys.exception()
            yield {"type": "error", "msg": str(exc) if isinstance(exc,ContextBudgetExceeded) else "Agent 执行失败，请稍后重试。",
                   "code":exc.code if isinstance(exc,ContextBudgetExceeded) else "agent_error", "run_id": run_id}
            yield {"type": "done", "run_id": run_id}
        finally:
            # 断流也释放本次计量记录，完整报告由正常结束路径保存。
            usage.discard(run_id)
            from app.context.summary import discard
            discard(run_id)
    except (asyncio.CancelledError,GeneratorExit):
        # 首轮缓存与模型执行使用同一取消清理边界，避免在缓存阶段遗留计量。
        if "context_usage" not in entry:_failure_trace(entry,started,499)
        raise
    finally:
        usage.discard(run_id)
        from app.context.summary import discard
        discard(run_id)
