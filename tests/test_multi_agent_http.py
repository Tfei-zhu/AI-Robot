"""S5: actual HTTP/ASGI boundaries and SQLite, scripted models, no paid requests."""
import asyncio
import copy
import hashlib
import json
import os
import threading
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

import app.main as main
from app.config import settings
from app.context import usage
from app.context.token_counter import TokenCounter
from app.go_validation.contracts import GoTaskResult, ValidationReport, artifact_hash
from app.go_validation.runner import DockerGoRunner
from app.go_validation.service import GoTaskService
from app.go_validation.store import GoTaskStore
from app.services.security import _busy, session_identity
from test_multi_agent_agents import ScriptedModel, SOLUTION_A, TEST_A, fenced, plan_json, review_json
from test_multi_agent_regressions import cfg, code_reply
from test_multi_agent_workflow import BROKEN, StubRunner, request, revise_json

HEADERS = {"X-Internal-Token": "s5-gateway", "X-Account-Id": "1"}
OWNER = hashlib.sha256(b"account/1").hexdigest()


class RecordingStore(GoTaskStore):
    def __init__(self, path):
        super().__init__(str(path))
        self.saved = []

    def save(self, run_id, owner, result):
        super().save(run_id, owner, result)
        self.saved.append(copy.deepcopy(result))


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "admin_token", "s5-admin")
    monkeypatch.setattr(settings, "ai_internal_token", "s5-gateway")
    monkeypatch.setattr(settings, "ratelimit_enabled", False)
    monkeypatch.setattr(settings, "go_multi_agent", cfg())
    store = RecordingStore(tmp_path / "s5.sqlite3")
    monkeypatch.setattr(main, "go_store", store)
    yield store
    store.close()


def install(monkeypatch, store, case="pass", **overrides):
    sup = [plan_json(), review_json()]
    code = [code_reply()]
    outcomes = ["passed"]
    if case == "repair":
        sup = [plan_json(), revise_json(), review_json()]
        code = [fenced(("solution.go", BROKEN), ("solution_test.go", TEST_A)), code_reply()]
        outcomes = ["failed", "passed"]
    elif case == "failed":
        outcomes = ["failed"]
        monkeypatch.setattr(settings, "go_multi_agent", cfg(max_repairs=0))
    elif case == "unavailable":
        outcomes = ["unavailable"]
    elif case == "budget":
        monkeypatch.setattr(settings, "go_multi_agent", cfg(max_normal_calls=2, max_model_calls=2))
    elif case == "generation_error":
        sup = ["invalid", "still invalid"]
    service = GoTaskService(store, supervisor_model=ScriptedModel(*sup),
                           code_model=ScriptedModel(*code), runner=StubRunner(*outcomes))
    for key, value in overrides.items():
        setattr(service, key, value)
    monkeypatch.setattr(main, "go_service", service)
    return service


def business(data):
    """IDs/timings and their prompt-token estimates vary between independent runs.

    Provider usage, limits, decisions and all source/hash evidence remain exact.
    Each removed local input estimate is independently checked against actual
    captured messages below, rather than accepted without verification.
    """
    if isinstance(data, dict):
        return {k: business(v) for k, v in data.items()
                if k not in {"run_id", "task_id", "artifact_id", "elapsed_ms", "input_estimate", "remaining_seconds"}}
    if isinstance(data, list):
        return [business(v) for v in data]
    return data


