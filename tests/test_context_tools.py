"""P2 验证模型实际收到投影、原文可补读及权限限制。"""
import asyncio
import json
import pytest
from app.config import settings
from app.context.tool_projection import project,read_tool_result,tool_session
from app.context.token_counter import TokenCounter
from app.context.store import get_store,close_stores
from app.agents import graph
from langchain_core.messages import HumanMessage,AIMessage,ToolMessage


@pytest.fixture
def context(monkeypatch,tmp_path):
    from test_context_foundation import calibration
    monkeypatch.setattr(settings,"context_mode","enforce")
    monkeypatch.setattr(settings,"context_store_path",str(tmp_path/"context.sqlite3"))
    monkeypatch.setattr(settings,"context_model_window",32768)
    monkeypatch.setattr(settings,"context_calibration_path",calibration(tmp_path))
    yield
    close_stores()


def test_tool_json_projection_and_tail_preservation(context):
    raw={"chunks":[{"text":"普通背景。"*2000+"重要结论：超时 250ms。","source":"doc#1"}],"sources":["doc#1"],"retrieval":{"large":"x"*10000}}
    result=project("search_knowledge",raw,session="a:s",run_id="r",args={"query":"超时"})
    assert "250ms" in result["chunks"][0]["text"] and result["truncated"]
    assert TokenCounter().text(json.dumps(result,ensure_ascii=False,separators=(",",":")))<=settings.context_tool_tokens
    record=get_store().result("a","a:s",result["result_id"])
    assert record["data"]==raw


def test_read_original_scope_and_limit(context):
    raw={"answer":"需要保留的原文。"*1000,"sources":["doc#1"]}
    result=project("unknown",raw,session="a:s",run_id="r",args={})
    async def run():
        token=tool_session.set("b:s")
        try:assert json.loads(await read_tool_result.ainvoke({"result_id":result["result_id"]}))["status"]=="error"
        finally:tool_session.reset(token)
        token=tool_session.set("a:s")
        try:
            data=json.loads(await read_tool_result.ainvoke({"result_id":result["result_id"],"field":"answer"}))
            assert data["next_offset"] and data["truncated"]
            assert TokenCounter().text(json.dumps(data,ensure_ascii=False,separators=(",",":")))<=settings.context_read_tokens
        finally:tool_session.reset(token)
    asyncio.run(run())


def test_article_projection_preserves_requested_values(context):
    raw={"article":{"id":12,"title":"标题","likes_count":7,"comments_count":8,"content":"全文"*5000},"sources":["article:12"],"queried_at":123}
    result=project("query_article",raw,session="a:s",run_id="r",args={"message":"文章12有多少点赞"})
    assert result["article"]=={"id":12,"title":"标题","likes_count":7}
    assert result["queried_at"]==123 and result["truncated"]


def test_actual_graph_receives_short_tool_message(context,monkeypatch):
    from langchain_core.tools import tool
    @tool("search_knowledge")
    async def search(query:str)->str:
        """返回长测试证据。"""
        return json.dumps({"answer":"背景。"*10000+"必须保留 250ms。","sources":["doc#1"]},ensure_ascii=False)
    captured=[]
    class Model:
        def bind_tools(self,tools):return self
        async def ainvoke(self,messages):
            captured.extend(m for m in messages if isinstance(m,ToolMessage))
            if captured:return AIMessage(content="完成")
            return AIMessage(content="",tool_calls=[{"name":"search_knowledge","args":{"query":"250ms"},"id":"call1"}])
    monkeypatch.setattr(graph,"get_llm",lambda:Model())
    monkeypatch.setitem(graph._tools_by_name,"search_knowledge",search)
    result=asyncio.run(graph.get_agent_graph().ainvoke({"messages":[HumanMessage(content="查询")],"session_id":"a:s","run_id":"projection-test","tool_rounds":0}))
    assert result["final"]=="完成" and captured
    assert len(captured[0].content)<2000
    assert "250ms" in captured[0].content
