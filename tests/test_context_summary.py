"""P5 摘要只覆盖提交历史，草稿成功提交、失败/取消不破坏原文。"""
import asyncio
import json
import pytest
from langchain_core.messages import AIMessage
from app.config import settings
from app.context import summary,session
from app.context.store import get_store,close_stores
from app.context.contracts import scope,ContextBudgetExceeded
from app.context.builder import build
from app.services.chat import _initial_state,_cache_lookup
from langchain_core.messages import SystemMessage
from test_context_foundation import calibration


@pytest.fixture
def context(monkeypatch,tmp_path):
    for key,value in {"context_mode":"enforce","context_model_window":32768,"context_calibration_path":calibration(tmp_path),
                      "context_store_path":str(tmp_path/"summary.sqlite3"),"context_history_tokens":500,
                      "context_history_enabled":True,"context_summary_enabled":True}.items():monkeypatch.setattr(settings,key,value)
    store=get_store()
    for i in range(12):store.commit("a","a:s",f"r{i}",f"第{i}轮要求只用标准库，编号CTX。"*4,"确认。"*4)
    yield store
    close_stores()


class Summarizer:
    async def ainvoke(self,messages):
        payload=json.loads(messages[-1].content)
        first=payload["new_committed_turns"][0]["turn"]
        return AIMessage(content=json.dumps({"constraints":[{"text":"只用标准库；编号CTX","source_turns":[first],"active":True}],
                                             "evidence_refs":[]},ensure_ascii=False))


def test_summary_draft_only_commits_with_completed_reply(context):
    async def run():
        state=await summary.prepare(_initial_state("当前问题","a:s","summary-run"),Summarizer())
        assert context.summary("a","a:s") is None
        assert state["context_summary"]["covered_until_turn"]<12
        output=build(state,SystemMessage(content="规则"),state["messages"])
        assert any("编号CTX" in str(m.content) for m in output)
        session.commit("a:s","summary-run","当前问题","最终回复")
        assert context.summary("a","a:s")["version"]==1
        assert len(context.turns("a","a:s"))==13
        summary.discard("summary-run")
    asyncio.run(run())


def test_failed_summary_does_not_silently_drop_history(context):
    class Bad:
        async def ainvoke(self,messages):return AIMessage(content='{"constraints":[{"text":"错误","source_turns":[999]}]}')
    async def run():
        original=_initial_state("当前问题","a:s","bad-summary")
        state=await summary.prepare(original,Bad())
        assert state==original and context.summary("a","a:s") is None
        with pytest.raises(ContextBudgetExceeded,match="未被摘要覆盖"):build(state,SystemMessage(content="规则"),state["messages"])
        assert len(context.turns("a","a:s"))==12
    asyncio.run(run())


def test_summary_cancel_discards_draft_and_preserves_turns(context):
    class Cancel:
        async def ainvoke(self,messages):raise asyncio.CancelledError
    async def run():
        with pytest.raises(asyncio.CancelledError):await summary.prepare(_initial_state("问题","a:s","cancel-summary"),Cancel())
        assert summary.draft("cancel-summary") is None and context.summary("a","a:s") is None
        assert len(context.turns("a","a:s"))==12
    asyncio.run(run())


def test_persisted_history_is_not_first_turn_cache(context,monkeypatch):
    monkeypatch.setattr(settings,"cache_enabled",True)
    monkeypatch.setattr(settings,"embedding_api_key","fixture")
    result=asyncio.run(_cache_lookup("问题","a:s"))
    assert result[-1] is False


def test_off_rollback_recovers_recent_originals(context,monkeypatch):
    from app.services.memory import memory
    memory.clear("a:s")
    monkeypatch.setattr(settings,"context_mode","off")
    state=_initial_state("继续","a:s","rollback")
    assert state["context_history_count"]==12
    assert "第11轮" in state["messages"][-3].content
    assert len(context.turns("a","a:s"))==12
    memory.clear("a:s")


def test_stream_cancel_after_summary_does_not_commit_draft(context,monkeypatch):
    from app.agents import graph
    from app.services.chat import stream_chat
    from langchain_core.messages import AIMessageChunk
    monkeypatch.setattr(settings,"cache_enabled",False)
    monkeypatch.setattr(settings,"llm_api_key","fixture")
    class Model(Summarizer):
        def bind(self,**kwargs):return self
        def bind_tools(self,tools):return self
        async def ainvoke(self,messages):
            if "整理已经完成" in messages[0].content:return await super().ainvoke(messages)
            return AIMessage(content="完成")
        async def astream(self,messages):
            yield AIMessageChunk(content="半条回复")
            await asyncio.sleep(5)
    monkeypatch.setattr(graph,"get_llm",lambda:Model())
    async def run():
        events=stream_chat("继续","a:s")
        while True:
            item=await anext(events)
            if item["type"]=="token":break
        await events.aclose()
        assert context.summary("a","a:s") is None
        assert len(context.turns("a","a:s"))==12
    asyncio.run(run())