def events(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


@pytest.mark.parametrize("case,expected", [("pass", "passed"), ("repair", "passed"),
    ("failed", "failed"), ("unavailable", "unavailable"), ("budget", "budget_exceeded"),
    ("generation_error", "generation_error")])
def test_actual_json_sse_equal_and_persist_every_round(setup, monkeypatch, case, expected):
    async def run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
            ordinary_service = install(monkeypatch, setup, case)
            ordinary = await client.post("/api/v1/go/tasks", headers=HEADERS, json=request().model_dump())
            assert ordinary.status_code == 200
            data = ordinary.json()
            assert data["status"] == expected
            streamed_service = install(monkeypatch, setup, case)
            streamed = await client.post("/api/v1/go/tasks/stream", headers=HEADERS, json=request().model_dump())
            assert streamed.status_code == 200
            messages = events(streamed)
            assert all(e["run_id"] == messages[0]["run_id"] for e in messages)
            assert messages[0]["type"] == "go_start"
            assert messages[-1]["type"] == "go_done"
            assert sum(e["type"] == "go_done" for e in messages) == 1
            final = messages[-1]["result"]
            assert business(data) == business(final)
            assert final["status"] == expected  # HTTP 200 / stream completion is not business success.
            for result, service in ((data, ordinary_service), (final, streamed_service)):
                assert 0 <= result["budget"]["remaining_seconds"] <= result["budget"]["task_seconds"]
                assert result["budget"]["used"]["model"] == result["model_calls"]
                captured = {"supervisor": iter(service.supervisor_model.inputs),
                            "code": iter(service.code_model.inputs)}
                for call, measured in zip(result["agent_calls"], result["context_stats"]["calls"]):
                    assert measured["input_estimate"] == TokenCounter().count(next(captured[call["role"]]))
            for result in (data, final):
                loaded = await client.get("/api/v1/go/tasks/" + result["run_id"], headers=HEADERS)
                assert loaded.status_code == 200
                assert loaded.json() == result
                for art, attempt in zip(result["artifacts"], result["attempts"]):
                    assert artifact_hash(art["files"]) == art["artifact_hash"]
                    assert attempt["validation"]["artifact_hash"] == art["artifact_hash"]
                assert result["model_calls"] == len(result["agent_calls"])
            if case in {"pass", "repair", "failed"}:
                assert any(e["type"] == "go_call" for e in messages)
                assert sum(e["type"] == "go_attempt" for e in messages) == len(final["attempts"])
                assert sum(e["usage"]["total_tokens"] for e in messages if e["type"] == "go_usage") == final["token_usage"]["total_tokens"]
                assert any(e["type"] == "go_stage" and e["stage"] == "finish" and e["status"] == expected
                           for e in messages)
            if case == "repair":
                assert [e["round"] for e in messages if e["type"] == "go_stage" and e["stage"] == "repair"] == [1]
                assert len(final["artifacts"]) == len(final["reviews"]) == 2
                assert final["artifacts"][0]["artifact_hash"] != final["artifacts"][1]["artifact_hash"]
                assert any(r["task_spec"] and len(r["artifacts"]) == 1 and len(r["reviews"]) == 1
                           and r["status"] == "running" for r in setup.saved)
    asyncio.run(run())


def test_historical_report_rows_read_through_http_after_store_reopen(setup, monkeypatch):
    rows = json.loads((Path(__file__).resolve().parents[1] /
                       "docs/go-validation-fixture-report.json").read_text())["results"]
    db = setup._db()
    for row in rows:
        assert "workflow_version" not in row
        assert "artifact_hash" not in row["attempts"][0]["validation"]
        # Insert historical JSON bytes directly: do not manufacture an old sample
        # by serializing the new model or have save() supply the new fields first.
        db.execute("INSERT INTO go_tasks VALUES (?, ?, ?)", (row["run_id"], OWNER, json.dumps(row)))
    db.commit()
    setup.close()
    reopened = GoTaskStore(setup.path)
    monkeypatch.setattr(main, "go_store", reopened)
    async def run():
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
            for old in rows:
                response = await client.get("/api/v1/go/tasks/" + old["run_id"], headers=HEADERS)
                assert response.status_code == 200
                current = response.json()
                assert current["status"] == old["status"]
                assert current["workflow_version"] == "single-v1"
                assert current["task_spec"] is None and current["reviews"] == current["artifacts"] == []
                assert current["stop_reason"] is None
                assert current["attempts"][0]["validation"]["artifact_hash"] is None
                assert GoTaskResult.model_validate(current).model_dump() == current
                denied = await client.get("/api/v1/go/tasks/" + old["run_id"],
                                          headers={**HEADERS, "X-Account-Id": "2"})
                assert denied.status_code == 404
    try:
        asyncio.run(run())
    finally:
        reopened.close()


class BlockingModel(ScriptedModel):
    def __init__(self, *replies, block_at):
        super().__init__(*replies)
        self.block_at = block_at
        self.entered, self.closed = asyncio.Event(), asyncio.Event()

    async def ainvoke(self, messages):
        if len(self.inputs) == self.block_at:
            self.inputs.append(list(messages))
            self.entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.closed.set()
        return await super().ainvoke(messages)


class BlockingSandbox(StubRunner):
    def __init__(self):
        super().__init__()
        self.entered, self.closed = asyncio.Event(), asyncio.Event()
        self.last_report = None

    async def validate(self, bundle):
        self.bundles.append(bundle)
        self.entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0.01)  # Controlled bounded cleanup, not a real Docker result.
            self.last_report = ValidationReport(status="cancelled", container_removed=True,
                                                 artifact_hash=artifact_hash(bundle.files))
            self.closed.set()


