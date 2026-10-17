"""Actual fixed Docker validation + substituted review, not an LLM evaluation."""
import asyncio
import json
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from multi_agent_fixtures import bundle, budget, review, task
from app.agents.go_workflow import decide_after_review
from app.go_validation.contracts import bind_validation, freeze_artifact
from app.go_validation.runner import DockerGoRunner


async def main():
    rows = []
    for mode in ("correct", "wrong_early_return"):
        source = bundle()
        if mode != "correct":
            source.files[0].content = source.files[0].content.replace("<-ctx.Done(); return ctx.Err()", "return nil")
        art = freeze_artifact(task(), source, round=0, artifact_id=mode)
        machine = bind_validation(await DockerGoRunner().validate(art.bundle()), art)
        audited = review(art)  # Intentionally approves both: machine failure must win.
        decision = decide_after_review(task(), art, machine, audited, budget())
        assert machine.artifact_hash == audited.artifact_hash == art.artifact_hash
        assert machine.container_removed
        if mode == "correct":
            assert machine.status == "passed", machine.model_dump()
            assert decision.status == "passed"
        else:
            assert machine.status == "failed", machine.model_dump()
            assert decision.action == "repair" and decision.status == "running"
            assert "TestServer" in machine.stages[-1].output
        rows.append(dict(case=mode, artifact=art.model_dump(), validation=machine.model_dump(),
                         review=audited.model_dump(), decision=decision.model_dump()))
        print(mode, "machine:", machine.status, "review fixture:", audited.verdict,
              "server:", decision.status, decision.reason)
    (BASE / "real-gate-report.json").write_text(json.dumps({
        "verification": "actual Docker Go 1.26.2", "review_source": "fixture, no LLM request",
        "scope": "S1 gate integration, not a multi-agent runtime or quality evaluation", "results": rows,
    }, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
