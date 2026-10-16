"""D 部分：独立行为测试、边界及真实异常执行。"""
import asyncio
import os

import pytest

from app.go_validation.contracts import CodeBundle, GoTaskRequest, SourceFile
from app.go_validation.fixtures import ACCEPTANCE_FILE, with_acceptance_tests
from app.go_validation.runner import DockerGoRunner
from app.go_validation.service import GoTaskService
from app.go_validation.store import GoTaskStore
from eval.go_fixtures import FixtureModel, output

real = pytest.mark.skipif(os.environ.get("AIROBOT_TEST_DOCKER") != "1", reason="显式启用真实 Docker 测试")


def test_reserved_acceptance_file_rejected():
    bundle = output("channel").bundle
    bundle.files.append(SourceFile(name=ACCEPTANCE_FILE, content="package example"))
    # 通过模型校验后的对象检查保留文件名，不能替换服务端行为测试。
    bundle = CodeBundle.model_validate(bundle.model_dump())
    with pytest.raises(ValueError, match="不能提交"):
        with_acceptance_tests(bundle, "channel")


@real
@pytest.mark.parametrize("scenario", ["context_cancel", "worker_pool", "channel"])
def test_server_tests_detect_bad_behavior_even_with_weak_model_tests(scenario):
    bundle = output(scenario, "behavior_error").bundle
    bundle.files[1].content = 'package example\nimport "testing"\nfunc TestWeak(t *testing.T){if 1!=1{t.Fatal("never")}}'
    report = asyncio.run(DockerGoRunner().validate(with_acceptance_tests(bundle, scenario)))
    assert report.status == "failed" and report.stages[-1].stage == "test"
    assert "TestServer" in report.stages[-1].output and report.container_removed


@real
@pytest.mark.parametrize("body,status", [
    ('panic("异常测试")', "failed"),
    ('os.Exit(7)', "failed"),
    # go test 内部超时（模型代码死循环）按可修复失败处理，交给修复循环；
    # 只有沙箱/工具链级超时（阶段 35s 上限、外层总预算）才是终态 timeout。
    ('for {}', "failed"),
])
def test_real_panics_exit_and_infinite_loop(body, status):
    imports = 'import "os"\n' if "os.Exit" in body else ""
    bundle = CodeBundle(files=[
        {"name": "solution.go", "content": "package example\nfunc Value()int{return 1}"},
        {"name": "solution_test.go", "content": 'package example\nimport "testing"\n'+imports+
         'func TestBad(t *testing.T){'+body+'}'},
    ])
    report = asyncio.run(DockerGoRunner().validate(bundle))
    assert report.status == status and report.container_removed, report.model_dump()


@real
def test_real_repair_cannot_remove_server_tests():
    class WeakRepair(FixtureModel):
        async def ainvoke(self, messages):
            result = output("channel", "behavior_error")
            result.bundle.files[1].content = 'package example\nimport "testing"\nfunc TestWeak(t *testing.T){}'
            return result
    store = GoTaskStore(":memory:")
    try:
        service = GoTaskService(store, model=WeakRepair("channel", "behavior_error"), retrieve=lambda_retrieve)
        request = GoTaskRequest(scenario="channel", requirement="实现 channel 求和和取消")
        result = asyncio.run(service.run(request, "test", "test"))
        assert result.status == "failed" and len(result.attempts) == 3
        original = next(f.content for f in result.attempts[0].bundle.files if f.name == ACCEPTANCE_FILE)
        assert all(next(f.content for f in a.bundle.files if f.name == ACCEPTANCE_FILE) == original for a in result.attempts)
    finally:
        store.close()


async def lambda_retrieve(query):
    return {"chunks": [], "sources": []}


@real
def test_http_real_graph_json_stream_and_report_ownership(monkeypatch):
    import app.main as main
    from app.config import settings
    from httpx import ASGITransport, AsyncClient
    monkeypatch.setattr(settings, "admin_token", "acceptance-admin-token")
    monkeypatch.setattr(settings, "ai_internal_token", "acceptance-gateway-token")
    monkeypatch.setattr(settings, "ratelimit_enabled", False)
    store = GoTaskStore(":memory:")
    class Correct:
        async def ainvoke(self, messages):
            return output("channel")
    monkeypatch.setattr(main, "go_service", GoTaskService(store, model=Correct(), retrieve=lambda_retrieve))
    monkeypatch.setattr(main, "go_store", store)
    async def run():
        headers = {"X-Internal-Token": "acceptance-gateway-token", "X-Account-Id": "42"}
        request = {"scenario": "channel", "requirement": "求和直到 channel 关闭，支持取消"}
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
            response = await client.post("/api/v1/go/tasks", json=request, headers=headers)
            assert response.status_code == 200
            result = response.json()
            assert result["status"] == "passed" and result["attempts"][0]["validation"]["container_removed"]
            saved = await client.get("/api/v1/go/tasks/" + result["run_id"], headers=headers)
            assert saved.json() == result
            assert (await client.get("/api/v1/go/tasks/" + result["run_id"], headers={**headers, "X-Account-Id": "43"})).status_code == 404
            stream = await client.post("/api/v1/go/tasks/stream", json=request, headers=headers)
            import json
            events = [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")]
            assert events[-1]["type"] == "go_done" and events[-1]["result"]["status"] == "passed"
            assert [s["stage"] for s in events[-1]["result"]["attempts"][0]["validation"]["stages"]] == ["policy", "compile", "vet", "test"]
    try:
        asyncio.run(run())
    finally:
        store.close()