class Exchange:
    """Real ASGI request lifecycle with controllable disconnect, no socket/network."""
    def __init__(self, path, payload, *, account="1", send_error=False):
        self.receives = asyncio.Queue()
        self.receives.put_nowait({"type": "http.request", "body": json.dumps(payload).encode(), "more_body": False})
        self.messages = []
        self.send_error = send_error
        self.scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1", "method": "POST", "scheme": "http", "path": path,
            "raw_path": path.encode(), "query_string": b"", "root_path": "",
            "client": ("127.0.0.1", 1234), "server": ("test", 80),
            "headers": [(b"content-type", b"application/json"),
                        (b"x-internal-token", b"s5-gateway"), (b"x-account-id", account.encode())]}

    async def send(self, message):
        self.messages.append(message)
        if self.send_error and message["type"] == "http.response.body" and message.get("body"):
            raise OSError("simulated broken client socket")

    async def run(self):
        await main.app(self.scope, self.receives.get, self.send)

    def disconnect(self):
        self.receives.put_nowait({"type": "http.disconnect"})


@pytest.mark.parametrize("stage", ["generate", "review", "sandbox", "repair_generate"])
@pytest.mark.parametrize("transport", ["json", "sse"])
@pytest.mark.parametrize("stop", ["cancel", "timeout"])
def test_interruptions_preserve_evidence_and_release_session(setup, monkeypatch, stage, transport, stop):
    async def run():
        sup = ScriptedModel(plan_json(), review_json())
        code = ScriptedModel(code_reply())
        runner = StubRunner()
        if stage == "generate":
            blocker = code = BlockingModel(block_at=0)
        elif stage == "review":
            blocker = sup = BlockingModel(plan_json(), block_at=1)
        elif stage == "sandbox":
            blocker = runner = BlockingSandbox()
        else:
            sup = ScriptedModel(plan_json(), revise_json())
            blocker = code = BlockingModel(fenced(("solution.go", BROKEN), ("solution_test.go", TEST_A)), block_at=1)
            runner = StubRunner("failed")
        limits = {"code_timeout": 0.08} if stage in {"generate", "repair_generate"} else {
                  "supervisor_timeout" if stage == "review" else "validation_timeout": 0.08}
        monkeypatch.setattr(settings, "go_multi_agent", cfg(**(limits if stop == "timeout" else {})))
        install(monkeypatch, setup, supervisor_model=sup, code_model=code, runner=runner)
        session = f"s5-{stage}-{transport}-{stop}"
        payload = {**request().model_dump(), "session_id": session}
        path = "/api/v1/go/tasks" + ("/stream" if transport == "sse" else "")
        exchange = Exchange(path, payload)
        job = asyncio.create_task(exchange.run())
        try:
            await asyncio.wait_for(blocker.entered.wait(), 3)
            key = session_identity("account/1", session)[1]
            assert key in _busy
            async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
                conflict = await client.post("/api/v1/go/tasks", headers=HEADERS, json=payload)
                assert conflict.status_code == 409
            if stop == "cancel":
                if transport == "sse":
                    exchange.disconnect()
                else:
                    job.cancel()
            try:
                await asyncio.wait_for(job, 3)
            except asyncio.CancelledError:
                assert stop == "cancel"
            assert blocker.closed.is_set()
            assert key not in _busy
            assert setup.saved, "Cancellation must persist a report, including before first artifact"
            saved = setup.get(setup.saved[-1]["run_id"], OWNER)
            expected = "cancelled" if stop == "cancel" else "timeout"
            assert saved["status"] == saved["stop_reason"] == expected
            assert saved["workflow_version"] == "multi-v1" and saved["task_spec"] is not None
            expected_calls = {"generate": 2, "review": 3, "sandbox": 2, "repair_generate": 4}[stage]
            assert saved["model_calls"] == len(sup.inputs) + len(code.inputs) == expected_calls
            assert saved["context_stats"]["model_calls"] == expected_calls
            assert saved["validation_calls"] == (0 if stage == "generate" else 1)
            assert len(saved["artifacts"]) == (0 if stage == "generate" else 1)
            assert len(saved["reviews"]) == (1 if stage == "repair_generate" else 0)
            if stage != "sandbox":
                assert saved["agent_calls"][-1]["status"] in {"failed", "cancelled"}
                assert saved["context_stats"]["unknown_usage_calls"] == 1
            if stage == "sandbox":
                assert len(saved["attempts"]) == 1
                assert saved["attempts"][0]["validation"]["status"] == expected
                assert saved["attempts"][0]["validation"]["container_removed"]
            for art in saved["artifacts"]:
                assert artifact_hash(art["files"]) == art["artifact_hash"]
            assert saved["run_id"] not in usage._ledgers
            async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
                own = await client.get("/api/v1/go/tasks/" + saved["run_id"], headers=HEADERS)
                assert own.status_code == 200 and own.json() == saved
                other = await client.get("/api/v1/go/tasks/" + saved["run_id"],
                                         headers={**HEADERS, "X-Account-Id": "2"})
                assert other.status_code == 404
                install(monkeypatch, setup)
                again = await client.post("/api/v1/go/tasks", headers=HEADERS, json=payload)
                assert again.status_code == 200 and again.json()["status"] == "passed"
        finally:
            if not job.done():
                job.cancel()
                try:
                    await job
                except asyncio.CancelledError:
                    pass
    asyncio.run(run())


