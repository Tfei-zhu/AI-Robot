"""S8 frozen four-arm evaluation. Fixtures still execute real Docker, never paid models.

Use freeze -> run fixtures/dev -> run fixtures/holdout -> report.
Live requires an explicit cumulative cap, pinned model, frozen rates and durable ledger.
"""
import argparse
import asyncio
import datetime
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault("PYTHON_DOTENV_DISABLED","1")

from eval.multi_agent_protocol import (ARMS, CostLedger, aggregate, digest, freeze, load_freeze,
                                      live_preflight, valid_usage, write_json)


def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()


def image_id():
    return subprocess.check_output(["docker","image","inspect","airobot-go-validator:1.26.2","--format","{{.Id}}"],text=True).strip()


class TrackingModel:
    """Only request boundary: reserve durably BEFORE invoking a client, including retries."""
    def __init__(self,model,role,state,folder,limits,*,cost_ledger=None,window=32768,input_limit=None,expected_revision=None):
        self.model,self.role,self.state,self.folder,self.limits=model,role,state,Path(folder),limits
        self.cost_ledger,self.window=cost_ledger,window
        self.input_limit,self.expected_revision=input_limit,expected_revision
        self.model_name=getattr(model,"model_name","s8-model")
        self.kwargs={"max_tokens":limits["supervisor_output"] if role=="supervisor" else limits["code_output"]}

    async def ainvoke(self,messages):
        if self.state.get("evaluation_stop"):
            raise RuntimeError("Evaluation already stopped; request not sent")
        if len(self.state["calls"])>=self.limits["max_calls"]:
            raise RuntimeError("Frozen per-trial total call cap exhausted; request not sent")
        if self.input_limit is not None:
            from app.context.token_counter import TokenCounter
            if TokenCounter().count(messages)>self.input_limit:
                raise RuntimeError("Frozen matched input estimate cap exhausted; request not sent")
        ticket=None
        if self.cost_ledger:
            try:ticket=self.cost_ledger.reserve(self.window,self.kwargs["max_tokens"],self.state["trial_id"])
            except RuntimeError:
                self.state["evaluation_stop"]="cost_budget_exhausted"
                raise
        row=dict(role=self.role,index=len(self.state["calls"])+1,started_utc=utc(),status="running",usage=None,
                 messages=[dict(type=getattr(m,"type","unknown"),content=getattr(m,"content",str(m))) for m in messages],
                 cost_ticket=ticket)
        self.state["calls"].append(row)
        path=self.folder/f"call-{row['index']:02d}.json"
        write_json(path,row,exclusive=True)
        started=time.perf_counter();response=None
        try:
            timeout=min(self.limits["call_seconds"],60) if self.role=="supervisor" and self.limits["supervisor_output"]==4096 else self.limits["call_seconds"]
            response=await asyncio.wait_for(self.model.ainvoke(messages),timeout)
            row.update(status="returned",usage=valid_usage(response),output=getattr(response,"content",str(response)))
            metadata=getattr(response,"response_metadata",{}) or {}
            row["provider_metadata"]={k:metadata[k] for k in ("model_name","system_fingerprint","finish_reason") if k in metadata}
            row["provider_response_id"]=getattr(response,"id",None)
            if self.expected_revision and metadata.get("model_name")!=self.expected_revision:
                self.state["evaluation_stop"]="model_version_unverified"
                row["version_error"]="Provider model version missing/different from frozen requested revision"
            return response
        except BaseException as exc:
            row.update(status="cancelled" if isinstance(exc,asyncio.CancelledError) else "failed",error=type(exc).__name__+": "+str(exc)[:500])
            raise
        finally:
            row["elapsed_ms"]=round((time.perf_counter()-started)*1000,2)
            if self.cost_ledger:self.cost_ledger.finish(ticket,row["usage"])
            write_json(path,row)


def build_config(arm,frozen):
    from app.config import GoMultiAgentSettings
    spec=ARMS[arm];p=frozen["protocol"]
    window=p["live_model"]["context_window"] or p["fixture_window"]
    return GoMultiAgentSettings(enabled=spec["multi"],supervisor_window=window,code_window=window,
        max_normal_calls=spec["normal"],max_retries=spec["retries"],max_model_calls=spec["max_calls"],
        supervisor_output_tokens=spec["supervisor_output"],code_output_tokens=spec["code_output"],
        supervisor_input_tokens=p["input_tokens"],code_input_tokens=p["input_tokens"],
        task_timeout=p["task_seconds"],code_timeout=spec["call_seconds"],supervisor_timeout=min(60,spec["call_seconds"]),
        validation_timeout=p["validation_seconds"],cleanup_timeout=p["cleanup_seconds"])


