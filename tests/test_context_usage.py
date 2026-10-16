"""P0 计量：真实用量、未知用量、流事件及重试口径。"""
import asyncio
import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from app.context.usage import UsageLedger, invoke, ledger, discard, stream


def test_unknown_usage_is_not_zero():
    import time
    data = UsageLedger(); call=data.begin("planning", "fixture")
    data.finish(call, AIMessage(content="ok"), time.perf_counter())
    assert data.report()["token_usage"] is None
    assert data.report()["unknown_usage_calls"] == 1


def test_each_model_call_and_stream_usage():
    class Model:
        async def ainvoke(self, messages):
            return AIMessage(content="ok", usage_metadata={"input_tokens":10,"output_tokens":2,"total_tokens":12})
        async def astream(self, messages):
            yield AIMessageChunk(content="一")
            yield AIMessageChunk(content="二", usage_metadata={"input_tokens":20,"output_tokens":3,"total_tokens":23})
    async def run():
        await invoke(Model(), [], run_id="usage-test",stage="planning",model_name="fixture")
        chunks=[c async for c in stream(Model(), [],run_id="usage-test",stage="final",model_name="fixture")]
        result=ledger("usage-test").report();discard("usage-test")
        assert len(chunks)==2 and result["model_calls"]==2
        assert result["token_usage"]["total_tokens"]==35
    asyncio.run(run())


def test_cancel_is_recorded_without_fabricated_cost():
    class Slow:
        async def ainvoke(self, messages):
            raise asyncio.CancelledError
    async def run():
        with pytest.raises(asyncio.CancelledError):
            await invoke(Slow(), [],run_id="usage-cancel",stage="planning",model_name="fixture")
        assert ledger("usage-cancel").report()["calls"][0]["status"]=="cancelled"
        assert ledger("usage-cancel").report()["cost_estimate"] is None
        discard("usage-cancel")
    asyncio.run(run())


def test_embedding_reports_actual_sdk_usage():
    from app.context.usage import EmbeddingClient,current_run
    class Client:
        def create(self,**kwargs):return {"data":[{"embedding":[1.0]}],"usage":{"prompt_tokens":7,"total_tokens":7}}
    token=current_run.set("embedding-test")
    try:
        data=EmbeddingClient(Client(),"fixture").create(input=["原文"])
        report=ledger("embedding-test").report()
        assert data["data"][0]["embedding"]==[1.0]
        assert report["embedding_calls"]==1 and report["model_calls"]==0
        assert report["token_usage"]["total_tokens"]==7
    finally:current_run.reset(token);discard("embedding-test")


@pytest.mark.parametrize("streaming",[False,True])
def test_cache_phase_cancellation_is_traced_and_releases_ledger(monkeypatch,streaming):
    from app.services import chat as service
    from app.context import usage
    from app.config import settings
    from app.services.tracing import traces
    monkeypatch.setattr(settings,"llm_api_key","fixture")
    captured=[]
    async def cancelled(message,session_id,run_id):
        captured.append(run_id)
        usage.ledger(run_id).begin("embedding","fixture")
        raise asyncio.CancelledError
    monkeypatch.setattr(service,"_cache_lookup",cancelled)
    async def run():
        with pytest.raises(asyncio.CancelledError):
            if streaming:
                async for _ in service.stream_chat("问题","cache-cancel:test"):pass
            else:await service.chat("问题","cache-cancel:test")
        assert captured[0] not in usage._ledgers
        trace=next(t for t in traces.recent(20) if t["run_id"]==captured[0])
        assert trace["status"]==499 and trace["context_usage"]["unknown_usage_calls"]==1
    asyncio.run(run())


def test_pricing_includes_summary_cache_and_embedding(monkeypatch,tmp_path):
    import json
    import time
    from app.config import settings
    book={"currency":"CNY","models":{"fixture":{"endpoint":settings.llm_base_url,"max_input_tokens":128000,"input":1,"output":2,"cache_read":0.2}}}
    p=tmp_path/"prices.json";p.write_text(json.dumps(book),encoding="utf-8")
    monkeypatch.setattr(settings,"context_price_book",str(p))
    data=UsageLedger();call=data.begin("summary","fixture")
    data.finish(call,AIMessage(content="ok",usage_metadata={"input_tokens":100,"output_tokens":10,"total_tokens":110,"input_token_details":{"cache_read":50}}),time.perf_counter())
    assert data.report()["cost_estimate"]==0.00008
    assert data.report()["uncached_cost_estimate"]==0.00012
    unknown=data.begin("embedding","unknown")
    assert data.report()["cost_estimate"] is None


def test_evaluation_budget_blocks_request_before_call():
    from app.context.usage import EvaluationBudget,EvaluationLimitExceeded
    data=EvaluationBudget(1,100)
    reservation=data.reserve(20,10,"fixture")
    data.finish({"stage":"planning","model":"fixture","usage":{"input_tokens":20,"output_tokens":10,"total_tokens":30}},reservation)
    with pytest.raises(EvaluationLimitExceeded):data.reserve(20,10,"fixture")


def test_evaluation_budget_reserves_pending_parallel_calls():
    from app.context.usage import EvaluationBudget,EvaluationLimitExceeded
    data=EvaluationBudget(10,100)
    reservation=data.reserve(60,20,"fixture")
    with pytest.raises(EvaluationLimitExceeded):data.reserve(20,10,"fixture")
    data.finish({"stage":"planning","model":"fixture","usage":{"input_tokens":30,"output_tokens":10,"total_tokens":40}},reservation)
    assert data.pending_tokens==0 and data.pending_cost==0
    assert data.reserve(20,10,"fixture")[0]==30


def test_unknown_attempt_charges_upper_reserve_without_fabricating_usage():
    from app.context.usage import EvaluationBudget,EvaluationLimitExceeded
    data=EvaluationBudget(10,100)
    reservation=data.reserve(60,20,"fixture")
    data.finish({"usage":None},reservation)
    assert data.unknown and data.unknown_calls==1 and data.tokens==80
    assert data.unknown_token_reserve==80 and data.pending_tokens==0
    with pytest.raises(EvaluationLimitExceeded):data.reserve(20,10,"fixture")
    assert data.reserve(5,5,"fixture")[0]==10
    data=EvaluationBudget(10,10)
    with pytest.raises(EvaluationLimitExceeded):data.reserve(20,10,"fixture")
    data=EvaluationBudget(10,100);data.finish({"usage":None})
    with pytest.raises(EvaluationLimitExceeded):data.reserve(20,10,"fixture")
