"""第一版契约：固定工具链、单包源码、三个场景与最多两次修复。"""
import hashlib
import json
import re
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

GO_VERSION = "1.26.2"
MAX_REPAIRS = 2
MAX_SOURCE_BYTES = 65536
ContractId = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128,
                                             pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")]
ArtifactHash = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-f0-9]{64}$")]
ContractText = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=8000)]
StopReason = Literal["completed", "validation_failed", "requirements_failed", "review_revision",
                     "review_error", "validation_report_error", "artifact_error", "repair_limit",
                     "no_progress", "budget_exceeded", "cancelled", "timeout", "unavailable",
                     "clarification_needed", "generation_error"]
Scenario = Literal["context_cancel", "worker_pool", "channel"]
SCENARIO_SPECS = {
    "context_cancel": "package example；实现 WaitForCancel(ctx context.Context) error，等待取消后返回 ctx.Err()。",
    "worker_pool": "package example；实现 WorkerPool(ctx context.Context, jobs []int, workers int) ([]int, error)。"
                   "最多 workers 个工作协程，每个输入乘二并保持输出顺序，不修改输入；workers<=0 返回错误；取消返回错误。",
    "channel": "package example；实现 SumChannel(ctx context.Context, input <-chan int) (int, error)。"
               "读取并求和，channel 关闭后返回总和；取消时返回 ctx.Err()；nil channel 也必须响应取消。",
}


class SourceFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=4, max_length=64)
    content: str = Field(min_length=1, max_length=MAX_SOURCE_BYTES)

    @model_validator(mode="after")
    def safe_name(self):
        # 只允许当前目录的 Go 文件，禁止路径穿越、隐藏文件及工具链配置。
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*\.go", self.name):
            raise ValueError("仅允许普通 Go 文件名，不能包含路径")
        return self


class CodeBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    files: list[SourceFile] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def complete_package(self):
        names = [f.name for f in self.files]
        # Windows 文件名大小写不敏感，提前拒绝碰撞。
        if len(set(n.lower() for n in names)) != len(names):
            raise ValueError("文件名重复")
        if not any(n.endswith("_test.go") for n in names):
            raise ValueError("必须提供测试文件")
        if not any(not n.endswith("_test.go") for n in names):
            raise ValueError("必须提供实现文件")
        if sum(len(f.content.encode("utf-8")) for f in self.files) > MAX_SOURCE_BYTES:
            raise ValueError("源码总量超过 64 KiB")
        return self


class GoTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement: str = Field(min_length=5, max_length=8000)
    scenario: Scenario
    session_id: str | None = Field(default=None, min_length=1, max_length=128,
                                   pattern=r"^[A-Za-z0-9_-]+$")


class StageReport(BaseModel):
    stage: Literal["policy", "compile", "vet", "test", "sandbox"]
    exit_code: int
    output: str = ""
    elapsed_ms: float = 0
    truncated: bool = False


class ValidationReport(BaseModel):
    status: Literal["passed", "failed", "timeout", "unavailable", "cancelled"]
    go_version: str = GO_VERSION
    stages: list[StageReport] = Field(default_factory=list)
    elapsed_ms: float = 0
    container_removed: bool = False
    # Historical reports remain readable; the multi-agent gate requires all bindings.
    artifact_hash: ArtifactHash | None = None
    task_id: ContractId | None = None
    artifact_id: ContractId | None = None
    round: int | None = Field(default=None, ge=0, le=MAX_REPAIRS, strict=True)


class Attempt(BaseModel):
    number: int = Field(ge=0, le=MAX_REPAIRS)
    bundle: CodeBundle
    validation: ValidationReport
    change_summary: str = ""


class GeneratedCode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bundle: CodeBundle
    change_summary: str = Field(default="", max_length=2000)


class FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


class Requirement(FrozenContract):
    requirement_id: ContractId
    text: ContractText
    required: bool = Field(default=True, strict=True)


