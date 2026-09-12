# -*- coding: utf-8 -*-
"""LangGraph Agent 离线单测：图结构与 SSE 执行事件映射。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402
from langchain_core.messages import AIMessageChunk

import app.agents.graph as graph_module  # noqa: E402
from app.agents.graph import get_agent_graph  # noqa: E402
from app.config import settings  # noqa: E402
from app.services.chat import _sources, _step_events, stream_chat  # noqa: E402


def test_graph_has_agent_tool_and_finalize_nodes():
    graph = get_agent_graph().get_graph()
    assert {"agent", "tools", "finalize"}.issubset(graph.nodes)


def test_agent_sse_events_keep_tool_metadata():
    events = _step_events({"type": "tool_call", "tool": "search_knowledge", "args": {"query": "context"}})
    assert events[0]["type"] == "stage" and events[0]["stage"] == "tool"
    assert events[1]["type"] == "tool_call"
    assert events[1]["tool"] == "search_knowledge"


def test_sources_are_ordered_and_deduplicated():
    assert _sources(["a#1", "b#2", "a#1", ""]) == ["a#1", "b#2"]


def test_graph_runs_a_tool_loop_without_a_real_model():
    """规划 -> 工具 -> 整合必须来自同一张图，且不需要模型网络调用。"""
    class FakeBoundModel:
        async def ainvoke(self, messages):
            if any(isinstance(item, ToolMessage) for item in messages):
                return AIMessage(content="请遵守社区规范。")
            return AIMessage(content="", tool_calls=[{
                "name": "community_guideline", "args": {"question": "发文规则"}, "id": "call-1"
            }])

    class FakeModel:
        def bind_tools(self, _tools):
            return FakeBoundModel()

        async def ainvoke(self, _messages):
            return AIMessage(content="请遵守社区规范。")

    original = graph_module.get_llm
    graph_module.get_llm = lambda: FakeModel()
    try:
        state = asyncio.run(get_agent_graph().ainvoke({
            "messages": [HumanMessage(content="发文要注意什么？")], "session_id": "test",
            "run_id": "test-run", "sources": [], "steps": [], "tool_rounds": 0,
        }))
    finally:
        graph_module.get_llm = original

    assert state["final"] == "请遵守社区规范。"
    assert state["sources"] == ["community_guideline"]
    assert any(step["type"] == "tool_call" for step in state["steps"])
    assert any(step["type"] == "tool_result" and step["ok"] for step in state["steps"])


def test_sse_consumes_the_same_agent_tool_loop():
    class FakeBoundModel:
        async def ainvoke(self, messages):
            if any(isinstance(item, ToolMessage) for item in messages):
                return AIMessage(content="请遵守社区规范。")
            return AIMessage(content="", tool_calls=[{
                "name": "community_guideline", "args": {"question": "发文规则"}, "id": "stream-call"
            }])

    class FakeModel:
        def bind_tools(self, _tools):
            return FakeBoundModel()

        async def ainvoke(self, _messages):
            return AIMessage(content="请遵守社区规范。")

    async def collect():
        return [event async for event in stream_chat("发文要注意什么？", "stream-agent-test")]

    original_llm = graph_module.get_llm
    async def fake_stream(self, messages):
        yield AIMessageChunk(content="请遵守社区规范。")
    FakeModel.astream = fake_stream
    original_key, original_cache = settings.llm_api_key, settings.cache_enabled
    graph_module.get_llm = lambda: FakeModel()
    settings.llm_api_key, settings.cache_enabled = "test-key", False
    try:
        events = asyncio.run(collect())
    finally:
        graph_module.get_llm = original_llm
        settings.llm_api_key, settings.cache_enabled = original_key, original_cache

    assert any(event["type"] == "tool_call" for event in events)
    done = next(event for event in events if event["type"] == "done")
    assert done["sources"] == ["community_guideline"]
    assert any(event["type"] == "token" and event["content"] == "请遵守社区规范。" for event in events)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
