"""离线 Agent 路径门禁：执行真实 LangGraph，替换模型与外部工具。

这不是回答质量评分；真实模型的质量评测使用 run_eval.py --agent。
"""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from app.agents import graph
from app.config import settings


async def evaluate():
    rows = []
    for case in ("knowledge", "article", "combined", "failure", "budget", "direct"):
        calls = []

        @tool("search_knowledge")
        async def knowledge(query: str) -> str:
            """返回测试知识原文。"""
            if case == "failure":
                raise RuntimeError("测试检索失败")
            return json.dumps({"chunks": [{"text": "context 用于取消任务", "source": "guide#0"}],
                               "sources": ["guide#0"]}, ensure_ascii=False)

        @tool("query_article")
        async def article(message: str) -> str:
            """返回测试文章数据。"""
            return json.dumps({"answer": "文章 12 点赞 7", "sources": ["article:12"]})

        class Model:
            def bind_tools(self, tools):
                return self

            async def ainvoke(self, messages):
                calls.append(messages)
                used = any(isinstance(m, ToolMessage) for m in messages)
                forced = "不得再调用任何工具" in str(messages[0].content)
                if forced or case == "direct" or (used and case != "budget"):
                    return AIMessage(content="context 用于取消任务；文章 12 点赞 7。")
                names = (["search_knowledge", "query_article"] if case == "combined"
                         else ["query_article"] if case == "article" else ["search_knowledge"])
                return AIMessage(content="", tool_calls=[
                    {"name": n, "args": {"query": "context"} if n == "search_knowledge"
                     else {"message": "文章 12"}, "id": f"call-{len(calls)}-{i}"}
                    for i, n in enumerate(names)])

        with patch.object(graph, "get_llm", return_value=Model()), \
             patch.object(graph, "_tools_by_name", {"search_knowledge": knowledge, "query_article": article}), \
             patch.object(settings, "agent_max_tool_rounds", 2):
            state = await graph.get_agent_graph().ainvoke({
                "messages": [HumanMessage(content=case)], "sources": [], "steps": [], "tool_rounds": 0})
        expected = (["guide#0", "article:12"] if case == "combined" else ["article:12"]
                    if case == "article" else [] if case in ("direct", "failure") else ["guide#0"])
        assert list(dict.fromkeys(state["sources"])) == expected, case
        assert state["final"], case
        assert state["tool_rounds"] <= 2, case
        if case == "failure":
            assert any(s.get("ok") is False for s in state["steps"]), case
        if case == "budget":
            assert len(calls) == 3, case  # 两轮工具规划 + 最终生成，预算耗尽不再规划
        rows.append({"case": case, "passed": True, "model_calls": len(calls),
                     "tool_rounds": state["tool_rounds"], "sources": expected})
    return rows


if __name__ == "__main__":
    print(json.dumps(asyncio.run(evaluate()), ensure_ascii=False, indent=2))
