"""Review-only regression probes. No live model, network, or Docker calls.

Failures assert intended behavior; do not weaken these assertions to green the review.
Run with repository root and tests on PYTHONPATH and the S0.1 offline guard.
"""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.agents.code_agent import CodeAgent
from app.agents.go_workflow import MultiAgentGoWorkflow, SharedBudget
from app.agents.role_runtime import extract_json, usage_of
from app.agents.supervisor import SupervisorAgent
from app.config import GoMultiAgentSettings, settings
from app.context.token_counter import TokenCounter
from app.go_validation.service import GoTaskService
from app.go_validation.store import GoTaskStore
from test_multi_agent_agents import ScriptedModel, SOLUTION_A, TEST_A, fenced, plan_json, review_json
from test_multi_agent_workflow import StubRunner, request


def config(**overrides):
    return GoMultiAgentSettings(**overrides)


def workflow(*, cfg=None, runner=None, unknown=False):
    class UnknownModel(ScriptedModel):
        async def ainvoke(self, messages, *args, **kwargs):
            result = await super().ainvoke(messages, *args, **kwargs)
            result.usage_metadata = None
            return result

    model_type = UnknownModel if unknown else ScriptedModel
    sup = model_type(plan_json(), review_json())
    code = model_type(fenced(("solution.go", SOLUTION_A), ("solution_test.go", TEST_A)))
    flow = MultiAgentGoWorkflow(supervisor=SupervisorAgent(model=sup),
                               code=CodeAgent(model=code),
                               runner=runner or StubRunner(), config=cfg)
    return flow, sup, code


class ReviewProbes(unittest.IsolatedAsyncioTestCase):
    async def test_enabled_switch_selects_multi_workflow(self):
        cfg = config(enabled=True, supervisor_window=32768, code_window=32768)
        model = ScriptedModel(fenced(("solution.go", SOLUTION_A), ("solution_test.go", TEST_A)))
        async def retrieve(_):
            return {"chunks": [], "sources": []}
        store = GoTaskStore(":memory:")
        try:
            with patch.object(settings, "go_multi_agent", cfg):
                result = await GoTaskService(store, model=model, runner=StubRunner(),
                                             retrieve=retrieve).run(request(), "review", "review-session")
            print("ENTRY", json.dumps({"enabled": True, "workflow": result.workflow_version,
                                      "status": result.status, "reviews": len(result.reviews),
                                      "model_calls": result.model_calls}), flush=True)
            self.assertEqual(result.workflow_version, "multi-v1")
        finally:
            store.close()

    async def test_role_input_budget_blocks_before_model_send(self):
        cfg = config(enabled=True, supervisor_window=32768, code_window=32768,
                     supervisor_input_tokens=1, code_input_tokens=1)
        flow, sup, code = workflow(cfg=cfg)
        with patch.object(settings, "go_multi_agent", cfg), patch.object(settings, "context_mode", "off"):
            result = await flow.run(request())
        count = TokenCounter().count(sup.inputs[0]) if sup.inputs else 0
        print("INPUT_BUDGET", json.dumps({"limit": 1, "actual_first_prompt_estimate": count,
                                         "model_sends": len(sup.inputs) + len(code.inputs),
                                         "status": result.status}), flush=True)
        self.assertEqual(len(sup.inputs) + len(code.inputs), 0)
        self.assertEqual(result.status, "budget_exceeded")

    async def test_validation_stage_timeout_is_retained_as_timeout(self):
        class SlowRunner:
            async def validate(self, bundle):
                await asyncio.sleep(0.2)
                raise AssertionError("cancelled before completion")
        flow, sup, code = workflow(cfg=config(validation_timeout=0.01), runner=SlowRunner())
        result = await flow.run(request())
        print("VALIDATION_TIMEOUT", json.dumps({"status": result.status, "error": result.error,
                "validation_calls": result.validation_calls, "reserved": flow.budget.used["validations"],
                "attempts": len(result.attempts), "supervisor_sends": len(sup.inputs)}), flush=True)
        self.assertEqual(result.status, "timeout")
        self.assertEqual(result.validation_calls, 1)
        self.assertEqual(len(result.attempts), 1)

    async def test_injected_role_usage_is_in_task_ledger(self):
        flow, _, _ = workflow()
        result = await flow.run(request())
        print("ROLE_LEDGERS", json.dumps({"agent_calls": result.model_calls,
                "context_model_calls": result.context_stats["model_calls"],
                "aggregate_tokens": result.token_usage,
                "context_tokens": result.context_stats["token_usage"]}), flush=True)
        self.assertEqual(result.context_stats["model_calls"], result.model_calls)

    async def test_unknown_usage_is_not_reported_as_known_zero(self):
        flow, _, _ = workflow(unknown=True)
        result = await flow.run(request())
        print("UNKNOWN_USAGE", json.dumps({"per_call": [c.token_usage for c in result.agent_calls],
                "aggregate": result.token_usage, "context_complete": result.context_stats["usage_complete"],
                "unknown_calls": result.context_stats["unknown_usage_calls"]}), flush=True)
        self.assertEqual(result.context_stats["unknown_usage_calls"], 3)
        self.assertFalse(result.context_stats["usage_complete"])
        self.assertNotEqual(result.token_usage, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})

    def test_partial_provider_usage_stays_unknown(self):
        actual = usage_of(SimpleNamespace(usage_metadata={"input_tokens": 12}))
        print("PARTIAL_USAGE", actual, flush=True)
        self.assertIsNone(actual)

    def test_json_surrounded_by_prose_can_be_parsed(self):
        payload = {"verdict": "approve"}
        self.assertEqual(extract_json("说明：" + json.dumps(payload) + "\n结束"), payload)

    async def test_configured_cleanup_budget_reaches_docker_adapter(self):
        # Execute the production Docker adapter, substituting only OS processes.
        # No Docker commands are actually sent in this probe.
        from multi_agent_fixtures import artifact
        cfg = config(cleanup_timeout=0.001)
        flow, _, _ = workflow(cfg=cfg)
        flow.runner = None
        flow.budget = SharedBudget.from_settings(cfg)
        stdout, stderr = asyncio.StreamReader(), asyncio.StreamReader()
        stdout.feed_data(json.dumps({"status": "passed", "go_version": "1.26.2", "stages": [
            {"stage": name, "exit_code": 0} for name in ("policy", "compile", "vet", "test")]}).encode())
        stdout.feed_eof()
        stderr.feed_eof()
        proc = SimpleNamespace(returncode=0, stdout=stdout, stderr=stderr,
                               wait=AsyncMock(return_value=0),
                               stdin=SimpleNamespace(write=lambda _: None, drain=AsyncMock(), close=lambda: None))
        async def slow_remove():
            await asyncio.sleep(0.03)
            return 0
        cleanup = SimpleNamespace(returncode=0, wait=slow_remove)
        observed = []
        real_wait_for = asyncio.wait_for
        async def capture_wait_for(awaitable, timeout):
            observed.append(timeout)
            return await real_wait_for(awaitable, timeout)
        async def spawn(*args, **kwargs):
            return cleanup if args[1] == "rm" else proc
        with patch("asyncio.create_subprocess_exec", spawn), patch("asyncio.wait_for", capture_wait_for):
            report = await flow._validate(artifact())
        print("CLEANUP_BUDGET", json.dumps({"configured": cfg.cleanup_timeout,
                "timeouts_used": observed, "status": report.status}), flush=True)
        self.assertIn(cfg.cleanup_timeout, observed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