def test_close_at_go_start_persists_cancelled_without_external_calls(setup, monkeypatch):
    async def run():
        service = install(monkeypatch, setup)
        stream = service.stream(request(), "account/1", "early-close")
        start = await anext(stream)
        await stream.aclose()
        saved = setup.get(start["run_id"], OWNER)
        assert saved is not None and saved["status"] == saved["stop_reason"] == "cancelled"
        assert saved["workflow_version"] == "multi-v1"
        assert saved["model_calls"] == saved["validation_calls"] == 0
        assert not service.supervisor_model.inputs and not service.code_model.inputs
    asyncio.run(run())


def test_accounts_same_public_session_can_run_concurrently(setup, monkeypatch):
    async def run():
        gate = BlockingModel(block_at=0)
        service = install(monkeypatch, setup, code_model=gate)
        first = Exchange("/api/v1/go/tasks/stream", {**request().model_dump(), "session_id": "shared"})
        job = asyncio.create_task(first.run())
        try:
            await asyncio.wait_for(gate.entered.wait(), 3)
            install(monkeypatch, setup)
            async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
                other = await client.post("/api/v1/go/tasks", headers={**HEADERS, "X-Account-Id": "2"},
                                           json={**request().model_dump(), "session_id": "shared"})
                assert other.status_code == 200 and other.json()["status"] == "passed"
                denied = await client.get("/api/v1/go/tasks/" + other.json()["run_id"], headers=HEADERS)
                assert denied.status_code == 404
            first.disconnect()
            await asyncio.wait_for(job, 3)
            assert gate.closed.is_set()
            assert not service._semaphore.locked()
        finally:
            if not job.done():
                job.cancel()
                try:
                    await job
                except asyncio.CancelledError:
                    pass
    asyncio.run(run())