class AcceptanceCriterion(FrozenContract):
    criterion_id: ContractId
    requirement_id: ContractId
    text: ContractText


class TaskSpec(FrozenContract):
    task_id: ContractId
    scenario: Scenario
    original_requirement: ContractText
    requirements: tuple[Requirement, ...] = Field(min_length=1, max_length=128)
    acceptance_criteria: tuple[AcceptanceCriterion, ...] = Field(min_length=1, max_length=128)
    constraints: tuple[ContractText, ...] = Field(default=(), max_length=128)
    source_refs: tuple[ContractText, ...] = Field(default=(), max_length=20)

    @property
    def server_contract(self) -> str:
        return SCENARIO_SPECS[self.scenario]

    @model_validator(mode="after")
    def consistent_requirements(self):
        ids = [r.requirement_id for r in self.requirements]
        criteria = [c.criterion_id for c in self.acceptance_criteria]
        if len(ids) != len(set(ids)) or len(criteria) != len(set(criteria)):
            raise ValueError("需求或验收条件 ID 重复")
        linked = {c.requirement_id for c in self.acceptance_criteria}
        if not linked <= set(ids):
            raise ValueError("验收条件引用未知需求")
        required = {r.requirement_id for r in self.requirements if r.required}
        if not required or not required <= linked:
            raise ValueError("必须有必要需求且每条均有验收条件")
        return self


class ArtifactFile(SourceFile):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


def artifact_hash(files) -> str:
    """Hash the complete final bundle. Preserve exact UTF-8 content, including whitespace."""
    bundle = CodeBundle.model_validate({"files": [f.model_dump() if isinstance(f, BaseModel) else f for f in files]})
    payload = [{"name": f.name, "content": f.content} for f in sorted(bundle.files, key=lambda f: f.name)]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


class CodeArtifact(FrozenContract):
    task_id: ContractId
    artifact_id: ContractId
    scenario: Scenario
    round: int = Field(ge=0, le=MAX_REPAIRS, strict=True)
    files: tuple[ArtifactFile, ...] = Field(min_length=3, max_length=8)
    artifact_hash: ArtifactHash | None = None
    change_summary: str = Field(default="", max_length=2000, strict=True)
    addressed_issue_ids: tuple[ContractId, ...] = Field(default=(), max_length=128)

    @model_validator(mode="after")
    def final_snapshot(self):
        from app.go_validation.fixtures import ACCEPTANCE_FILE, ACCEPTANCE_TESTS
        actual = artifact_hash(self.files)  # Revalidate size, uniqueness and complete bundle.
        trusted = [f for f in self.files if f.name == ACCEPTANCE_FILE]
        if len(trusted) != 1 or trusted[0].content != ACCEPTANCE_TESTS[self.scenario]:
            raise ValueError("最终产物必须包含当前场景原样的服务端验收测试")
        if self.artifact_hash is not None and self.artifact_hash != actual:
            raise ValueError("产物 hash 与完整文件不匹配")
        if len(set(self.addressed_issue_ids)) != len(self.addressed_issue_ids):
            raise ValueError("修复问题 ID 重复")
        object.__setattr__(self, "artifact_hash", actual)
        return self

    def bundle(self) -> CodeBundle:
        # Return a copy; mutable runner inputs cannot change the frozen snapshot.
        return CodeBundle(files=[f.model_dump() for f in self.files])


def freeze_artifact(task: TaskSpec, bundle: CodeBundle, *, round: int,
                    artifact_id: str | None = None, change_summary: str = "",
                    addressed_issue_ids=()) -> CodeArtifact:
    """Server entry: inject trusted tests BEFORE computing the version."""
    from app.go_validation.fixtures import with_acceptance_tests
    task = TaskSpec.model_validate(task.model_dump())
    final = with_acceptance_tests(CodeBundle.model_validate(bundle.model_dump()), task.scenario)
    return CodeArtifact(task_id=task.task_id, artifact_id=artifact_id or uuid.uuid4().hex,
                        scenario=task.scenario, round=round, files=[f.model_dump() for f in final.files],
                        change_summary=change_summary, addressed_issue_ids=addressed_issue_ids)


