"""JSON 与 SSE 都消费同一个图执行流，并保存账户隔离的完整报告。"""
import asyncio
import hashlib
import time
import uuid
from contextlib import aclosing, asynccontextmanager
from pathlib import Path

from app.go_validation.contracts import GoTaskRequest, GoTaskResult
from app.go_validation.store import GoTaskStore
from app.services.concurrency import run_blocking, finish_cleanup
from app.services.tracing import traces
from app.context import usage as context_usage
from app.config import settings

TASK_TIMEOUT = 360  # 围栏格式单次生成 15~60s，3 轮生成加验证在 180s 内放不下（99 样本实测校准）。
store = GoTaskStore(str(Path(__file__).resolve().parents[2] / "data" / "go_tasks.sqlite3"))


class GoTaskService:
    def __init__(self, task_store=None, timeout=TASK_TIMEOUT, model=None, runner=None, retrieve=None,
                 supervisor_model=None, code_model=None):
        self.store = task_store if task_store is not None else store
        self.timeout = timeout
        self.model, self.runner, self.retrieve = model, runner, retrieve
        self.supervisor_model, self.code_model = supervisor_model, code_model
        self._semaphore = asyncio.Semaphore(2)

    async def _stop_workflow(self, state):
        task = state.get("go_result_ref", {}).get("task")
        if task is not None:
            if not task.done() and not task.cancelling():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                # This is the child task's expected stop, not a swallowed
                # cancellation of the request (which the caller re-raises).
                pass

    @asynccontextmanager
    async def _execution_slot(self, state):
        async with self._semaphore:
            try:
                yield
            finally:
                # A stopping sandbox still consumes capacity. Join its cleanup
                # before admitting another task, including on stream disconnect.
                await finish_cleanup(self._stop_workflow(state))

    def result(self, state, started, *, latest=False):
        # The task-local reference retains the final cancellation snapshot even
        # when graph cancellation prevents draining its remaining stream events.
        # Normal events persist their own snapshot, never a future version that
        # the graph has already published while the client is still consuming.
        snapshot = (state.get("go_result_ref", {}).get("result", state.get("go_result"))
                    if latest else state.get("go_result"))
        if snapshot is not None:
            data = dict(snapshot)
            data.update(status=state["go_status"], elapsed_ms=round((time.perf_counter()-started)*1000, 1))
            if state.get("go_error"):
                reason = state["go_status"] if state["go_status"] != "failed" else "unavailable"
                data.update(error=state["go_error"], stop_reason=reason)
            return GoTaskResult.model_validate(data)
        return GoTaskResult(run_id=state["run_id"], status=state["go_status"],
                scenario=state["go_request"]["scenario"], attempts=state.get("go_attempts", []),
                sources=state.get("go_sources", []), model_calls=state.get("go_model_calls", 0),
                validation_calls=state.get("go_validations", 0), error=state.get("go_error"),
                token_usage=state.get("go_usage", {}), model_source="fixture" if self.model is not None else "configured",
                context_stats=context_usage.ledger(state["run_id"]).report(),
                elapsed_ms=round((time.perf_counter()-started)*1000, 1))

    async def stream(self, request: GoTaskRequest, principal: str, session_key: str):
        from app.agents.graph import get_agent_graph
        owner = hashlib.sha256(principal.encode()).hexdigest()
        started = time.perf_counter()
        cfg = settings.go_multi_agent
        timeout = min(self.timeout, cfg.task_timeout) if cfg.enabled else self.timeout
        state = {"run_id": uuid.uuid4().hex, "session_id": session_key,
                 "go_request": request.model_dump(), "go_status": "running",
                 "go_attempts": [], "go_model_calls": 0, "go_tools": 0, "go_validations": 0,
                 "go_model": self.model, "go_runner": self.runner, "go_retrieve": self.retrieve,
                 "go_supervisor_model": self.supervisor_model, "go_code_model": self.code_model,
                 "go_multi_config": cfg, "go_deadline": time.monotonic() + timeout}
        if cfg.enabled:
            state["go_result"] = GoTaskResult(run_id=state["run_id"], status="running",
                scenario=request.scenario, workflow_version="multi-v1").model_dump()
            state["go_result_ref"] = {"result": state["go_result"]}
        try:
            # Persist and guard even the first yield: a client may close as soon
            # as go_start arrives, before acquiring the execution semaphore.
            await run_blocking(self.store.save, state["run_id"], owner,
                               self.result(state, started).model_dump())
            yield {"type": "go_start", "run_id": state["run_id"],
                   "workflow_version": "multi-v1" if cfg.enabled else "single-v1"}
            async with asyncio.timeout(timeout):
                async with self._execution_slot(state):
                    async with aclosing(get_agent_graph().astream(state, stream_mode=["updates", "custom"])) as updates:
                        async for mode, update in updates:
                            if mode == "custom":
                                if update.get("type") == "go_progress":
                                    state["go_result"] = update["result"]
                                    state["go_status"] = update["result"]["status"]
                                    await run_blocking(self.store.save, state["run_id"], owner,
                                                       self.result(state, started).model_dump())
                                elif update.get("type") == "go_call":
                                    for public, internal in (("model_calls", "go_model_calls"),
                                                             ("tools", "go_tools"), ("validations", "go_validations")):
                                        if public in update:
                                            state[internal] = update[public]
                                elif update.get("type") == "go_usage":
                                    state["go_usage"] = {k:state.get("go_usage",{}).get(k,0)+v
                                                         for k,v in update["usage"].items()}
                                yield {**update, "run_id": state["run_id"]}
                            else:
                                for values in update.values():
                                    state.update(values)
                                await run_blocking(self.store.save, state["run_id"], owner,
                                                   self.result(state, started).model_dump())
        except TimeoutError:
            await finish_cleanup(self._stop_workflow(state))
            state.update(go_status="timeout", go_error="任务超过总时间预算")
        except (asyncio.CancelledError, GeneratorExit):
            async def cancel_and_save():
                await self._stop_workflow(state)
                state.update(go_status="cancelled", go_error="请求取消；清理结果见各轮验证报告")
                await run_blocking(self.store.save, state["run_id"], owner,
                                   self.result(state, started, latest=True).model_dump())
            try:
                await finish_cleanup(cancel_and_save())
            finally:
                context_usage.discard(state["run_id"])
            raise
        except Exception:
            await finish_cleanup(self._stop_workflow(state))
            state.update(go_status="failed", go_error="任务执行失败，请通过 run_id 查看已有报告")
        result = self.result(state, started, latest=True)
        try:
            await finish_cleanup(run_blocking(self.store.save, state["run_id"], owner, result.model_dump()))
            traces.record({"run_id": result.run_id, "session_id": session_key, "intent": "go_validation",
                           "status": 200 if result.status == "passed" else 422,
                           "tool_calls": result.validation_calls if cfg.enabled else state.get("go_tools", 0),
                           "total_ms": result.elapsed_ms,"context_usage":result.context_stats})
        finally:
            context_usage.discard(state["run_id"])
        yield {"type": "go_done", "run_id": state["run_id"], "result": result.model_dump()}

    async def run(self, request, principal, session_key):
        # 普通响应也消费相同流，避免两个入口各自维护一套修复逻辑。
        async with aclosing(self.stream(request, principal, session_key)) as events:
            async for event in events:
                if event["type"] == "go_done":
                    return GoTaskResult.model_validate(event["result"])
        raise RuntimeError("任务未产生最终报告")


service = GoTaskService()
