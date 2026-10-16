"""C 部分：同一张图、修复预算、冻结测试、持久化及 JSON/SSE 一致性。"""
import asyncio
import hashlib
import os

import pytest
from httpx import ASGITransport, AsyncClient

from app.go_validation.contracts import CodeBundle, GoTaskRequest, ValidationReport, StageReport
from app.go_validation.runner import DockerGoRunner
from app.go_validation.service import GoTaskService
from app.go_validation.store import GoTaskStore


def generated(value=2, assertion=4):
    return {"bundle": {"files": [
        {"name": "solution.go", "content": f"package example\nfunc Double(x int) int {{return x * {value}}}"},
        {"name": "solution_test.go", "content": f'package example\nimport "testing"\nfunc TestDouble(t *testing.T){{if Double(2)!={assertion}{{t.Fatal("wrong")}}}}'},
    ]}, "change_summary": "修复乘数"}


class FakeModel:
    def __init__(self, responses):
        self.responses=iter(responses)
        self.calls=0
    async def ainvoke(self, messages):
        self.calls+=1
        return next(self.responses)


class FakeRunner:
    def __init__(self, statuses):
        self.statuses=iter(statuses)
    async def validate(self, bundle):
        status=next(self.statuses)
        return ValidationReport(status=status, container_removed=True,
            stages=[StageReport(stage="test",exit_code=0 if status=="passed" else 1,output="actual test error")])


async def references(requirement):
    return {"chunks":[{"text":"示例资料"}],"sources":["article:12#0"]}


def make(model, runner=None, timeout=180):
    return GoTaskService(GoTaskStore(":memory:"),model=model,
                         runner=runner or FakeRunner(["failed","passed"]),retrieve=references,timeout=timeout)


REQUEST=GoTaskRequest(requirement="演示验证及修复流程",scenario="worker_pool")


def test_repairs_and_persists_with_sources():
    service=make(FakeModel([generated(1),generated(2)]))
    result=asyncio.run(service.run(REQUEST,"account/1","test"))
    assert result.status=="passed" and len(result.attempts)==2
    assert result.model_calls==2 and result.validation_calls==2
    assert result.sources==["article:12#0"]
    owner=hashlib.sha256(b"account/1").hexdigest()
    assert len(service.store.get(result.run_id,owner)["attempts"])==2
    assert service.store.get(result.run_id,hashlib.sha256(b"account/2").hexdigest()) is None


def test_max_two_repairs_and_preserves_failure():
    model=FakeModel([generated(1)]*4)
    service=make(model,FakeRunner(["failed"]*4))
    result=asyncio.run(service.run(REQUEST,"account/1","test"))
    assert result.status=="failed" and len(result.attempts)==3
    assert model.calls==result.model_calls==result.validation_calls==3
    assert result.attempts[-1].validation.stages[-1].output=="actual test error"


def test_fenced_output_parser():
    # 真实模型按围栏纯文本输出；解析器需容忍前后废话与缺失围栏，但契约校验不放松。
    from app.go_validation.nodes import parse_model_output
    text = """好的，以下是代码：
=== FILE: solution.go ===
```go
package example

func Double(x int) int { return x * 2 }
```
=== FILE: solution_test.go ===
```go
package example
import "testing"
func TestDouble(t *testing.T){ if Double(2)!=4 {t.Fatal("wrong")} }
```
CHANGE: 首次实现
"""
    out = parse_model_output(text)
    assert [f.name for f in out.bundle.files] == ["solution.go", "solution_test.go"]
    assert "return x * 2" in out.bundle.files[0].content
    assert "```" not in out.bundle.files[0].content
    assert out.change_summary == "首次实现"
    fenceless = text.replace("```go\n", "").replace("\n```", "")
    assert parse_model_output(fenceless).bundle.files[0].content == out.bundle.files[0].content
    with pytest.raises(ValueError):
        parse_model_output("没有任何文件头的输出")


def test_server_tests_cannot_be_weakened_on_repair():
    # 模型自己的测试可随修复更新（初轮可能自身有缺陷）；服务端验收测试必须原样保留。
    from app.go_validation.fixtures import ACCEPTANCE_FILE, ACCEPTANCE_TESTS
    class AssertRunner:
        async def validate(self,bundle):
            acceptance=next((f for f in bundle.files if f.name.lower()==ACCEPTANCE_FILE),None)
            assert acceptance is not None and acceptance.content==ACCEPTANCE_TESTS["worker_pool"]
            return ValidationReport(status="failed",container_removed=True)
    service=make(FakeModel([generated(1),generated(1,2),generated(1,2)]),AssertRunner())
    result=asyncio.run(service.run(REQUEST,"account/1","test"))
    assert result.status=="failed" and len(result.attempts)==3


@pytest.mark.parametrize("status",["unavailable","timeout"])
def test_infrastructure_failures_do_not_trigger_repairs(status):
    model=FakeModel([generated()])
    result=asyncio.run(make(model,FakeRunner([status])).run(REQUEST,"account/1","test"))
    assert result.status==status and model.calls==1


