"""Multi-agent Go workflow: S1 pure policy, S4 shared budget, S3 closed-loop runner.

Pure decision functions never call models, tools, Docker or networks. The S3/S4
orchestrator and ledger below enforce the same rules at runtime: budgets are
reserved before any external request, the deadline is absolute for the whole task,
and terminal states come from server evidence only.
"""
import asyncio
import json
import time
import uuid
from enum import Enum
from typing import Literal

from pydantic import BaseModel, model_validator

from app.go_validation.contracts import (
    Attempt, CodeArtifact, FrozenContract, GO_VERSION, GoTaskRequest, MAX_REPAIRS,
    RemainingBudget, ReviewReport, StageReport, TaskSpec, ValidationReport,
    artifact_hash, bind_validation,
)


class WorkflowPhase(str, Enum):
    PLANNING = "planning"
    GENERATING = "generating"
    VALIDATING = "validating"
    REVIEWING = "reviewing"
    REPAIRING = "repairing"
    FINISHED = "finished"


_TRANSITIONS = {
    WorkflowPhase.PLANNING: {WorkflowPhase.GENERATING, WorkflowPhase.FINISHED},
    WorkflowPhase.GENERATING: {WorkflowPhase.VALIDATING, WorkflowPhase.FINISHED},
    WorkflowPhase.VALIDATING: {WorkflowPhase.REVIEWING, WorkflowPhase.FINISHED},
    WorkflowPhase.REVIEWING: {WorkflowPhase.REVIEWING, WorkflowPhase.REPAIRING, WorkflowPhase.FINISHED},
    WorkflowPhase.REPAIRING: {WorkflowPhase.VALIDATING, WorkflowPhase.FINISHED},
    WorkflowPhase.FINISHED: set(),
}


def transition(current: WorkflowPhase, target: WorkflowPhase) -> WorkflowPhase:
    current, target = WorkflowPhase(current), WorkflowPhase(target)
    if target not in _TRANSITIONS[current]:
        raise ValueError(f"非法状态流转: {current.value} -> {target.value}")
    return target


class WorkflowDecision(FrozenContract):
    action: Literal["finish", "repair", "retry_review"]
    status: Literal["running", "passed", "failed", "cancelled", "timeout", "unavailable", "budget_exceeded"]
    reason: Literal["completed", "validation_failed", "requirements_failed", "review_revision",
                    "review_error", "validation_report_error", "artifact_error", "repair_limit",
                    "no_progress", "budget_exceeded", "cancelled", "timeout", "unavailable"]

    @property
    def phase(self) -> WorkflowPhase:
        return {"finish": WorkflowPhase.FINISHED, "repair": WorkflowPhase.REPAIRING,
                "retry_review": WorkflowPhase.REVIEWING}[self.action]

    @model_validator(mode="after")
    def coherent_decision(self):
        if (self.action == "finish") == (self.status == "running"):
            raise ValueError("终态/运行态与路由动作不一致")
        if self.status == "passed" and self.reason != "completed":
            raise ValueError("成功终态必须由完成条件产生")
        return self


def _parse(model, value):
    # Revalidate even instances/model_copy/model_construct outputs at the trust boundary.
    return model.model_validate(value.model_dump() if isinstance(value, BaseModel) else value)


def machine_passed(report: ValidationReport) -> bool:
    return (report.status == "passed" and report.go_version == GO_VERSION and report.container_removed
            and [s.stage for s in report.stages] == ["policy", "compile", "vet", "test"]
            and all(s.exit_code == 0 and not s.truncated for s in report.stages))


def requirements_complete(task: TaskSpec, review: ReviewReport) -> bool:
    """Structural/evidence coverage, not a proof of semantic correctness."""
    checks = {c.requirement_id: c for c in review.requirement_checks}
    return all(r.requirement_id in checks and checks[r.requirement_id].status == "pass"
               for r in task.requirements if r.required)