def bind_validation(report: ValidationReport, artifact: CodeArtifact) -> ValidationReport:
    """Add task metadata to a validator report already bound to its actual input."""
    artifact = CodeArtifact.model_validate(artifact.model_dump())
    data = ValidationReport.model_validate(report.model_dump()).model_dump()
    if data["artifact_hash"] != artifact.artifact_hash:
        raise ValueError("验证器未绑定实际输入版本，或版本不匹配；不能重标历史报告")
    for key in ("artifact_hash", "task_id", "artifact_id", "round"):
        value = getattr(artifact, key)
        if data.get(key) is not None and data[key] != value:
            raise ValueError("拒绝将已有验证报告重新绑定到不同版本")
        data[key] = value
    return ValidationReport.model_validate(data)


class RequirementCheck(FrozenContract):
    requirement_id: ContractId
    status: Literal["pass", "fail", "unknown"]
    evidence: ContractText


class ReviewIssue(FrozenContract):
    issue_id: ContractId
    requirement_id: ContractId | None = None
    severity: Literal["blocking", "suggestion"]
    file: Annotated[str, StringConstraints(strict=True, max_length=64,
                                          pattern=r"^[A-Za-z][A-Za-z0-9_]*\.go$")] | None = None
    line: int | None = Field(default=None, ge=1, strict=True)
    evidence: ContractText
    repair_instruction: ContractText

    @model_validator(mode="after")
    def location(self):
        if self.line is not None and self.file is None:
            raise ValueError("行号必须关联源码文件")
        return self


class ReviewReport(FrozenContract):
    task_id: ContractId
    artifact_id: ContractId
    artifact_hash: ArtifactHash
    round: int = Field(ge=0, le=MAX_REPAIRS, strict=True)
    verdict: Literal["approve", "revise", "cannot_assess"]
    requirement_checks: tuple[RequirementCheck, ...] = Field(default=(), max_length=128)
    issues: tuple[ReviewIssue, ...] = Field(default=(), max_length=128)
    summary: Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=2000)]

    @model_validator(mode="after")
    def coherent_review(self):
        checks = [c.requirement_id for c in self.requirement_checks]
        issues = [i.issue_id for i in self.issues]
        if len(checks) != len(set(checks)) or len(issues) != len(set(issues)):
            raise ValueError("审查条目或问题 ID 重复")
        if self.verdict == "approve" and any(i.severity == "blocking" for i in self.issues):
            raise ValueError("approve 不能同时包含 blocking 问题")
        return self

    def check_context(self, task: TaskSpec, artifact: CodeArtifact):
        if artifact.task_id != task.task_id or artifact.scenario != task.scenario:
            raise ValueError("产物不属于当前任务或场景")
        if any(getattr(self, key) != getattr(artifact, key)
               for key in ("task_id", "artifact_id", "artifact_hash", "round")):
            raise ValueError("审查不属于当前代码版本")
        known = {r.requirement_id for r in task.requirements}
        if any(c.requirement_id not in known for c in self.requirement_checks):
            raise ValueError("审查引用未知需求")
        files = {f.name: f.content for f in artifact.files}
        for issue in self.issues:
            if issue.requirement_id is not None and issue.requirement_id not in known:
                raise ValueError("问题引用未知需求")
            if issue.file is not None:
                if issue.file not in files:
                    raise ValueError("问题引用不存在的文件")
                if issue.line is not None and issue.line > len(files[issue.file].splitlines()):
                    raise ValueError("问题行号超出源码")