async def run_trial(case,arm,frozen,folder,*,mode="fixtures",repeat=1,cost_ledger=None,inject=None,rerun_of=None,reason=None):
    from app.config import settings
    from app.go_validation.contracts import CodeBundle,GoTaskRequest,artifact_hash
    from app.go_validation.runner import DockerGoRunner
    from app.go_validation.service import GoTaskService
    from app.go_validation.store import GoTaskStore
    from eval.multi_agent_fixtures import FixtureRole,FixtureState
    from eval.multi_agent_scoring import score,label
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    spec=ARMS[arm];trial_id=folder.name
    state=dict(trial_id=trial_id,case_id=case["id"],split=case["split"],arm=arm,repeat=repeat,
        freeze_hash=frozen["freeze_hash"],started_utc=utc(),state="started",calls=[],mode=mode,
        rerun_of=rerun_of,rerun_reason=reason,controlled_interruption=inject)
    write_json(folder/"trial.json",state,exclusive=True)
    store=GoTaskStore(str(folder/"reports.sqlite3"));principal="s8/"+trial_id
    fixture=FixtureState(case,inject)
    cfg=build_config(arm,frozen)
    def role(name):
        if mode=="fixtures":client=FixtureRole(fixture,name)
        else:
            from app.agents.graph import get_llm
            client=get_llm(max_retries=0,model=frozen["protocol"]["live_model"]["name"]).bind(
                max_tokens=spec["supervisor_output"] if name=="supervisor" else spec["code_output"])
        return TrackingModel(client,name,state,folder,spec,cost_ledger=cost_ledger,window=cfg.code_window,
            input_limit=frozen["protocol"]["input_tokens"] if arm.endswith("equal3") else None,
            expected_revision=frozen["protocol"]["live_model"]["revision"] if mode=="live" else None)
    async def retrieve(_):return {"chunks":[],"sources":[],"warning":"same frozen empty retrieval for every arm"}
    service=GoTaskService(store,runner=DockerGoRunner(),retrieve=retrieve,
        timeout=0.15 if inject=="timeout" else frozen["protocol"]["task_seconds"],
        **({"supervisor_model":role("supervisor"),"code_model":role("code")} if spec["multi"] else {"model":role("single")}))
    previous=settings.go_multi_agent
    settings.go_multi_agent=cfg
    request=GoTaskRequest(scenario=case["scenario"],requirement=case["requirement"])
    started=time.perf_counter();result=None;run_id=None;fatal=None
    async def consume():
        nonlocal result,run_id
        async for event in service.stream(request,principal,trial_id):
            run_id=event["run_id"]
            with (folder/"events.jsonl").open("a") as log:
                log.write(json.dumps(event,ensure_ascii=False)+"\n");log.flush()
            if event["type"]=="go_done":result=event["result"]
    try:
        job=asyncio.create_task(consume())
        if inject=="cancel":
            await asyncio.wait_for(fixture.entered.wait(),3);job.cancel()
        try:await job
        except BaseException as exc:
            fatal=exc
            state["exception"]=type(exc).__name__+": "+str(exc)[:500]
            if run_id:result=store.get(run_id,hashlib.sha256(principal.encode()).hexdigest())
    finally:
        settings.go_multi_agent=previous
        store.close()
    state["generation_ms"]=round((time.perf_counter()-started)*1000,2)
    if result is not None:write_json(folder/"result.json",result,exclusive=True)
    attempts=result.get("attempts",[]) if result else []
    final=CodeBundle.model_validate(attempts[-1]["bundle"]) if attempts else None
    refusal=bool(result and result["status"]=="failed" and result.get("stop_reason")=="clarification_needed")
    scoring=time.perf_counter()
    if fatal and not inject:
        independent=label(case,None)
    else:
        try:independent=await score(case,final,refusal=refusal)
        except Exception as exc:
            independent=label(case,None);independent["exception"]=type(exc).__name__+": "+str(exc)[:500]
    initial=independent
    if attempts and artifact_hash(CodeBundle.model_validate(attempts[0]["bundle"]).files)!=artifact_hash(final.files) and not fatal:
        try:initial=await score(case,CodeBundle.model_validate(attempts[0]["bundle"]))
        except Exception as exc:
            initial=label(case,None);initial["exception"]=type(exc).__name__+": "+str(exc)[:500]
    state.update(state="interrupted" if fatal else "completed",ended_utc=utc(),
        business_status=result["status"] if result else "interrupted",stop_reason=result.get("stop_reason") or result["status"] if result else "interrupted",
        independent=independent,initial_independent=initial,scoring_ms=round((time.perf_counter()-scoring)*1000,2),
        reported_model_calls=result.get("model_calls") if result else None,actual_client_calls=len(state["calls"]),
        validation_calls=result.get("validation_calls") if result else None,feasible=case["feasible"],
        cost_estimate=0 if mode=="fixtures" else None,
        cost_note="nonbillable fixed responses; unknown tokens remain unknown" if mode=="fixtures" else "frozen token ceiling estimate, not invoice; missing usage remains unknown")
    if mode=="live" and state["calls"] and all(c["usage"] is not None for c in state["calls"]):
        rates=frozen["protocol"]["live_rates"]
        state["cost_estimate"]=sum((c["usage"]["input_tokens"]*float(rates["input_ceiling_per_million"])+
                                 c["usage"]["output_tokens"]*float(rates["output_ceiling_per_million"]))/1e6 for c in state["calls"])
    write_json(folder/"independent.json",dict(final=independent,initial=initial),exclusive=True)
    write_json(folder/"trial.json",state)
    if len(state["calls"])>spec["max_calls"]:raise RuntimeError("Actual client calls exceeded frozen cap")
    if fatal and not inject:raise fatal
    return state