def decide_after_review(task: TaskSpec, artifact: CodeArtifact, validation: ValidationReport,
                        review: ReviewReport | dict | None, remaining: RemainingBudget, *,
                        max_repairs: int = MAX_REPAIRS, previous_failed_hash: str | None = None,
                        cancelled: bool = False) -> WorkflowDecision:
    """Choose success, review retry, repair or a terminal result from server evidence.

All arguments must come from task-local server state. Models supply only review
content; they never choose status, remaining budget, or transition targets.
"""
    def finish(status, reason):
        return WorkflowDecision(action="finish", status=status, reason=reason)

    if type(max_repairs) is not int or not 0 <= max_repairs <= MAX_REPAIRS:
        raise ValueError("业务修复上限必须在 0..2 之间")
    remaining = _parse(RemainingBudget, remaining)
    if cancelled:
        return finish("cancelled", "cancelled")
    if remaining.seconds <= 0:
        return finish("timeout", "timeout")
    try:
        task, artifact = _parse(TaskSpec, task), _parse(CodeArtifact, artifact)
        if artifact.task_id != task.task_id or artifact.scenario != task.scenario:
            raise ValueError("产物不属于当前任务")
    except (ValueError, TypeError):
        return finish("failed", "artifact_error")
    try:
        validation = _parse(ValidationReport, validation)
        if any(getattr(validation, key) != getattr(artifact, key)
               for key in ("task_id", "artifact_id", "artifact_hash", "round")):
            raise ValueError("验证报告版本未绑定或不匹配")
    except (ValueError, TypeError):
        return finish("failed", "validation_report_error")
    if validation.status in ("unavailable", "timeout", "cancelled"):
        return finish(validation.status, validation.status)
    if validation.status == "passed" and not machine_passed(validation):
        return finish("failed", "validation_report_error")

    def review_error():
        if remaining.retries > 0 and remaining.model_calls > 0:
            return WorkflowDecision(action="retry_review", status="running", reason="review_error")
        return finish("failed", "review_error")

    try:
        review = _parse(ReviewReport, review)
        review.check_context(task, artifact)
    except (ValueError, TypeError):
        return review_error()
    required_ids = {r.requirement_id for r in task.requirements if r.required}
    if review.verdict == "cannot_assess" or not required_ids <= {c.requirement_id for c in review.requirement_checks}:
        return review_error()
    complete = requirements_complete(task, review)
    blocking = any(i.severity == "blocking" for i in review.issues)
    if machine_passed(validation) and review.verdict == "approve" and complete and not blocking:
        return finish("passed", "completed")
    if previous_failed_hash == artifact.artifact_hash:
        return finish("failed", "no_progress")
    if artifact.round >= max_repairs:
        return finish("failed", "repair_limit")
    if (remaining.model_calls < 2 or remaining.normal_calls < 2 or remaining.validations < 1):
        return finish("budget_exceeded", "budget_exceeded")
    reason = ("validation_failed" if not machine_passed(validation) else
              "requirements_failed" if not complete or blocking else "review_revision")
    return WorkflowDecision(action="repair", status="running", reason=reason)


class BudgetExceededError(Exception):
    """服务端预算/截止时间预占失败；调用方不得发送该请求。"""

    def __init__(self, message: str, *, kind: str):
        super().__init__(message)
        self.kind = kind  # model | retry | validation | retrieval | repair | deadline