class RemainingBudget(FrozenContract):
    # A server-produced snapshot, not a model-controlled budget authority.
    normal_calls: int = Field(default=7, ge=0, le=7, strict=True)
    retries: int = Field(default=1, ge=0, le=1, strict=True)
    model_calls: int = Field(default=8, ge=0, le=8, strict=True)
    validations: int = Field(default=3, ge=0, le=3, strict=True)
    seconds: float = Field(default=360, ge=0, strict=True, allow_inf_nan=False)

    @model_validator(mode="after")
    def shared_limit(self):
        if self.model_calls > self.normal_calls + self.retries:
            raise ValueError("总剩余调用不能大于正常与共享重试额度之和")
        return self


class RepairRequest(FrozenContract):
    task_spec: TaskSpec
    previous_artifact: CodeArtifact
    validation_report: ValidationReport
    review_report: ReviewReport
    remaining_budget: RemainingBudget
    round: int = Field(ge=1, le=MAX_REPAIRS, strict=True)

    @model_validator(mode="after")
    def linked_repair(self):
        artifact = self.previous_artifact
        self.review_report.check_context(self.task_spec, artifact)
        if any(getattr(self.validation_report, key) != getattr(artifact, key)
               for key in ("task_id", "artifact_id", "artifact_hash", "round")):
            raise ValueError("修复引用不匹配的验证报告")
        if self.round != artifact.round + 1:
            raise ValueError("修复轮次必须紧接上一产物")
        from app.agents.go_workflow import decide_after_review
        decision = decide_after_review(self.task_spec, artifact, self.validation_report,
                                       self.review_report, self.remaining_budget)
        if decision.action != "repair":
            raise ValueError("服务端判定不允许创建修复任务: " + decision.reason)
        return self


class AgentCall(FrozenContract):
    role: Literal["supervisor", "code"]
    stage: Literal["plan", "generate", "review", "repair"]
    model: ContractText
    status: Literal["running", "passed", "failed", "cancelled"]
    # Unknown provider usage remains None, never silently zero.
    token_usage: dict[Literal["input_tokens", "output_tokens", "total_tokens"],
                      Annotated[int, Field(ge=0, strict=True)]] | None = None


class GoTaskResult(BaseModel):
    run_id: str
    status: Literal["running", "cancelled", "passed", "failed", "timeout", "unavailable", "generation_error", "budget_exceeded"]
    scenario: Scenario
    attempts: list[Attempt] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    model_calls: int = 0
    validation_calls: int = 0
    elapsed_ms: float = 0
    error: str | None = None
    model_source: Literal["configured", "fixture"] = "configured"
    token_usage: dict[str, int] | None = Field(default_factory=dict)
    context_stats: dict = Field(default_factory=dict)
    budget: dict = Field(default_factory=dict)  # Server ledger snapshot; absent in historical reports.
    validation_scope: str = "仅验证当前代码、当前测试和固定 Go 工具链；不保证全部行为正确"
    workflow_version: Literal["single-v1", "multi-v1"] = "single-v1"
    task_spec: TaskSpec | None = None
    artifacts: list[CodeArtifact] = Field(default_factory=list)
    reviews: list[ReviewReport] = Field(default_factory=list)
    agent_calls: list[AgentCall] = Field(default_factory=list)
    stop_reason: StopReason | None = None
    final_summary: str = Field(default="", max_length=8000)

    @model_validator(mode="after")
    def multi_success_requires_evidence(self):
        if self.workflow_version != "multi-v1" or self.status != "passed":
            return self
        from app.agents.go_workflow import decide_after_review
        if not self.task_spec or not self.artifacts or not self.reviews or not self.attempts:
            raise ValueError("多 Agent passed 必须保存当前产物、验证和审查证据")
        artifact, attempt = self.artifacts[-1], self.attempts[-1]
        if (self.scenario != self.task_spec.scenario or attempt.number != artifact.round
                or artifact_hash(attempt.bundle.files) != artifact.artifact_hash):
            raise ValueError("最终尝试与产物版本不匹配")
        decision = decide_after_review(self.task_spec, artifact, attempt.validation,
                                       self.reviews[-1], RemainingBudget())
        if decision.status != "passed":
            raise ValueError("多 Agent passed 未通过服务端成功条件")
        return self
