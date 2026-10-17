"""Deterministic response scripts, shared by all arms. These are NOT quality labels."""
import asyncio
import json

from langchain_core.messages import AIMessage
from eval.go_fixtures import CORRECT, BEHAVIOR_ERROR, MODEL_TESTS


class FixtureState:
    def __init__(self,case,inject=None):
        self.case=case;self.generations=0;self.inject=inject
        self.entered=asyncio.Event()


class FixtureRole:
    model_name="s8-scripted-v1"
    def __init__(self,state,role):
        self.state,self.role=state,role

    async def ainvoke(self,messages):
        state=self.state;case=state.case;profile=case["fixture_profile"]
        if self.role!="supervisor":
            state.generations+=1
            if state.inject:
                state.entered.set()
                await asyncio.Event().wait()
            if profile=="provider_failure" and state.generations==1:
                raise RuntimeError("S8 controlled provider failure, counted and never refunded")
            bad=profile=="persistent_failure" or (state.generations==1 and profile in {"behavior_repair","weak_model_tests"})
            source=(BEHAVIOR_ERROR if bad else CORRECT)[case["scenario"]]
            if profile=="compile_repair" and state.generations==1:
                source+="\nvar broken = MissingS8CompileIdentifier\n"
            source+=f"\n// fixture version {state.generations}\n"
            if case.get("marker") and profile!="missing_supplement" and state.generations>1:
                target={"context_cancel":"WaitForCancel","worker_pool":"WorkerPool","channel":"SumChannel"}[case["scenario"]]
                source=source.replace("func "+target,"// "+case["marker"]+"\nfunc "+target)
            test=MODEL_TESTS[case["scenario"]]
            if profile=="weak_model_tests" and state.generations==1:
                test='package example\nimport "testing"\nfunc TestWeak(t *testing.T){if 1!=1{t.Fatal("never")}}\n'
            content="\n".join(f"=== FILE: {name} ===\n```go\n{value}\n```" for name,value in
                              (("solution.go",source),("solution_test.go",test)))+"\nCHANGE: scripted fixture round"
        elif "计划阶段" in messages[0].content:
            reqs=[dict(requirement_id="r-base",text=case["requirement"],required=True)]
            if case.get("marker"):reqs.append(dict(requirement_id="r-doc",text="附带指定文档注释",required=True))
            content=json.dumps(dict(requirements=reqs,acceptance_criteria=[
                dict(criterion_id="a-"+r["requirement_id"],requirement_id=r["requirement_id"],text=r["text"]) for r in reqs],
                constraints=["只用标准库，服从固定服务端接口"],source_refs=[]),ensure_ascii=False)
        else:
            missing=profile=="supplement" and state.generations==1
            checks=[dict(requirement_id="r-base",status="pass",evidence="fixture source inspected")]
            if case.get("marker"):checks.append(dict(requirement_id="r-doc",status="fail" if missing else "pass",evidence="fixture document check"))
            issues=[dict(issue_id="missing-doc",requirement_id="r-doc",severity="blocking",file="solution.go",line=1,
                evidence="所需函数文档注释缺失",repair_instruction="在函数声明前附带用户指定的合同注释")] if missing else []
            content=json.dumps(dict(verdict="revise" if missing else "approve",requirement_checks=checks,issues=issues,
                                    summary="fixed reviewer output, not an independent label"),ensure_ascii=False)
        # No fabricated provider token usage. Unknown stays unknown in reports.
        return AIMessage(content=content)