def test_previous_active_constraint_cannot_disappear(context):
    from app.context.contracts import SessionSummary
    from app.context.token_counter import TokenCounter
    previous={"version":1,"covered_until_turn":1,"constraints":[{"text":"必须标准库","source_turns":[1],"active":True}]}
    candidate=SessionSummary(version=2,covered_until_turn=2)
    summary.validate(candidate,previous,context.turns("a","a:s")[1:2],TokenCounter(),"a:s")
    assert candidate.constraints[0].text=="必须标准库"
    candidate.constraints[0].active=False
    with pytest.raises(ValueError,match="用户纠正"):
        summary.validate(candidate,previous,context.turns("a","a:s")[1:2],TokenCounter(),"a:s")


def test_summary_retry_receives_validation_error(context):
    class Repair(Summarizer):
        count=0
        async def ainvoke(self,messages):
            self.count+=1
            if self.count==1:return AIMessage(content='{"evidence_refs":["invalid-source-title"]}')
            assert "摘要引用未知证据" in messages[-1].content
            assert '"previous_invalid_output"' in messages[-1].content
            return await super().ainvoke(messages)
    async def run():
        model=Repair();state=await summary.prepare(_initial_state("当前问题","a:s","repair-summary"),model)
        assert model.count==2 and state.get("context_summary")
        assert context.summary("a","a:s") is None
        summary.discard("repair-summary")
    asyncio.run(run())


def test_summary_cannot_discard_constraints_to_meet_length(context,monkeypatch):
    from app.context.contracts import SessionSummary
    from app.context.token_counter import TokenCounter
    constraints=[{"text":f"必须遵守第{i}项完整接口约束"*20,"source_turns":[1],"active":True} for i in range(20)]
    previous={"version":1,"covered_until_turn":1,"constraints":constraints}
    candidate=SessionSummary(version=2,covered_until_turn=2)
    with pytest.raises(ValueError,match="长度额度"):
        summary.validate(candidate,previous,context.turns("a","a:s")[1:2],TokenCounter(),"a:s")
    assert len(candidate.constraints)==20


def test_explicit_correction_deactivates_old_instead_of_adding_it_back(context):
    from app.context.contracts import SessionSummary
    from app.context.token_counter import TokenCounter
    context.commit("a","a:s","correction-user","纠正版本，改为 Go 1.25.0，其他要求不变","已记录")
    row=context.turns("a","a:s")[-1]
    previous={"version":1,"covered_until_turn":12,"constraints":[{"text":"Go 1.26.2","source_turns":[1],"active":True},
                                                                  {"text":"只用标准库","source_turns":[1],"active":True}]}
    candidate=SessionSummary(version=2,covered_until_turn=13,constraints=[{"text":"Go 1.25.0","source_turns":[13]}],
        corrections=[{"text":"版本改为1.25.0","source_turns":[13],"supersedes":["Go 1.26.2"]}])
    summary.validate(candidate,previous,[row],TokenCounter(),"a:s")
    active=[c.text for c in candidate.constraints if c.active]
    assert "Go 1.25.0" in active and "只用标准库" in active and "Go 1.26.2" not in active
    assert any(c.text=="Go 1.26.2" and not c.active for c in candidate.constraints)


def test_first_summary_handles_correction_without_previous_constraint(context):
    from app.context.contracts import SessionSummary
    from app.context.token_counter import TokenCounter
    context.commit("a","a:s","initial-correction","纠正版本，改为 Go 1.25.0","已记录")
    rows=context.turns("a","a:s")
    candidate=SessionSummary(version=1,covered_until_turn=13,
        constraints=[{"text":"Go 1.25.0","source_turns":[13]}],
        corrections=[{"text":"版本改为1.25.0","source_turns":[13],"supersedes":["Go 1.26.2"]}])
    summary.validate(candidate,None,rows,TokenCounter(),"a:s")
    assert candidate.corrections[0].supersedes==[]
    assert [c.text for c in candidate.constraints if c.active]==["Go 1.25.0"]