def report(output,frozen,mode,split,rows,expected):
    data=dict(freeze_hash=frozen["freeze_hash"],mode=mode,split=split,generated_utc=utc(),expected_runs=expected,
        recorded_runs=len(rows),complete=len(rows)==expected and not any(r.get("evaluation_stop") or r.get("state")=="started" for r in rows),metrics=aggregate(rows),
        protocol_violations=[dict(trial_id=r["trial_id"],reason=r["evaluation_stop"]) for r in rows if r.get("evaluation_stop")],
        currency=None if mode=="fixtures" else frozen["protocol"]["live_rates"]["currency"],
        not_run=max(0,expected-len(rows)),pending_trial_ids=[r["trial_id"] for r in rows if r.get("state")=="started"],
        inference="No model-quality improvement conclusion from scripted responses. Native resources differ; equal3 only equalizes ceilings.",
        failed_or_interrupted_trials=[r["trial_id"] for r in rows if r["business_status"]!="passed" or r["independent"]["correct"] is not True],
        trials=[dict(trial_id=r["trial_id"],case_id=r["case_id"],arm=r["arm"],repeat=r["repeat"],business_status=r["business_status"],independently_correct=r["independent"]["correct"]) for r in rows])
    write_json(Path(output)/"report.json",data)
    return data


def audit_rows(output,frozen):
    rows=[];cases={c["id"]:c for c in frozen["cases"]}
    for path in sorted(Path(output).glob("*/trial.json")):
        row=json.loads(path.read_text())
        if "independent" not in row:
            from eval.multi_agent_scoring import label
            calls=[json.loads(c.read_text()) for c in sorted(path.parent.glob("call-*.json"))]
            row.update(business_status="interrupted",stop_reason="process_interrupted_or_setup_failed",
                independent=label(cases[row["case_id"]],None),initial_independent={},calls=calls,
                generation_ms=None,scoring_ms=None,cost_estimate=None,actual_calls_complete=False,
                feasible=cases[row["case_id"]]["feasible"])
        rows.append(row)
    return rows


