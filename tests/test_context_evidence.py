"""P3 查询复用与证据可见性、版本、权限和预算。"""
import asyncio
import json
import pytest
from langchain_core.messages import ToolMessage
from app.config import settings
from app.context.evidence import retrieve,search_key,visible
from app.context.tool_projection import project
from app.context.store import close_stores
from app.context.usage import ledger,discard


@pytest.fixture
def context(monkeypatch,tmp_path):
    monkeypatch.setattr(settings,"context_store_path",str(tmp_path/"context.sqlite3"))
    yield
    close_stores()


def test_retrieve_reuses_only_same_scope_args_and_revision(context,monkeypatch):
    class Search:
        calls=0
        async def ainvoke(self,args):
            self.calls+=1
            return json.dumps({"chunks":[{"text":"事实","source":"doc#1"}],"sources":["doc#1"]})
    async def run():
        tool=Search()
        for session,args,revision in [("a:s",{"query":"cancel"},1),("a:s",{"query":"cancel"},1),
                                      ("a:s",{"query":"不要 cancel"},1),("a:s",{"query":"cancel"},2),
                                      ("b:s",{"query":"cancel"},1),("a:other",{"query":"cancel"},1)]:
            await retrieve(tool,args,session=session,run_id="reuse-test",revision=revision)
        assert tool.calls==5
        assert ledger("reuse-test").context["retrieval_reused"]==1
        monkeypatch.setattr(settings,"context_evidence_ttl",-1)
        await retrieve(tool,{"query":"cancel"},session="a:s",run_id="reuse-test",revision=1)
        assert tool.calls==6;discard("reuse-test")
    asyncio.run(run())
    assert search_key({"query":"A"},1,"boot1")!=search_key({"query":"A"},1,"boot2")


def test_duplicate_body_not_repeated_and_total_budget(context,monkeypatch):
    monkeypatch.setattr(settings,"context_evidence_tokens",200)
    raw={"chunks":[{"text":"相同资料。"*50,"source":"doc#1"},{"text":"相同资料。"*50,"source":"doc#2"}],"sources":["doc#1","doc#2"]}
    first=project("search_knowledge",raw,session="a:s",run_id="dedup",args={"query":"资料"})
    assert sum("text" in c for c in first["chunks"])==1
    messages=[ToolMessage(content=json.dumps(first,ensure_ascii=False),tool_call_id="c1")]
    second=project("search_knowledge",raw,session="a:s",run_id="dedup",args={"query":"资料"},messages=messages)
    assert all("text" not in c for c in second["chunks"])
    _,n=visible([*messages,ToolMessage(content=json.dumps(second,ensure_ascii=False),tool_call_id="c2")])
    assert n<=200
    assert second["sources"]==raw["sources"]


def test_same_evidence_in_new_turn_has_visible_body(context):
    raw={"chunks":[{"text":"需要正文","source":"doc#1"}],"sources":["doc#1"]}
    first=project("search_knowledge",raw,session="a:s",run_id="r1",args={})
    second=project("search_knowledge",raw,session="a:s",run_id="r2",args={},messages=[])
    assert first["chunks"][0]["evidence_id"]==second["chunks"][0]["evidence_id"]
    assert second["chunks"][0]["text"]=="需要正文"
