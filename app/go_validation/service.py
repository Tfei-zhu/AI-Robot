"""JSON 与 SSE 都消费同一个图执行流，并保存账户隔离的完整报告。"""
import asyncio
import hashlib
import time
import uuid
from contextlib import aclosing
from pathlib import Path

from app.go_validation.contracts import GoTaskRequest, GoTaskResult
from app.go_validation.store import GoTaskStore
from app.services.concurrency import run_blocking
from app.services.tracing import traces

TASK_TIMEOUT = 180
store = GoTaskStore(str(Path(__file__).resolve().parents[2] / "data" / "go_tasks.sqlite3"))


class GoTaskService:
    def __init__(self, task_store=None, timeout=TASK_TIMEOUT, model=None, runner=None, retrieve=None):
        self.store = task_store if task_store is not None else store
        self.timeout = timeout
        self.model, self.runner, self.retrieve = model, runner, retrieve
        self._semaphore = asyncio.Semaphore(2)

    def result(self, state, started):
        return GoTaskResult(run_id=state["run_id"], status=state["go_status"],
                scenario=state["go_request"]["scenario"], attempts=state.get("go_attempts", []),
                sources=state.get("go_sources", []), model_calls=state.get("go_model_calls", 0),
                validation_calls=state.get("go_validations", 0), error=state.get("go_error"),
                token_usage=state.get("go_usage", {}), model_source="fixture" if self.model is not None else "configured",
                elapsed_ms=round((time.perf_counter()-started)*1000, 1))

    async def stream(self, request: GoTaskRequest, principal: str, session_key: str):
        from app.agents.graph import get_agent_graph
        owner = hashlib.sha256(principal.encode()).hexdigest()
        started = time.perf_counter()
        state = {"run_id": uuid.uuid4().hex, "session_id": session_key,
                 "go_request": request.model_dump(), "go_status": "running",
                 "go_attempts": [], "go_model_calls": 0, "go_tools": 0, "go_validations": 0,
                 "go_model": self.model, "go_runner": self.runner, "go_retrieve": self.retrieve}
        yield {"type": "go_start", "run_id": state["run_id"]}
        try:
            async with asyncio.timeout(self.timeout):
                async with self._semaphore:
                    async with aclosing(get_agent_graph().astream(state, stream_mode=["updates", "custom"])) as updates:
                        async for mode, update in updates:
                            if mode == "custom":
                                if update.get("type") == "go_call":
                                    for public, internal in (("model_calls", "go_model_calls"),
                                                             ("tools", "go_tools"), ("validations", "go_validations")):
                                        if public in update:
                                            state[internal] = update[public]
                                elif update.get("type") == "go_usage":
                                    state["go_usage"] = {k:state.get("go_usage",{}).get(k,0)+v
                                                         for k,v in update["usage"].items()}
                                yield update
                            else:
                                for values in update.values():
                                    state.update(values)
                                await run_blocking(self.store.save, state["run_id"], owner,
                                                   self.result(state, started).model_dump())
        except TimeoutError:
            state.update(go_status="timeout", go_error="任务超过总时间预算")
        except (asyncio.CancelledError, GeneratorExit):
            state.update(go_status="cancelled", go_error="请求取消，沙箱已请求清理")
            await run_blocking(self.store.save, state["run_id"], owner, self.result(state, started).model_dump())
            raise
        except Exception:
            state.update(go_status="failed", go_error="任务执行失败，请通过 run_id 查看已有报告")
        result = self.result(state, started)
        await run_blocking(self.store.save, state["run_id"], owner, result.model_dump())
        traces.record({"run_id": result.run_id, "session_id": session_key, "intent": "go_validation",
                       "status": 200 if result.status == "passed" else 422,
                       "tool_calls": state.get("go_tools", 0), "total_ms": result.elapsed_ms})
        yield {"type": "go_done", "result": result.model_dump()}

    async def run(self, request, principal, session_key):
        # 普通响应也消费相同流，避免两个入口各自维护一套修复逻辑。
        async with aclosing(self.stream(request, principal, session_key)) as events:
            async for event in events:
                if event["type"] == "go_done":
                    return GoTaskResult.model_validate(event["result"])
        raise RuntimeError("任务未产生最终报告")


service = GoTaskService()