@pytest.mark.parametrize("stop", ["cancel", "timeout"])
def test_waiting_for_capacity_keeps_zero_calls_and_releases_session(setup, monkeypatch, stop):
    async def run():
        service = install(monkeypatch, setup, timeout=0.08 if stop == "timeout" else 360)
        await service._semaphore.acquire()
        await service._semaphore.acquire()
        session = "capacity-" + stop
        exchange = Exchange("/api/v1/go/tasks/stream", {**request().model_dump(), "session_id": session})
        job = asyncio.create_task(exchange.run())
        try:
            while not setup.saved:
                await asyncio.sleep(0)
            if stop == "cancel":
                exchange.disconnect()
            await asyncio.wait_for(job, 3)
            saved = setup.get(setup.saved[-1]["run_id"], OWNER)
            assert saved["status"] == saved["stop_reason"] == ("cancelled" if stop == "cancel" else "timeout")
            assert saved["model_calls"] == saved["validation_calls"] == 0
            assert saved["artifacts"] == saved["reviews"] == []
            assert session_identity("account/1", session)[1] not in _busy
            assert not service.supervisor_model.inputs and not service.code_model.inputs
        finally:
            service._semaphore.release()
            service._semaphore.release()
            if not job.done():
                job.cancel()
                try:
                    await job
                except asyncio.CancelledError:
                    pass
    asyncio.run(run())


def test_repeated_cancellation_keeps_session_until_report_commit(setup, monkeypatch):
    async def run():
        model = BlockingModel(block_at=0)
        install(monkeypatch, setup, code_model=model)
        entered_commit, release_commit = threading.Event(), threading.Event()
        original = setup.save
        def delayed_commit(run_id, owner, result):
            if result["status"] == "cancelled":
                entered_commit.set()
                if not release_commit.wait(3):
                    raise RuntimeError("test did not release final commit")
            original(run_id, owner, result)
        monkeypatch.setattr(setup, "save", delayed_commit)
        session = "repeat-cancel"
        exchange = Exchange("/api/v1/go/tasks", {**request().model_dump(), "session_id": session})
        job = asyncio.create_task(exchange.run())
        try:
            await asyncio.wait_for(model.entered.wait(), 3)
            job.cancel()
            assert await asyncio.to_thread(entered_commit.wait, 3)
            assert session_identity("account/1", session)[1] in _busy
            job.cancel()
            await asyncio.sleep(0)
            assert session_identity("account/1", session)[1] in _busy
            release_commit.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(job, 3)
            saved = setup.get(setup.saved[-1]["run_id"], OWNER)
            assert saved["status"] == "cancelled" and saved["model_calls"] == 2
            assert saved["run_id"] not in usage._ledgers
            assert session_identity("account/1", session)[1] not in _busy
        finally:
            release_commit.set()
            if not job.done():
                job.cancel()
                try:
                    await job
                except asyncio.CancelledError:
                    pass
    asyncio.run(run())


def test_execution_capacity_is_held_until_sandbox_cleanup_finishes(setup, monkeypatch):
    async def run():
        cleanup_started, cleanup_release = asyncio.Event(), asyncio.Event()
        class CleanupGate(BlockingSandbox):
            async def validate(self, bundle):
                self.bundles.append(bundle)
                self.entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cleanup_started.set()
                    await cleanup_release.wait()
                    self.last_report = ValidationReport(status="cancelled", container_removed=True,
                                                         artifact_hash=artifact_hash(bundle.files))
                    self.closed.set()
        runner = CleanupGate()
        service = install(monkeypatch, setup, runner=runner)
        key = session_identity("account/1", "cleanup-capacity")[1]
        exchange = Exchange("/api/v1/go/tasks/stream", {**request().model_dump(), "session_id": "cleanup-capacity"})
        job = asyncio.create_task(exchange.run())
        try:
            await asyncio.wait_for(runner.entered.wait(), 3)
            exchange.disconnect()
            await asyncio.wait_for(cleanup_started.wait(), 3)
            await asyncio.sleep(0)
            assert service._semaphore._value == 1  # one slot still owned by stopping sandbox
            assert key in _busy
            cleanup_release.set()
            await asyncio.wait_for(job, 3)
            assert runner.closed.is_set() and service._semaphore._value == 2 and key not in _busy
            saved = setup.get(setup.saved[-1]["run_id"], OWNER)
            assert saved["status"] == "cancelled"
            assert saved["attempts"][0]["validation"]["container_removed"]
        finally:
            cleanup_release.set()
            if not job.done():
                job.cancel()
                try:
                    await job
                except asyncio.CancelledError:
                    pass
    asyncio.run(run())