class SharedBudget:
    """S4 全任务共享账本：外部请求发送前预占额度，失败请求同样计数、不返还。

    纯服务端状态：角色只读快照，模型无权修改额度或截止时间。截止时间是
    建账时刻起的绝对时间，不随修复轮次重置；没有释放额度的 API。
    """

    def __init__(self, *, max_normal_calls: int = 7, max_retries: int = 1,
                 max_model_calls: int = 8, max_repairs: int = MAX_REPAIRS,
                 max_validations: int = 3, max_retrievals: int = 1,
                 seconds: float = 360.0, clock=time.monotonic):
        if not (1 <= max_normal_calls <= 7 and 0 <= max_retries <= 1
                and max_normal_calls <= max_model_calls <= max_normal_calls + max_retries
                and 0 <= max_repairs <= MAX_REPAIRS and 1 <= max_validations <= 3
                and 0 <= max_retrievals <= 1 and seconds > 0):
            raise ValueError("预算参数超出首版硬上限")
        self._max = {"normal": max_normal_calls, "retries": max_retries, "model": max_model_calls,
                     "repairs": max_repairs, "validations": max_validations, "retrievals": max_retrievals}
        self._clock = clock
        self.seconds_total = seconds
        self._deadline = clock() + seconds
        self._used = {"normal": 0, "retries": 0, "model": 0,
                      "validations": 0, "retrievals": 0, "repairs": 0}

    @classmethod
    def from_settings(cls, cfg=None, *, deadline=None):
        from app.config import settings
        cfg = cfg or settings.go_multi_agent
        budget = cls(max_normal_calls=cfg.max_normal_calls, max_retries=cfg.max_retries,
                   max_model_calls=cfg.max_model_calls, max_repairs=cfg.max_repairs,
                   max_validations=cfg.max_validations, max_retrievals=cfg.max_retrievals,
                   seconds=cfg.task_timeout)
        if deadline is not None:
            budget._deadline = min(budget._deadline, deadline)
        return budget

    @property
    def used(self) -> dict:
        return dict(self._used)

    @property
    def limits(self) -> dict:
        return dict(self._max)

    def seconds_left(self) -> float:
        return max(0.0, self._deadline - self._clock())

    def _reserve(self, key: str, *, total: bool = False, kind: str | None = None):
        if self.seconds_left() <= 0:  # 截止后任何新请求都不再预占
            raise BudgetExceededError("任务截止时间已到", kind="deadline")
        if self._used[key] + 1 > self._max[key]:
            raise BudgetExceededError(f"超过 {key} 上限 {self._max[key]}", kind=kind or key)
        if total and self._used["model"] + 1 > self._max["model"]:
            raise BudgetExceededError(f"超过总模型调用上限 {self._max['model']}", kind="model")
        self._used[key] += 1
        if total:
            self._used["model"] += 1

    def reserve_model(self, *, retry: bool = False) -> None:
        """发送前预占一次模型调用；retry=True 消耗全任务唯一共享异常重试。"""
        if retry:
            self._reserve("retries", total=True, kind="retry")
        else:
            self._reserve("normal", total=True, kind="model")

    def reserve_validation(self) -> None:
        self._reserve("validations", kind="validation")

    def reserve_retrieval(self) -> None:
        self._reserve("retrievals", kind="retrieval")

    def reserve_repair(self) -> None:
        self._reserve("repairs", kind="repair")

    def stage_timeout(self, stage_limit: float, *, reserve: float = 0) -> float:
        """单阶段上限取角色上限与剩余任务时间的较小值；过期直接拒绝。"""
        left = self.seconds_left() - reserve
        if left <= 0:
            raise BudgetExceededError("任务截止时间已到", kind="deadline")
        return min(stage_limit, left)

    def snapshot(self) -> RemainingBudget:
        return RemainingBudget(
            normal_calls=self._max["normal"] - self._used["normal"],
            retries=self._max["retries"] - self._used["retries"],
            model_calls=self._max["model"] - self._used["model"],
            validations=self._max["validations"] - self._used["validations"],
            seconds=self.seconds_left())


_TERMINAL_ERRORS = {
    "repair_limit": "修复轮次已用完，仍存在未解决问题",
    "no_progress": "修复返回了相同产物，无进展",
    "budget_exceeded": "模型或验证预算不足",
    "review_error": "审查输出无效且共享重试额度耗尽",
    "validation_report_error": "验证报告未绑定当前代码版本",
    "artifact_error": "产物版本校验失败",
    "unavailable": "验证环境不可用，未进入代码修复",
    "timeout": "任务超过总时间预算",
    "cancelled": "任务被取消",
    "completed": "",
}


