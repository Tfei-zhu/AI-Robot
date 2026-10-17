"""Review regressions: real service entry, request guards, evidence and cleanup.

Models are scripted; Docker boundary tests substitute OS processes only.
No test invokes a paid model or changes the review's frozen probes.
"""
import asyncio
import hashlib
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.agents.code_agent import CodeAgent
from app.agents.go_workflow import BudgetExceededError, MultiAgentGoWorkflow, SharedBudget
from app.agents.role_runtime import extract_json, usage_of
from app.agents.supervisor import SupervisorAgent
from app.config import GoMultiAgentSettings, settings
from app.context import usage
from app.go_validation.service import GoTaskService
from app.go_validation.runner import DockerGoRunner
from app.go_validation.store import GoTaskStore
from multi_agent_fixtures import artifact
from test_multi_agent_agents import ScriptedModel, SOLUTION_A, TEST_A, fenced, plan_json, review_json
from test_multi_agent_workflow import BROKEN, StubRunner, request, revise_json


def code_reply():
    return fenced(("solution.go", SOLUTION_A), ("solution_test.go", TEST_A))


def cfg(**overrides):
    return GoMultiAgentSettings(enabled=True, supervisor_window=32768, code_window=32768, **overrides)


def flow(config=None, runner=None, supervisor=None, code=None):
    supervisor = supervisor or ScriptedModel(plan_json(), review_json())
    code = code or ScriptedModel(code_reply())
    return MultiAgentGoWorkflow(supervisor=SupervisorAgent(model=supervisor),
        code=CodeAgent(model=code), runner=runner or StubRunner(), config=config or cfg()), supervisor, code


class MultiAgentRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_service_selects_new_path_and_persists_review(self):
        store = GoTaskStore(":memory:")
        self.addCleanup(store.close)
        service = GoTaskService(store, supervisor_model=ScriptedModel(plan_json(), review_json()),
                                code_model=ScriptedModel(code_reply()), runner=StubRunner())
        with patch.object(settings, "go_multi_agent", cfg()):
            result = await service.run(request(), "account/test", "session")
        self.assertEqual((result.workflow_version, result.status, result.model_calls), ("multi-v1", "passed", 3))
        self.assertEqual(len(result.reviews), 1)
        self.assertEqual(result.context_stats["token_usage"]["total_tokens"], 138)
        saved = store.get(result.run_id, hashlib.sha256(b"account/test").hexdigest())
        self.assertEqual(saved["reviews"][0]["artifact_hash"], result.artifacts[-1].artifact_hash)
        self.assertIsNone(store.get(result.run_id, hashlib.sha256(b"account/other").hexdigest()))
        self.assertNotIn(result.run_id, usage._ledgers)

    async def test_switch_off_uses_original_path_even_when_graph_was_cached(self):
        store = GoTaskStore(":memory:")
        self.addCleanup(store.close)
        from app.agents.graph import get_agent_graph
        with patch.object(settings, "go_multi_agent", cfg()):
            get_agent_graph()
        service = GoTaskService(store, model=ScriptedModel(code_reply()), runner=StubRunner())
        with patch.object(settings, "go_multi_agent", GoMultiAgentSettings()):
            result = await service.run(request(), "account/test", "session")
        self.assertEqual((result.workflow_version, result.status), ("single-v1", "passed"))
        self.assertFalse(result.reviews)

    async def test_service_cannot_pass_failed_validation_when_review_approves(self):
        store = GoTaskStore(":memory:")
        self.addCleanup(store.close)
        service = GoTaskService(store, supervisor_model=ScriptedModel(plan_json(), review_json()),
                                code_model=ScriptedModel(code_reply()), runner=StubRunner("failed"))
        with patch.object(settings, "go_multi_agent", cfg(max_repairs=0)):
            result = await service.run(request(), "test", "session")
        self.assertEqual((result.workflow_version, result.status), ("multi-v1", "failed"))
        self.assertEqual(result.reviews[0].verdict, "approve")

    async def test_role_limit_blocks_plan_and_code_without_spending_retry(self):
        for limits, sends in (({"supervisor_input_tokens": 1}, (0, 0)),
                              ({"code_input_tokens": 1}, (1, 0))):
            with self.subTest(limits=limits):
                task, sup, code = flow(cfg(**limits))
                with patch.object(settings, "context_mode", "off"):
                    result = await task.run(request())
                self.assertEqual(result.status, "budget_exceeded")
                self.assertEqual((len(sup.inputs), len(code.inputs)), sends)
                self.assertEqual(task.budget.used["retries"], 0)
                self.assertEqual(result.context_stats["model_calls"], sum(sends))

    async def test_validation_timeout_preserves_bound_report_and_count(self):
        class Slow:
            async def validate(self, bundle):
                await asyncio.sleep(1)
        task, sup, _ = flow(cfg(validation_timeout=0.01), Slow())
        result = await task.run(request())
        self.assertEqual((result.status, result.validation_calls), ("timeout", 1))
        self.assertEqual(result.attempts[0].validation.artifact_hash, result.artifacts[0].artifact_hash)
        self.assertEqual(result.attempts[0].validation.stages[0].exit_code, 124)
        self.assertEqual(len(sup.inputs), 1)

    async def test_partial_usage_keeps_known_subtotal_and_unknown_total(self):
        class Partial(ScriptedModel):
            async def ainvoke(self, messages):
                response = await super().ainvoke(messages)
                return SimpleNamespace(content=response.content, usage_metadata={"input_tokens": 12})
        task, _, _ = flow(code=Partial(code_reply()))
        result = await task.run(request())
        self.assertIsNone(result.token_usage)
        self.assertFalse(result.context_stats["usage_complete"])
        self.assertEqual(result.context_stats["unknown_usage_calls"], 1)
        self.assertEqual(result.context_stats["known_token_usage"],
                         {"input_tokens": 36, "output_tokens": 68, "total_tokens": 92})
        self.assertIsNone(result.agent_calls[1].token_usage)
        self.assertEqual(result.context_stats["model_calls"], 3)

    async def test_no_usage_is_never_a_complete_zero_total(self):
        class Unknown(ScriptedModel):
            async def ainvoke(self, messages):
                response = await super().ainvoke(messages)
                response.usage_metadata = None
                return response
        task, _, _ = flow(supervisor=Unknown(plan_json(), review_json()), code=Unknown(code_reply()))
        result = await task.run(request())
        self.assertIsNone(result.token_usage)
        self.assertEqual(result.context_stats["unknown_usage_calls"], 3)
        self.assertFalse(result.context_stats["usage_complete"])

    async def test_json_prose_and_nested_braces_do_not_spend_retry(self):
        payload = {"value": {"text": "quoted } brace"}}
        self.assertEqual(extract_json("说明："+json.dumps(payload)+"\n结束"), payload)
        self.assertEqual(extract_json("```json\n"+json.dumps(payload)+"\n```"), payload)
        task, _, _ = flow(supervisor=ScriptedModel("说明："+plan_json()+"\n结束", review_json()))
        result = await task.run(request())
        self.assertEqual(result.status, "passed")
        self.assertEqual(task.budget.used["retries"], 0)

    def test_partial_or_invalid_provider_metadata_stays_unknown(self):
        for metadata in ({"input_tokens": 12}, {}, None,
                         {"input_tokens": 12, "output_tokens": None, "total_tokens": 12}):
            with self.subTest(metadata=metadata):
                self.assertIsNone(usage_of(SimpleNamespace(usage_metadata=metadata)))

    async def test_cleanup_time_is_reserved_before_starting_validation(self):
        clock = [0.0]
        budget = SharedBudget(seconds=20, clock=lambda: clock[0])
        runner = StubRunner()
        task, _, _ = flow(cfg(cleanup_timeout=5), runner)
        task.budget = budget
        observed = []
        wait_for = asyncio.wait_for
        async def capture(coro, timeout):
            observed.append(timeout)
            return await wait_for(coro, timeout)
        with patch("asyncio.wait_for", capture):
            await task._validate(artifact())
        self.assertEqual(observed, [15])
        clock[0] = 15  # only the cleanup reservation remains
        with self.assertRaises(BudgetExceededError):
            await task._validate(artifact())
        self.assertEqual(len(runner.bundles), 1)

    async def test_docker_cleanup_uses_configured_timeout_and_refuses_false_success(self):
        task, _, _ = flow(cfg(cleanup_timeout=0.001))
        task.runner = None
        task.budget = SharedBudget.from_settings(task._cfg)
        stdout, stderr = asyncio.StreamReader(), asyncio.StreamReader()
        stdout.feed_data(json.dumps({"status": "passed", "stages": [
            {"stage": s, "exit_code": 0} for s in ("policy", "compile", "vet", "test")]}).encode())
        stdout.feed_eof()
        stderr.feed_eof()
        proc = SimpleNamespace(returncode=0, stdout=stdout, stderr=stderr, wait=AsyncMock(return_value=0),
            stdin=SimpleNamespace(write=lambda _: None, drain=AsyncMock(), close=lambda: None))
        async def slow_remove():
            await asyncio.sleep(0.03)
            return 0
        cleanup = SimpleNamespace(returncode=0, wait=slow_remove)
        async def spawn(*args, **kwargs):
            return cleanup if args[1] == "rm" else proc
        with patch("asyncio.create_subprocess_exec", spawn):
            report = await task._validate(artifact())
        self.assertEqual(report.status, "unavailable")
        self.assertFalse(report.container_removed)

    async def test_service_cancel_during_review_preserves_last_call_and_usage(self):
        entered = asyncio.Event()
        class BlockingReview(ScriptedModel):
            async def ainvoke(self, messages):
                if self.inputs:
                    self.inputs.append(list(messages))
                    entered.set()
                    await asyncio.Event().wait()
                return await super().ainvoke(messages)
        store = GoTaskStore(":memory:")
        self.addCleanup(store.close)
        service = GoTaskService(store, supervisor_model=BlockingReview(plan_json()),
                                code_model=ScriptedModel(code_reply()), runner=StubRunner())
        events = []
        async def consume():
            async for event in service.stream(request(), "cancel-test", "session"):
                events.append(event)
        with patch.object(settings, "go_multi_agent", cfg()):
            job = asyncio.create_task(consume())
            await asyncio.wait_for(entered.wait(), 5)
            job.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await job
        result = store.get(events[0]["run_id"], hashlib.sha256(b"cancel-test").hexdigest())
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["model_calls"], 3)
        self.assertEqual(result["agent_calls"][-1]["status"], "cancelled")
        self.assertEqual(result["context_stats"]["unknown_usage_calls"], 1)
        self.assertEqual(len(result["attempts"]), 1)