async def evaluate(args,frozen):
    if bool(args.rerun_of)!=bool(args.reason):raise ValueError("Rerun needs both prior run identity and reason")
    if args.mode=="live" and getattr(args,"inject",None):raise ValueError("Controlled interruption is offline development only")
    # Authorization/pricing checks precede holdout markers and any model/client construction.
    cost=None
    if args.mode=="live":
        problems=live_preflight(frozen,args.cost_cap,frozen["protocol"].get("live_rates"),args.cost_ledger)
        if problems:raise ValueError("; ".join(problems))
        from app.config import settings
        if not settings.llm_api_key:raise ValueError("Live credentials must be explicitly supplied in environment; .env loading is disabled")
        if settings.llm_base_url!=frozen["protocol"]["live_model"]["endpoint"]:raise ValueError("Live endpoint differs from freeze")
        rates=frozen["protocol"]["live_rates"]
        cost=CostLedger(args.cost_ledger,args.cost_cap,rates["currency"],rates,frozen["protocol"]["live_model"])
    if args.split=="holdout":
        if args.limit or args.inject:raise ValueError("Holdout cannot be limited or used for interruption debugging")
        if not args.dev_report:raise ValueError("Full development evidence required before holdout")
        dev=json.loads(Path(args.dev_report).read_text())
        if not dev["complete"] or dev["split"]!="dev" or dev["mode"]!=args.mode or dev["freeze_hash"]!=frozen["freeze_hash"]:
            raise ValueError("Development report does not bind to this frozen full protocol")
        marker=Path(args.freeze)/("holdout-started-"+args.mode+".json")
        if marker.exists() and not (args.rerun_of and args.reason):raise ValueError("Holdout already started: retain prior run and supply rerun lineage/reason")
        if not marker.exists():write_json(marker,dict(started_utc=utc(),output=args.output),exclusive=True)
    if image_id()!=frozen["docker_image_id"]:raise ValueError("Docker image changed after protocol freeze")
    output=Path(args.output);output.mkdir(parents=True,exist_ok=False)
    cases=[c for c in frozen["cases"] if c["split"]==args.split]
    random.Random(frozen["protocol"]["seed"]).shuffle(cases)
    if args.limit:cases=cases[:args.limit]
    repeats=frozen["protocol"]["fixture_repeats" if args.mode=="fixtures" else "live_repeats"]
    rows=[];expected=len(cases)*len(ARMS)*repeats
    try:
        for repeat in range(1,repeats+1):
            for case in cases:
                arms=list(ARMS);offset=int(digest(case["id"])[:8],16)%len(arms)
                arms=arms[offset:]+arms[:offset]
                for arm in arms:
                    folder=output/(case["id"]+"-"+arm+f"-r{repeat}-"+uuid.uuid4().hex[:8])
                    row=await run_trial(case,arm,frozen,folder,mode=args.mode,repeat=repeat,cost_ledger=cost,
                        inject=args.inject,rerun_of=args.rerun_of,reason=args.reason)
                    rows.append(row)
                    print(json.dumps(dict(completed=len(rows),expected=expected,case=case["id"],arm=arm,
                        business=row["business_status"],independent=row["independent"]["correct"],calls=len(row["calls"])),ensure_ascii=False),flush=True)
                    report(output,frozen,args.mode,args.split,rows,expected)
                    if row.get("evaluation_stop"):
                        return 0  # No more requests; remaining trials explicitly not run in report.
    finally:
        # Preserve an interrupted trial too, including after external cancellation.
        rows=audit_rows(output,frozen)
        final=report(output,frozen,args.mode,args.split,rows,expected)
        final["full_split"]=not args.limit and not args.inject
        if not final["full_split"]:final["complete"]=False
        write_json(output/"report.json",final)
    return 0


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    frozen=sub.add_parser("freeze");frozen.add_argument("--output",required=True)
    frozen.add_argument("--model-config");frozen.add_argument("--rates");frozen.add_argument("--cost-cap")
    frozen.add_argument("--cases");frozen.add_argument("--protocol")
    prepared=sub.add_parser("prepare-live");prepared.add_argument("--freeze",required=True);prepared.add_argument("--output",required=True)
    prepared.add_argument("--cost-cap");prepared.add_argument("--cost-ledger")
    run=sub.add_parser("run");run.add_argument("--freeze",required=True);run.add_argument("--output",required=True)
    run.add_argument("--mode",choices=["fixtures","live"],required=True);run.add_argument("--split",choices=["dev","holdout"],required=True)
    run.add_argument("--dev-report");run.add_argument("--limit",type=int,default=0);run.add_argument("--inject",choices=["cancel","timeout"])
    run.add_argument("--cost-cap");run.add_argument("--cost-ledger");run.add_argument("--rerun-of");run.add_argument("--reason")
    args=parser.parse_args()
    if args.command=="freeze":
        model=json.loads(Path(args.model_config).read_text()) if args.model_config else None
        rates=json.loads(Path(args.rates).read_text()) if args.rates else None
        result=freeze(args.output,image_id(),model=model,rates=rates,cost_cap=args.cost_cap,
                      cases_path=args.cases,protocol_path=args.protocol)
        print(json.dumps(dict(freeze_hash=result["freeze_hash"],cases=30,dev=18,holdout=12)))
        return 0
    result=load_freeze(args.freeze)
    if args.command=="prepare-live":
        problems=live_preflight(result,args.cost_cap,result["protocol"].get("live_rates"),args.cost_ledger)
        write_json(args.output,dict(status="blocked" if problems else "ready_for_explicit_live_execution",
            frozen_hash=result["freeze_hash"],problems=problems,calls_sent=0,model=result["protocol"]["live_model"],
            worst_full_four_arm_calls=30*3*sum(a["max_calls"] for a in ARMS.values()),
            required_inputs=["明确累计费用上限及币种","固定模型版本/上下文窗口与端点","已核实的冻结单价上界","持久化费用账本","开发集证据和正式留出前固定费用目标"]),exclusive=True)
        print(json.dumps(dict(status="blocked" if problems else "ready",problems=problems,calls_sent=0),ensure_ascii=False));return 0
    if args.limit<0:raise ValueError("Limit cannot be negative")
    return asyncio.run(evaluate(args,result))


if __name__=="__main__":
    try:raise SystemExit(main())
    except (ValueError,AssertionError,RuntimeError) as exc:
        print(type(exc).__name__+": "+str(exc),file=sys.stderr);raise SystemExit(2)