class MultiAgentGoWorkflow:
    """S3 闭环编排：计划 → 检索 → [生成/修复 → 隔离验证 → 审查 → 服务端判定]+ → 终态。

    通过判定、预算与终态全部由服务端强制（decide_after_review + SharedBudget），
    模型输出只是判定输入；每次代码变化重新验证并重新审查，报告经 bind_validation
    绑定当前版本，旧版本报告不可能被复用。环境故障（unavailable/timeout/cancelled）
    直接终态，不让模型反复修改基础设施问题。
    """

    def __init__(self, *, supervisor=None, code=None, runner=None, retrieve=None,
                 budget: SharedBudget | None = None, config=None, run_id: str | None = None,
                 on_update=None):
        from app.config import settings
        from app.agents.code_agent import CodeAgent
        from app.agents.supervisor import SupervisorAgent
        self.run_id = run_id or uuid.uuid4().hex
        self._cfg = config or settings.go_multi_agent
        self._injected = supervisor is not None or code is not None
        self.supervisor = supervisor or SupervisorAgent(run_id=self.run_id)
        self.code = code or CodeAgent(run_id=self.run_id)
        # Roles remain context-isolated but account to the same task, including
        # independently injected models. Final reporting precedes ledger cleanup.
        for role in (self.supervisor, self.code):
            role.runner.run_id = self.run_id
            role.runner.config = self._cfg
        self.runner = runner
        self.retrieve = retrieve
        self.budget = budget
        self.on_update = on_update
        self._calls = []  # 按实际发生顺序合并的角色调用记录
        self._drained = {}

    async def run(self, request: GoTaskRequest):
        from app.context import usage as context_usage
        request = GoTaskRequest.model_validate(request.model_dump() if isinstance(request, GoTaskRequest) else request)
        self._scenario = request.scenario
        self._started = time.perf_counter()
        self._spec, self._attempts, self._artifacts, self._reviews, self._sources = None, [], [], [], []
        self.references = "[]"
        if self.budget is None:
            self.budget = SharedBudget.from_settings(self._cfg)
        try:
            async with asyncio.timeout(self._cfg.task_timeout):
                return await self._execute(request)
        except asyncio.CancelledError:
            self._notify("cancelled", status="cancelled", stop_reason="cancelled")
            raise  # 取消必须传播；活动调用已被取消，容器清理由 runner 内部有界完成
        except BudgetExceededError as exc:
            status = "timeout" if exc.kind == "deadline" else "budget_exceeded"
            return self._result(status, status, error=str(exc))
        except TimeoutError:
            return self._result("timeout", "timeout", error="任务超过总时间预算")
        except Exception as exc:
            from app.agents.role_runtime import AgentError
            if isinstance(exc, AgentError):
                if exc.kind == "timeout":
                    return self._result("timeout", "timeout", error=str(exc))
                if exc.stage == "review":
                    return self._result("failed", "review_error", error=str(exc))
                return self._result("generation_error", "generation_error", error=str(exc))
            # 验证器等未预期异常按环境问题处理，不让模型修复基础设施。
            return self._result("unavailable", "unavailable", error=str(exc)[:300])
        finally:
            for run in {self.run_id, self.supervisor.runner.run_id, self.code.runner.run_id}:
                context_usage.discard(run)

    async def _execute(self, request: GoTaskRequest) -> object:
        self._spec = await self._plan(request)
        await self._do_retrieve(request)
        artifact = await self._produce()
        return await self._loop(artifact)

    async def _invoke(self, coro):
        """顺序执行一个角色调用；按实际发生顺序合并调用记录。"""
        try:
            return await coro
        finally:
            for runner in (self.supervisor.runner, self.code.runner):
                seen = self._drained.get(id(runner), 0)
                self._calls.extend(runner.calls[seen:])
                self._drained[id(runner)] = len(runner.calls)
            self._notify("model_result")

    def _notify(self, stage, *, status="running", stop_reason=None):
        if self.on_update is not None:
            self.on_update(stage, self._result(status, stop_reason))

    async def _plan(self, request: GoTaskRequest) -> TaskSpec:
        from app.agents.role_runtime import AgentError

        async def attempt():
            self.supervisor.runner.timeout = self.budget.stage_timeout(self._cfg.supervisor_timeout)
            return await self._invoke(self.supervisor.plan(request, self.references))
        self.budget.reserve_model()
        self._notify("planning")
        try:
            return await attempt()
        except AgentError as exc:
            if exc.kind == "timeout":
                raise
            self.budget.reserve_model(retry=True)  # 解析/可恢复失败重试同样计数
            return await attempt()

    async def _do_retrieve(self, request: GoTaskRequest):
        from app.context import usage as context_usage
        if self.retrieve is None:
            return
        self.budget.reserve_retrieval()
        usage_token = context_usage.current_run.set(self.run_id)
        try:
            raw = await asyncio.wait_for(self.retrieve(request.requirement),
                                         self.budget.stage_timeout(30.0))
            if isinstance(raw, str):
                raw = json.loads(raw)
            self.references = json.dumps(raw.get("chunks", []), ensure_ascii=False)[:16000]
            self._sources = [str(s) for s in raw.get("sources", [])][:20]
        except Exception:
            # 检索是辅助输入：失败降级为空资料继续任务，已预占额度不返还。
            self.references, self._sources = "[]", []
        finally:
            context_usage.current_run.reset(usage_token)

    async def _produce(self, repair_request=None):
        from app.agents.role_runtime import AgentError

        async def attempt():
            self.code.runner.timeout = self.budget.stage_timeout(self._cfg.code_timeout)
            if repair_request is None:
                return await self._invoke(self.code.generate(self._spec, self.references))
            return await self._invoke(self.code.repair(repair_request))
        self.budget.reserve_model()
        self._notify("repair" if repair_request else "generate")
        try:
            artifact = await attempt()
        except AgentError as exc:
            if exc.kind == "timeout":
                raise
            self.budget.reserve_model(retry=True)
            artifact = await attempt()
        self._artifacts.append(artifact)
        self._notify("generated")
        return artifact

    async def _validate(self, artifact: CodeArtifact) -> ValidationReport:
        from app.go_validation.runner import DockerGoRunner
        # Leave cleanup time inside the same absolute task deadline. The Docker
        # adapter owns execution and cleanup separately; its outer wait includes both.
        execution_timeout = self.budget.stage_timeout(
            self._cfg.validation_timeout, reserve=self._cfg.cleanup_timeout)
        self.budget.reserve_validation()
        runner = self.runner or DockerGoRunner(timeout=execution_timeout,
                                               cleanup_timeout=self._cfg.cleanup_timeout)
        production_runner = isinstance(runner, DockerGoRunner)
        if production_runner:
            runner.timeout = min(runner.timeout, execution_timeout)
            runner.cleanup_timeout = self._cfg.cleanup_timeout
        self._notify("validate")
        try:
            report = await asyncio.wait_for(runner.validate(artifact.bundle()),
                execution_timeout + (self._cfg.cleanup_timeout if production_runner else 0))
        except TimeoutError:
            previous = getattr(runner, "last_report", None)
            report = ValidationReport(status="timeout", artifact_hash=artifact.artifact_hash,
                container_removed=bool(previous and previous.artifact_hash == artifact.artifact_hash
                                       and previous.container_removed), stages=[
                    StageReport(stage="sandbox", exit_code=124, output="验证超过时间预算")])
        except asyncio.CancelledError:
            previous = getattr(runner, "last_report", None)
            report = ValidationReport(status="cancelled", artifact_hash=artifact.artifact_hash,
                container_removed=bool(previous and previous.artifact_hash == artifact.artifact_hash
                                       and previous.container_removed), stages=[
                    StageReport(stage="sandbox", exit_code=130, output="验证取消")])
            self._save_attempt(artifact, bind_validation(report, artifact))
            raise
        except Exception as exc:
            previous = getattr(runner, "last_report", None)
            report = ValidationReport(status="unavailable", artifact_hash=artifact.artifact_hash,
                container_removed=bool(previous and previous.artifact_hash == artifact.artifact_hash
                                       and previous.container_removed), stages=[
                    StageReport(stage="sandbox", exit_code=1, output=f"验证器异常: {str(exc)[:1000]}")])
        return bind_validation(report, artifact)  # 绑定当前版本；环境失败也绑定

    def _save_attempt(self, artifact, report):
        self._attempts.append(Attempt(number=artifact.round, bundle=artifact.bundle(),
                                      validation=report, change_summary=artifact.change_summary))
        self._notify("validated")

    async def _review(self, artifact: CodeArtifact, report: ValidationReport) -> ReviewReport | None:
        """执行一次审查；调用方必须已完成发送前预占（正常或共享重试）。"""
        from app.agents.role_runtime import AgentError
        self._notify("review")
        try:
            self.supervisor.runner.timeout = self.budget.stage_timeout(self._cfg.supervisor_timeout)
            review = await self._invoke(self.supervisor.review(self._spec, artifact, report))
        except AgentError as exc:
            if exc.kind == "timeout":
                raise
            return None  # 格式/调用失败交给 S1 判定的 review_error/retry_review 路径
        self._reviews.append(review)
        self._notify("reviewed")
        return review

    async def _loop(self, artifact: CodeArtifact):
        from app.go_validation.contracts import RepairRequest
        last_failed_hash = None
        while True:
            report = await self._validate(artifact)
            self._save_attempt(artifact, report)
            if report.status in ("unavailable", "timeout", "cancelled"):
                # 环境问题直接终态（S1 判定同义短路）：不让模型反复修基础设施。
                return self._result(report.status, report.status,
                                    error=_TERMINAL_ERRORS[report.status])
            self.budget.reserve_model()
            review = await self._review(artifact, report)
            while True:
                decision = decide_after_review(
                    self._spec, artifact, report, review, self.budget.snapshot(),
                    max_repairs=self._cfg.max_repairs, previous_failed_hash=last_failed_hash)
                if decision.action != "retry_review":
                    break
                # S1 判定确认重试与总额度仍有余量；retry 预占由共享账本最终强制。
                self.budget.reserve_model(retry=True)
                review = await self._review(artifact, report)
            if decision.status == "passed":
                return self._result("passed", "completed",
                                    final_summary=(review.summary if review else ""))
            if decision.action == "finish":
                return self._result(decision.status, decision.reason,
                                    error=_TERMINAL_ERRORS.get(decision.reason, decision.reason))
            # repair：RepairRequest 携带原需求、当前完整源码、实际错误日志、
            # 具体 blocking 问题 ID 与修复要求（S1 契约 + S2 提示词强制）。
            last_failed_hash = artifact.artifact_hash
            repair_request = RepairRequest(
                task_spec=self._spec, previous_artifact=artifact, validation_report=report,
                review_report=review, remaining_budget=self.budget.snapshot(),
                round=artifact.round + 1)
            self.budget.reserve_repair()
            artifact = await self._produce(repair_request)

    def _result(self, status: str, stop_reason: str | None, *, error: str | None = None,
                final_summary: str = ""):
        from app.context import usage as context_usage
        for runner in (self.supervisor.runner, self.code.runner):  # 终态前补齐调用记录
            seen = self._drained.get(id(runner), 0)
            self._calls.extend(runner.calls[seen:])
            self._drained[id(runner)] = len(runner.calls)
        calls = self._calls
        measured = context_usage.ledger(self.run_id).report()
        from app.go_validation.contracts import GoTaskResult
        return GoTaskResult(
            run_id=self.run_id, status=status, scenario=self._scenario,
            attempts=self._attempts, sources=self._sources,
            model_calls=len(calls), validation_calls=self.budget.used["validations"],
            elapsed_ms=round((time.perf_counter() - self._started) * 1000, 1),
            error=error, model_source="fixture" if self._injected else "configured",
            token_usage=measured["token_usage"],
            context_stats=measured,
            budget={"limits": self.budget.limits, "used": self.budget.used,
                    "remaining_seconds": self.budget.seconds_left(), "task_seconds": self.budget.seconds_total},
            workflow_version="multi-v1", task_spec=self._spec,
            artifacts=self._artifacts, reviews=self._reviews, agent_calls=calls,
            stop_reason=stop_reason, final_summary=final_summary)


