"""S7: planning/retrieval stop before the first artifact, actual ASGI + SQLite.

All models/retrieval are controlled substitutes; no Docker result is claimed here.
"""
import asyncio

from httpx import ASGITransport, AsyncClient
import pytest

import app.main as main
from app.config import settings
from app.context import usage
from app.services.security import _busy, session_identity
from test_multi_agent_agents import ScriptedModel, plan_json
from test_multi_agent_http import BlockingModel, Exchange, HEADERS, OWNER, install, setup
from test_multi_agent_regressions import cfg
from test_multi_agent_workflow import request


@pytest.mark.parametrize("stage", ["plan", "retrieve"])
@pytest.mark.parametrize("transport", ["json", "sse"])
@pytest.mark.parametrize("stop", ["cancel", "timeout"])
def test_early_interrupt_preserves_call_and_releases_session(setup, monkeypatch, stage, transport, stop):
    async def run():
        entered, closed = asyncio.Event(), asyncio.Event()
        retrieval_calls = []

        async def retrieve(query):
            retrieval_calls.append(query)
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()

        if stage == "plan":
            supervisor = BlockingModel(block_at=0)
            entered, closed = supervisor.entered, supervisor.closed
        else:
            supervisor = ScriptedModel(plan_json())
        monkeypatch.setattr(settings, "go_multi_agent", cfg(
            **({"supervisor_timeout": 0.08} if stage == "plan" and stop == "timeout" else {})))
        service = install(monkeypatch, setup, supervisor_model=supervisor,
                          retrieve=retrieve if stage == "retrieve" else None,
                          timeout=0.15 if stage == "retrieve" and stop == "timeout" else 360)
        session = f"early-{stage}-{transport}-{stop}"
        payload = {**request().model_dump(), "session_id": session}
        exchange = Exchange("/api/v1/go/tasks" + ("/stream" if transport == "sse" else ""), payload)
        job = asyncio.create_task(exchange.run())
        try:
            await asyncio.wait_for(entered.wait(), 3)
            key = session_identity("account/1", session)[1]
            assert key in _busy
            if stop == "cancel":
                if transport == "sse":
                    exchange.disconnect()
                else:
                    job.cancel()
            try:
                await asyncio.wait_for(job, 3)
            except asyncio.CancelledError:
                assert stop == "cancel"
            assert closed.is_set() and key not in _busy
            saved = setup.get(setup.saved[-1]["run_id"], OWNER)
            assert saved["status"] == saved["stop_reason"] == ("cancelled" if stop == "cancel" else "timeout")
            assert saved["model_calls"] == saved["budget"]["used"]["model"] == 1
            assert len(saved["agent_calls"]) == len(supervisor.inputs) == 1
            assert not service.code_model.inputs
            assert saved["validation_calls"] == 0
            assert saved["artifacts"] == saved["attempts"] == saved["reviews"] == []
            assert saved["budget"]["used"]["retries"] == 0
            assert saved["budget"]["used"]["retrievals"] == len(retrieval_calls) == (1 if stage == "retrieve" else 0)
            assert (saved["task_spec"] is None) == (stage == "plan")
            assert saved["agent_calls"][0]["status"] == ("passed" if stage == "retrieve" else
                                                        "cancelled" if stop == "cancel" else "failed")
            assert saved["run_id"] not in usage._ledgers
            assert service._semaphore._value == 2
            async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
                own = await client.get("/api/v1/go/tasks/" + saved["run_id"], headers=HEADERS)
                assert own.status_code == 200 and own.json() == saved
                other = await client.get("/api/v1/go/tasks/" + saved["run_id"],
                                         headers={**HEADERS, "X-Account-Id": "2"})
                assert other.status_code == 404
                install(monkeypatch, setup)
                again = await client.post("/api/v1/go/tasks", json=payload, headers=HEADERS)
                assert again.status_code == 200 and again.json()["status"] == "passed"
        finally:
            if not job.done():
                job.cancel()
                try:
                    await job
                except asyncio.CancelledError:
                    pass
    asyncio.run(run())
