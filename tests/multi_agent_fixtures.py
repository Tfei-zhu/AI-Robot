"""S1 contract fixtures. Validation reports here are substitutes, never real Docker evidence."""
from app.go_validation.contracts import (
    CodeBundle, RemainingBudget, ReviewReport, StageReport, TaskSpec, ValidationReport,
    bind_validation, freeze_artifact,
)


def task():
    return TaskSpec(task_id="task-1", scenario="context_cancel", original_requirement="等待取消并传播错误，不能提前返回",
                    requirements=[{"requirement_id": "r-cancel", "text": "传播取消错误"},
                                  {"requirement_id": "r-wait", "text": "取消前不能返回"}],
                    acceptance_criteria=[{"criterion_id": "a-cancel", "requirement_id": "r-cancel", "text": "取消后返回 ctx.Err()"},
                                         {"criterion_id": "a-wait", "requirement_id": "r-wait", "text": "取消前保持等待"}])


def bundle():
    return CodeBundle(files=[
        {"name": "solution.go", "content": 'package example\nimport "context"\nfunc WaitForCancel(ctx context.Context) error { <-ctx.Done(); return ctx.Err() }\n'},
        {"name": "solution_test.go", "content": 'package example\nimport ("context"; "errors"; "testing")\nfunc TestCancel(t *testing.T) { ctx,cancel:=context.WithCancel(context.Background());cancel();if !errors.Is(WaitForCancel(ctx),context.Canceled){t.Fatal("cancel")} }\n'},
    ])


def artifact(round=0, **freeze_kwargs):
    return freeze_artifact(task(), bundle(), round=round,
                           artifact_id="artifact-" + str(round), **freeze_kwargs)


def validation(art, status="passed"):
    return bind_validation(ValidationReport(status=status, container_removed=True, artifact_hash=art.artifact_hash,
                           stages=[StageReport(stage=name, exit_code=1 if status == "failed" and name == "test" else 0,
                                               output="fixture execution evidence")
                                   for name in ("policy", "compile", "vet", "test")]), art)


def review(art, **changes):
    data = dict(task_id=art.task_id, artifact_id=art.artifact_id, artifact_hash=art.artifact_hash, round=art.round,
                verdict="approve", requirement_checks=[{"requirement_id": req.requirement_id, "status": "pass",
                                                       "evidence": "fixture source evidence: solution.go:3"}
                                                      for req in task().requirements], summary="fixture review")
    data.update(changes)
    return ReviewReport.model_validate(data)


def budget(**changes):
    return RemainingBudget(**changes)


def issue(**changes):
    data = dict(issue_id="i-1", requirement_id="r-cancel", severity="blocking", file="solution.go", line=3,
                evidence="取消错误未返回", repair_instruction="返回 ctx.Err() 并补断言")
    data.update(changes)
    return data