@unittest.skipUnless(os.environ.get("AIROBOT_TEST_DOCKER") == "1", "启用真实 Docker 服务入口测试")
class RealServiceRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_service_first_pass_and_repair_use_real_docker(self):
        for repair in (False, True):
            with self.subTest(repair=repair):
                store = GoTaskStore(":memory:")
                supervisor = ScriptedModel(plan_json(), *([revise_json()] if repair else []), review_json())
                code = ScriptedModel(*([fenced(("solution.go", BROKEN), ("solution_test.go", TEST_A))]
                                       if repair else []), code_reply())
                runner = DockerGoRunner()
                service = GoTaskService(store, supervisor_model=supervisor, code_model=code, runner=runner)
                try:
                    with patch.object(settings, "go_multi_agent", cfg()):
                        result = await service.run(request(), "docker-test", "session")
                    self.assertEqual((result.workflow_version, result.status), ("multi-v1", "passed"))
                    self.assertEqual(len(result.attempts), 2 if repair else 1)
                    self.assertEqual(len(result.reviews), 2 if repair else 1)
                    self.assertTrue(all(a.validation.container_removed for a in result.attempts))
                    if repair:
                        self.assertEqual(result.attempts[0].validation.status, "failed")
                    self.assertEqual(result.context_stats["model_calls"], result.model_calls)
                    self.assertEqual(result.model_calls, 5 if repair else 3)
                finally:
                    store.close()