def test_validated_correction_survives_later_summary_without_reactivating_old(context):
    from app.context.contracts import SessionSummary
    from app.context.token_counter import TokenCounter
    previous={"version":1,"covered_until_turn":2,
        "constraints":[{"text":"Go 1.26.2","source_turns":[1,2],"active":False},
                       {"text":"Go 1.25.0","source_turns":[2],"active":True}],
        "corrections":[{"text":"版本改为1.25.0","source_turns":[2],"supersedes":["Go 1.26.2"]}]}
    candidate=SessionSummary(version=2,covered_until_turn=3,
        constraints=[{"text":"Go 1.26.2","source_turns":[1]}],corrections=previous["corrections"])
    summary.validate(candidate,previous,context.turns("a","a:s")[2:3],TokenCounter(),"a:s")
    assert [c.text for c in candidate.constraints if c.active]==["Go 1.25.0"]


def test_unknown_supersedes_has_no_power_to_remove_existing_constraints(context):
    from app.context.contracts import SessionSummary
    from app.context.token_counter import TokenCounter
    previous={"version":1,"covered_until_turn":1,
        "constraints":[{"text":"必须标准库","source_turns":[1],"active":True}]}
    candidate=SessionSummary(version=2,covered_until_turn=2,
        corrections=[{"text":"插入话题不修改原要求","source_turns":[2],"supersedes":["插入话题不修改原要求"]}])
    summary.validate(candidate,previous,context.turns("a","a:s")[1:2],TokenCounter(),"a:s")
    assert candidate.corrections==[]
    assert [c.text for c in candidate.constraints if c.active]==["必须标准库"]
    candidate.constraints[0].active=False
    with pytest.raises(ValueError,match="用户纠正"):
        summary.validate(candidate,previous,context.turns("a","a:s")[1:2],TokenCounter(),"a:s")


def test_fact_evidence_refs_are_collected_and_scope_checked(context):
    from app.context.contracts import SessionSummary
    from app.context.token_counter import TokenCounter
    ref=context.save_result("a","a:s","evidence-run",{"data":{"answer":"250ms"}})
    data={"version":1,"covered_until_turn":1,"confirmed_facts":[{"text":"超时250ms","source_turns":[1],"evidence_refs":[ref]}]}
    candidate=SessionSummary.model_validate(data)
    summary.validate(candidate,None,context.turns("a","a:s")[:1],TokenCounter(),"a:s")
    assert candidate.evidence_refs==[ref]
    foreign=context.save_result("b","b:s","foreign-run",{"data":{"answer":"私有资料"}})
    data["confirmed_facts"][0]["evidence_refs"]=[foreign]
    with pytest.raises(ValueError,match="未知证据"):
        summary.validate(SessionSummary.model_validate(data),None,context.turns("a","a:s")[:1],TokenCounter(),"a:s")


def test_misplaced_supersedes_is_validated_as_correction_not_silently_ignored(context):
    from app.context.contracts import SessionSummary
    from app.context.token_counter import TokenCounter
    previous={"version":1,"covered_until_turn":1,
        "constraints":[{"text":"必须标准库","source_turns":[1],"active":True}]}
    data={"version":2,"covered_until_turn":2,
        "constraints":[{"text":"允许第三方库","source_turns":[2],"supersedes":["必须标准库"]}]}
    candidate=SessionSummary.model_validate(summary.normalize(data))
    # 第2轮没有用户纠正，移动字段不能授予模型撤销权限。
    with pytest.raises(ValueError,match="用户纠正"):
        summary.validate(candidate,previous,context.turns("a","a:s")[1:2],TokenCounter(),"a:s")
    assert candidate.corrections[0].supersedes==["必须标准库"]


def test_first_summary_discards_assistant_suggestion_mislabeled_as_user_correction(context):
    from app.context.contracts import SessionSummary
    from app.context.token_counter import TokenCounter
    context.commit("a","a:s","actual-correction","纠正版本：改为Go 1.25.0，其他要求不变","已记录")
    data={"version":1,"covered_until_turn":13,
        "constraints":[{"text":"Go 1.25.0","source_turns":[13]},{"text":"只用标准库","source_turns":[1]}],
        "corrections":[{"text":"版本改为Go 1.25.0","source_turns":[13],"supersedes":["Go 1.26.2"]},
                       {"text":"日志使用slog.With","source_turns":[2],"supersedes":["日志旧建议"]}]}
    item=SessionSummary.model_validate(data)
    summary.validate(item,None,context.turns("a","a:s"),TokenCounter(),"a:s")
    assert [c.text for c in item.corrections]==["版本改为Go 1.25.0"]
    assert [c.text for c in item.constraints if c.active]==["Go 1.25.0","只用标准库"]
    data["corrections"][1]["source_turns"]=[999]
    with pytest.raises(ValueError):
        summary.validate(SessionSummary.model_validate(data),None,context.turns("a","a:s"),TokenCounter(),"a:s")
