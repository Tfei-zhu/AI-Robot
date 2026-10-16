"""第一版契约：固定工具链、单包源码、三个场景与最多两次修复。"""
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

GO_VERSION = "1.26.2"
MAX_REPAIRS = 2
MAX_SOURCE_BYTES = 65536
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


class Attempt(BaseModel):
    number: int = Field(ge=0, le=MAX_REPAIRS)
    bundle: CodeBundle
    validation: ValidationReport
    change_summary: str = ""


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
    token_usage: dict[str, int] = Field(default_factory=dict)
    context_stats: dict = Field(default_factory=dict)
    # 通过编译和当前测试不能等同于证明任意输入下都正确。
    validation_scope: str = "仅验证当前代码、当前测试和固定 Go 工具链；不保证全部行为正确"


class GeneratedCode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bundle: CodeBundle
    change_summary: str = Field(default="", max_length=2000)