def test_stream_send_failure_closes_iterator_before_releasing_session(setup, monkeypatch):
    # ASGI 2.4 reports a broken socket at send(), while the body iterator is
    # paused at yield. Exercise SessionStreamResponse directly (middleware can
    # buffer the body), with the real service and session claim/release policy.
    from app.main import _sse
    from app.services.security import SessionStreamResponse, claim_session
    from contextlib import aclosing
    async def run():
        service = install(monkeypatch, setup)
        key = session_identity("account/1", "send-failure")[1]
        claim_session(key)
        async def body():
            async with aclosing(service.stream(request(), "account/1", key)) as stream:
                async for event in stream:
                    yield _sse(event)
        exchange = Exchange("/api/v1/go/tasks/stream", request().model_dump(), send_error=True)
        exchange.scope["asgi"]["spec_version"] = "2.4"
        from starlette.requests import ClientDisconnect
        with pytest.raises(ClientDisconnect):
            await SessionStreamResponse(body(), session_key=key)(exchange.scope, exchange.receives.get, exchange.send)
        saved = setup.get(setup.saved[-1]["run_id"], OWNER)
        assert saved["status"] == "cancelled" and saved["model_calls"] == 0
        assert key not in _busy
        assert not any(b'"type": "go_done"' in m.get("body", b"") for m in exchange.messages)
    asyncio.run(run())


def test_store_rejects_false_success_and_owner_overwrite(setup):
    initial = GoTaskResult(run_id="1" * 32, status="running", scenario="context_cancel").model_dump()
    setup.save(initial["run_id"], OWNER, initial)
    with pytest.raises(ValueError, match="归属"):
        setup.save(initial["run_id"], "another-owner", initial)
    with pytest.raises(ValueError, match="run_id"):
        setup.save("2" * 32, OWNER, initial)
    with pytest.raises(ValueError):
        setup.save(initial["run_id"], OWNER, {**initial, "workflow_version": "multi-v1", "status": "passed"})
    assert setup.get(initial["run_id"], OWNER)["status"] == "running"


def test_validator_exception_is_preserved_with_current_artifact(setup, monkeypatch):
    class BrokenRunner:
        async def validate(self, bundle):
            raise RuntimeError("sandbox-witness-9527")
    async def run():
        service = install(monkeypatch, setup, runner=BrokenRunner())
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
            response = await client.post("/api/v1/go/tasks", headers=HEADERS, json=request().model_dump())
            data = response.json()
            assert response.status_code == 200 and data["status"] == data["stop_reason"] == "unavailable"
            assert data["validation_calls"] == len(data["attempts"]) == 1
            report = data["attempts"][0]["validation"]
            assert report["artifact_hash"] == data["artifacts"][0]["artifact_hash"]
            assert not report["container_removed"]
            assert "sandbox-witness-9527" in report["stages"][0]["output"]
            assert len(service.supervisor_model.inputs) == 1 and data["model_calls"] == 2
    asyncio.run(run())


