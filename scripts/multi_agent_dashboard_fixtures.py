"""S6 test-only dependencies and capture. Never calls a live model."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from app.config import GoMultiAgentSettings, settings
from app.go_validation.contracts import GoTaskRequest
from app.go_validation.runner import DockerGoRunner
from app.go_validation.service import GoTaskService
from app.go_validation.store import GoTaskStore
from test_multi_agent_agents import ScriptedModel, SOLUTION_A, TEST_A, fenced, plan_json, review_json
from test_multi_agent_workflow import StubRunner, BROKEN, BROKEN2, BROKEN3, revise_json

TEST_TOKEN = "s6-local-test-token"
LEGACY = json.loads((ROOT / "docs/go-validation-fixture-report.json").read_text())["results"][1]


def configure():
    settings.go_multi_agent = GoMultiAgentSettings(enabled=True, supervisor_window=65536, code_window=65536)
    settings.admin_token = TEST_TOKEN
    settings.ai_internal_token = "s6-local-gateway-token"
    settings.llm_api_key = settings.embedding_api_key = ""
    settings.ratelimit_enabled = False


class BlockingCode(ScriptedModel):
    async def ainvoke(self, messages):
        self.inputs.append(list(messages))
        await asyncio.Event().wait()


def service(store, case, *, docker=False):
    supervisor = [plan_json(), review_json()]
    codes = [fenced(("solution.go", SOLUTION_A), ("solution_test.go", TEST_A))]
    outcomes = ["passed"]
    if case == "repair":
        supervisor = [plan_json(), revise_json(), review_json()]
        codes.insert(0, fenced(("solution.go", BROKEN), ("solution_test.go", TEST_A)))
        outcomes = ["failed", "passed"]
    elif case == "failed":
        supervisor = [plan_json(), review_json(), review_json(), review_json()]
        codes = [fenced(("solution.go", body), ("solution_test.go", TEST_A)) for body in (BROKEN, BROKEN2, BROKEN3)]
        outcomes = ["failed"] * 3
    elif case in {"timeout", "unavailable"}:
        outcomes = [case]
    return GoTaskService(store, supervisor_model=ScriptedModel(*supervisor),
        code_model=BlockingCode() if case == "cancel" else ScriptedModel(*codes),
        runner=DockerGoRunner() if docker else StubRunner(*outcomes))


async def capture(output):
    configure()
    store = GoTaskStore(":memory:")
    data = {"provenance": "Captured from actual service; both models and validator substituted. Browser responses will be replaced.",
            "legacy": LEGACY, "cases": {}}
    try:
        for case in ("passed", "repair", "failed", "timeout", "unavailable"):
            request = GoTaskRequest(scenario="context_cancel", requirement="等待取消并传播 ctx.Err()，取消前不能提前返回")
            data["cases"][case] = [e async for e in service(store, case).stream(request, "admin", "capture-" + case)]
        output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    finally:
        store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(capture(parser.parse_args().output))