def test_invalid_generated_files_are_rejected():
    data=generated();data["bundle"]["files"][0]["name"]="../escape.go"
    result=asyncio.run(make(FakeModel([data])).run(REQUEST,"account/1","test"))
    assert result.status=="generation_error" and result.validation_calls==0


def test_json_and_stream_use_identical_workflow():
    async def run():
        ordinary=await make(FakeModel([generated()]),FakeRunner(["passed"])).run(REQUEST,"account/1","test")
        events=[e async for e in make(FakeModel([generated()]),FakeRunner(["passed"])).stream(REQUEST,"account/1","test")]
        streamed=events[-1]["result"]
        def comparable(data):
            data={k:v for k,v in data.items() if k not in {"run_id","elapsed_ms"}}
            # 两次独立运行的真实计量耗时自然不同，其余业务结果和次数必须一致。
            for call in data.get("context_stats",{}).get("calls",[]):call.pop("elapsed_ms",None)
            return data
        assert comparable(ordinary.model_dump())==comparable(streamed)
        assert any(e["type"]=="go_stage" and e["stage"]=="validate" for e in events)
        assert any(e["type"]=="go_attempt" for e in events)
    asyncio.run(run())


def test_total_timeout_cancels_model_and_reports_attempted_call():
    class Slow:
        async def ainvoke(self,messages):
            await asyncio.sleep(5)
    result=asyncio.run(make(Slow(),timeout=0.05).run(REQUEST,"account/1","test"))
    assert result.status=="timeout" and result.model_calls==1


def test_closing_stream_persists_cancelled_status():
    async def run():
        service=make(FakeModel([generated()]),FakeRunner(["passed"]))
        events=service.stream(REQUEST,"account/1","test")
        first=await anext(events)
        await anext(events)
        await events.aclose()
        result=service.store.get(first["run_id"],hashlib.sha256(b"account/1").hexdigest())
        assert result["status"]=="cancelled"
    asyncio.run(run())


@pytest.mark.skipif(os.environ.get("AIROBOT_TEST_DOCKER")!="1",reason="启用真实 Docker 测试")
def test_actual_graph_repairs_using_real_go_error():
    def context_code(correct):
        body="<-ctx.Done();return ctx.Err()" if correct else "return nil"
        return {"bundle":{"files":[
            {"name":"solution.go","content":'package example\nimport "context"\nfunc WaitForCancel(ctx context.Context) error {'+body+'}'},
            {"name":"solution_test.go","content":'package example\nimport "testing"\nfunc TestExample(t *testing.T){if 1!=1{t.Fatal("wrong")}}'}]},"change_summary":"传播取消错误"}
    class RepairModel(FakeModel):
        async def ainvoke(self,messages):
            if self.calls:
                assert "previous_attempt" in messages[-1].content and "取消" in messages[-1].content
            return await super().ainvoke(messages)
    service=make(RepairModel([context_code(False),context_code(True)]),DockerGoRunner())
    request=GoTaskRequest(requirement="等待 context 取消并返回错误",scenario="context_cancel")
    result=asyncio.run(service.run(request,"account/1","test"))
    assert result.status=="passed" and len(result.attempts)==2
    assert result.attempts[0].validation.status=="failed"
    assert all(a.validation.container_removed for a in result.attempts)


def test_http_permissions_and_json_sse(monkeypatch):
    import app.main as main
    from app.config import settings
    monkeypatch.setattr(settings,"admin_token","admin-go-test")
    monkeypatch.setattr(settings,"ai_internal_token","gateway-go-test")
    monkeypatch.setattr(settings,"ratelimit_enabled",False)
    task_store=GoTaskStore(":memory:")
    class Repeating:
        async def ainvoke(self,messages):
            return generated()
    class Passing:
        async def validate(self,bundle):
            return ValidationReport(status="passed",container_removed=True)
    monkeypatch.setattr(main,"go_service",GoTaskService(task_store,model=Repeating(),runner=Passing(),retrieve=references))
    monkeypatch.setattr(main,"go_store",task_store)
    async def run():
        async with AsyncClient(transport=ASGITransport(app=main.app),base_url="http://test") as client:
            assert (await client.post("/api/v1/go/tasks",json=REQUEST.model_dump())).status_code==401
            headers={"X-Internal-Token":"gateway-go-test","X-Account-Id":"1"}
            r=await client.post("/api/v1/go/tasks",json=REQUEST.model_dump(),headers=headers)
            assert r.status_code==200 and r.json()["status"]=="passed"
            run_id=r.json()["run_id"]
            assert (await client.get("/api/v1/go/tasks/"+run_id,headers=headers)).status_code==200
            assert (await client.get("/api/v1/go/tasks/"+run_id,headers={**headers,"X-Account-Id":"2"})).status_code==404
            assert (await client.get("/api/v1/traces",headers=headers)).status_code==403
            s=await client.post("/api/v1/go/tasks/stream",json=REQUEST.model_dump(),headers=headers)
            assert s.status_code==200 and '"type": "go_done"' in s.text
            assert '"type": "go_attempt"' in s.text
    asyncio.run(run())