def test_progress_write_exception_stops_active_workflow_before_session_release(setup, monkeypatch):
    async def run():
        entered = threading.Event()
        blocker = BlockingModel(block_at=0)
        class Model:
            async def ainvoke(self, messages):
                entered.set()
                return await blocker.ainvoke(messages)
        service = install(monkeypatch, setup, code_model=Model())
        original = setup.save
        failed = False
        def fail_progress(run_id, owner, result):
            nonlocal failed
            if not failed and result["task_spec"] is not None and result["status"] == "running":
                failed = True
                if not entered.wait(3):
                    raise RuntimeError("test model did not enter")
                raise RuntimeError("one-shot progress commit failure")
            original(run_id, owner, result)
        monkeypatch.setattr(setup, "save", fail_progress)
        session = "write-error"
        async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
            response = await client.post("/api/v1/go/tasks", headers=HEADERS,
                                         json={**request().model_dump(), "session_id": session})
        assert response.status_code == 200 and response.json()["status"] == "failed"
        assert blocker.closed.is_set()
        saved = setup.get(response.json()["run_id"], OWNER)
        assert saved["model_calls"] == 2 and saved["agent_calls"][-1]["status"] == "cancelled"
        assert saved["task_spec"] is not None
        assert session_identity("account/1", session)[1] not in _busy
        assert saved["run_id"] not in usage._ledgers
        assert len(service.supervisor_model.inputs) == 1
    asyncio.run(run())


@pytest.mark.skipif(os.environ.get("AIROBOT_TEST_DOCKER") != "1", reason="显式启用 S5 真实 Docker 中断验收")
@pytest.mark.parametrize("transport", ["json", "sse"])
@pytest.mark.parametrize("stop", ["cancel", "timeout"])
def test_real_docker_http_interrupt_preserves_report_and_confirms_cleanup(setup, monkeypatch, transport, stop):
    class ObservedDocker(DockerGoRunner):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()
            self.name = None
        def command(self, name):
            self.name = name
            self.entered.set()
            return super().command(name)
    async def run():
        runner = ObservedDocker()
        # Valid assertions remain; this test deliberately stays active until
        # externally stopped. Neither model-generated nor trusted tests skip.
        park = ('package example\nimport ("testing"; "time")\n'
                'func TestPark(t *testing.T) { time.Sleep(30*time.Second); if 1+1 != 2 { t.Fatal("math") } }\n')
        service = install(monkeypatch, setup, runner=runner,
                          code_model=ScriptedModel(fenced(("solution.go", SOLUTION_A), ("solution_test.go", park))))
        monkeypatch.setattr(settings, "go_multi_agent", cfg(validation_timeout=1 if stop == "timeout" else 90))
        session = f"real-{stop}-{transport}"
        exchange = Exchange("/api/v1/go/tasks" + ("/stream" if transport == "sse" else ""),
                            {**request().model_dump(), "session_id": session})
        job = asyncio.create_task(exchange.run())
        try:
            await asyncio.wait_for(runner.entered.wait(), 3)
            async with asyncio.timeout(5):
                while True:
                    proc = await asyncio.create_subprocess_exec("docker", "inspect", "--format", "{{.State.Running}}", runner.name,
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    output, _ = await proc.communicate()
                    if output.strip() == b"true":
                        break
                    await asyncio.sleep(0.02)
            if stop == "cancel":
                if transport == "sse":
                    exchange.disconnect()
                else:
                    job.cancel()
            try:
                await asyncio.wait_for(job, 10)
            except asyncio.CancelledError:
                assert stop == "cancel"
            saved = setup.get(setup.saved[-1]["run_id"], OWNER)
            expected = "cancelled" if stop == "cancel" else "timeout"
            assert saved["status"] == saved["stop_reason"] == expected
            assert saved["model_calls"] == 2 and saved["validation_calls"] == 1
            assert saved["attempts"][0]["validation"]["container_removed"]
            assert saved["attempts"][0]["validation"]["artifact_hash"] == saved["artifacts"][0]["artifact_hash"]
            assert session_identity("account/1", session)[1] not in _busy
            proc = await asyncio.create_subprocess_exec("docker", "ps", "-aq", "--filter", "name=" + runner.name,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            output, _ = await proc.communicate()
            assert not output.strip()
            assert len(service.supervisor_model.inputs) == 1  # no review or repair after stop
        finally:
            if not job.done():
                job.cancel()
                try:
                    await job
                except asyncio.CancelledError:
                    pass
    asyncio.run(run())