async def run_in_graph(state):
    """The real Go service enters the same reviewed multi-agent implementation."""
    from langgraph.config import get_stream_writer
    from app.config import settings
    from app.agents.code_agent import CodeAgent
    from app.agents.supervisor import SupervisorAgent
    from app.go_validation.contracts import GoTaskResult

    cfg = state.get("go_multi_config") or settings.go_multi_agent
    run_id = state["run_id"]
    supervisor_model = state.get("go_supervisor_model")
    code_model = state.get("go_code_model")
    if supervisor_model is None:
        supervisor_model = state.get("go_model")
    if code_model is None:
        code_model = state.get("go_model")
    if not settings.llm_api_key and (supervisor_model is None or code_model is None):
        result = GoTaskResult(run_id=run_id, scenario=state["go_request"]["scenario"],
            status="unavailable", workflow_version="multi-v1", stop_reason="unavailable",
            error="未配置 AIROBOT_LLM_API_KEY")
        if state.get("go_result_ref") is not None:
            state["go_result_ref"]["result"] = result.model_dump()
        return {"go_result": result.model_dump(), "go_status": result.status}

    writer = get_stream_writer()
    published = {"attempts": 0, "calls": 0, "validations": 0, "usage": 0}
    def publish(stage, result):
        data = result.model_dump()
        if state.get("go_result_ref") is not None:
            state["go_result_ref"]["result"] = data
        writer({"type": "go_progress", "stage": stage, "result": data})
        role = ("supervisor" if stage in {"planning", "review", "reviewed"} else
                "code" if stage in {"generate", "repair", "generated"} else "validator" if stage in {"validate", "validated"} else None)
        current_round = data["artifacts"][-1]["round"] if data["artifacts"] else 0
        pending_repair = stage == "repair" or (stage == "model_result" and data["agent_calls"]
                                               and data["agent_calls"][-1]["stage"] == "repair")
        writer({"type": "go_stage", "stage": stage, "message": stage,
                "role": role, "status": result.status,
                "round": current_round + 1 if pending_repair else current_round})
        counts = (result.model_calls, result.validation_calls)
        if counts != (published["calls"], published["validations"]):
            writer({"type": "go_call", "model_calls": counts[0], "validations": counts[1],
                    "tools": counts[1] + workflow.budget.used["retrievals"]})
            published.update(calls=counts[0], validations=counts[1])
        for attempt in data["attempts"][published["attempts"]:]:
            writer({"type": "go_attempt", "attempt": attempt})
        published["attempts"] = len(data["attempts"])
        for call in data["agent_calls"][published["usage"]:]:
            if call["token_usage"] is not None:
                writer({"type": "go_usage", "usage": call["token_usage"],
                        "role": call["role"], "stage": call["stage"], "model": call["model"]})
        published["usage"] = len(data["agent_calls"])

    async def retrieve(query):
        from app.agents.tools import search_knowledge_tool
        return await search_knowledge_tool.ainvoke({"query": query})

    retrieval = state.get("go_retrieve")
    if retrieval is None and settings.embedding_api_key:
        retrieval = retrieve
    # Include service queue time in the same deadline; never reset at graph entry.
    budget = SharedBudget.from_settings(cfg, deadline=state.get("go_deadline"))
    workflow = MultiAgentGoWorkflow(
        supervisor=SupervisorAgent(model=supervisor_model, run_id=run_id),
        code=CodeAgent(model=code_model, run_id=run_id), runner=state.get("go_runner"),
        retrieve=retrieval, budget=budget, config=cfg, run_id=run_id, on_update=publish)
    workflow._injected = supervisor_model is not None or code_model is not None
    # LangGraph may finish cancelling its stream before every nested model task
    # has unwound. Keep a server-only handle so Service can join cleanup before
    # saving the last snapshot and releasing the HTTP session.
    task = asyncio.create_task(workflow.run(state["go_request"]))
    if state.get("go_result_ref") is not None:
        state["go_result_ref"]["task"] = task
    result = await task
    publish("finish", result)
    return {"go_result": result.model_dump(), "go_status": result.status}
