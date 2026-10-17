"""Review probes assert intended guarantees; failures are findings, not product edits."""
import asyncio
import hashlib
import json
from pathlib import Path

from app.config import settings
from app.context.token_counter import SERIALIZER_VERSION
from app.go_validation.runner import DockerGoRunner
from app.go_validation.service import GoTaskService
from app.go_validation.store import GoTaskStore
from test_multi_agent_agents import ScriptedModel, plan_json, review_json, fenced
from test_multi_agent_http import setup, install, Exchange, OWNER
from test_multi_agent_regressions import cfg, code_reply
from test_multi_agent_workflow import request, StubRunner

OUT = Path(__file__).resolve().parent

def save(name, value):
    (OUT/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    print(name, json.dumps(value,ensure_ascii=False)[:1200])

def test_json_disconnect_stops_work(setup, monkeypatch):
    async def run():
        class Gate(ScriptedModel):
            def __init__(self):
                super().__init__(plan_json(), review_json())
                self.entered, self.release = asyncio.Event(), asyncio.Event()
            async def ainvoke(self, messages):
                if not self.inputs:
                    self.entered.set()
                    await self.release.wait()
                return await super().ainvoke(messages)
        model = Gate()
        service = install(monkeypatch, setup, supervisor_model=model)
        exchange = Exchange('/api/v1/go/tasks', request().model_dump())
        task = asyncio.create_task(exchange.run())
        try:
            await asyncio.wait_for(model.entered.wait(), 3)
            exchange.disconnect()  # Real ASGI disconnect, NOT task.cancel().
            await asyncio.sleep(.1)
            model.release.set()
            await asyncio.wait_for(task, 3)
            result = setup.get(setup.saved[-1]['run_id'], OWNER)
            save('json-disconnect', dict(status=result['status'], model_calls=result['model_calls'],
                validation_calls=result['validation_calls'], disconnect_unconsumed=exchange.receives.qsize(),
                code_requests=len(service.code_model.inputs)))
            assert result['status']=='cancelled'
        finally:
            if not task.done():
                task.cancel()
                try: await task
                except asyncio.CancelledError: pass
    asyncio.run(run())

def test_failed_requirement_evidence_reaches_repair(monkeypatch):
    async def run():
        monkeypatch.setattr(settings,'go_multi_agent',cfg())
        checks=json.loads(review_json())['requirement_checks']
        checks[0].update(status='fail',evidence='REVIEW_EVIDENCE_9f31: solution.go:3 violates exact error identity')
        sup=ScriptedModel(plan_json(),review_json(verdict='revise',requirement_checks=checks,
                            summary='REPAIR_SUMMARY_1ac7: preserve exact error identity'),review_json())
        code=ScriptedModel(code_reply(),code_reply())
        store=GoTaskStore(':memory:')
        try:
            result=await GoTaskService(store,supervisor_model=sup,code_model=code,runner=StubRunner()).run(request(),'review','repair')
            prompt='\n'.join(str(m.content) for m in code.inputs[1])
            save('repair-feedback',dict(status=result.status,model_calls=result.model_calls,
                review=result.reviews[0].model_dump(),repair_prompt=prompt))
            assert 'REVIEW_EVIDENCE_9f31' in prompt
        finally: store.close()
    asyncio.run(run())

def test_context_preflight_failure_is_not_a_sent_call(monkeypatch,tmp_path):
    async def run():
        calibration=tmp_path/'calibration.json'
        calibration.write_text(json.dumps(dict(model=settings.llm_model,
            endpoint_sha256=hashlib.sha256(settings.llm_base_url.encode()).hexdigest(),
            encoding=settings.context_encoding,serializer=SERIALIZER_VERSION,
            samples=20,validated=True,factor=1.0)))
        for name,value in dict(context_mode='enforce',context_input_limit=1,
            context_model_window=32768,context_calibration_path=str(calibration),go_multi_agent=cfg()).items():
            monkeypatch.setattr(settings,name,value)
        sup=ScriptedModel(plan_json(),review_json())
        code=ScriptedModel(code_reply())
        store=GoTaskStore(':memory:')
        try:
            result=await GoTaskService(store,supervisor_model=sup,code_model=code,runner=StubRunner()).run(request(),'review','context')
            save('context-preflight',dict(status=result.status,error=result.error,reported_calls=result.model_calls,
                actual_calls=len(sup.inputs)+len(code.inputs),ledger_calls=result.context_stats['model_calls'],budget=result.budget))
            assert result.status=='budget_exceeded'
            assert result.model_calls==0
        finally: store.close()
    asyncio.run(run())

def test_disconnect_after_persisted_success_does_not_rewrite_terminal(setup,monkeypatch):
    async def run():
        service=install(monkeypatch,setup)
        stream=service.stream(request(),'account/1','terminal')
        try:
            async for event in stream:
                if event['type']=='go_progress' and event['result']['status']=='passed':
                    run_id=event['run_id']
                    before=setup.get(run_id,OWNER)
                    assert before['status']=='passed'
                    break
        finally:
            await stream.aclose()
        after=setup.get(run_id,OWNER)
        save('terminal-rewrite',dict(before=before['status'],after=after['status'],
            stop_reason=after['stop_reason'],calls=after['model_calls'],summary=after['final_summary']))
        assert after['status']=='passed'
    asyncio.run(run())
