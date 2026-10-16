"""真实模型长对话评测；每组独立生成全部回答，固定工具数据用于复现。"""
import argparse
import asyncio
import hashlib
import json
import sys
import time
import uuid
import math
import statistics
import re
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from app.agents import graph
from app.config import settings
from app.services import chat as chat_module
from app.services.memory import memory
from app.context import usage
from langchain_core.tools import tool


@tool("search_knowledge")
async def fixed_search(query: str) -> str:
    """检索固定测试知识，返回完整证据及来源。"""
    if any(word in query.lower() for word in ("context","deadline","取消","超时")):
        text="context 支持取消与超时。"*120+"重要结论：示例超时为 250ms。";source="context-fixture#0"
    else:
        text="Go 工程规范：命名应简短清晰；日志使用标准库 slog 记录结构化字段；测试使用 testing 编写表驱动用例。";source="engineering-fixture#0"
    return json.dumps({"chunks":[{"text":text,"source":source}],"sources":[source]},ensure_ascii=False)


class EvaluationModel:
    """保持所有实验组工具绑定后的输出额度一致。"""
    def __init__(self,base):self.base=base
    @property
    def kwargs(self):return getattr(self.base,"kwargs",{})
    def bind(self,**kwargs):return EvaluationModel(self.base.bind(**kwargs))
    def bind_tools(self,tools):return EvaluationModel(self.base.bind_tools(tools).bind(max_tokens=self.kwargs.get("max_tokens",384)))
    async def ainvoke(self,messages):return await self.base.ainvoke(messages)
    def astream(self,messages):return self.base.astream(messages)


def parse_answer(text):
    try:
        return json.loads(text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip())
    except (ValueError,TypeError):
        return {}


def matches(key,value,expected):
    # 字段未限定枚举语言，明确的中英文同义表达按同一语义验收。
    text=str(value).strip()
    if key=="language":return text.lower() in {"go","golang"}
    if key=="dependency":return text.lower().replace(" ","") in {
        "标准库","仅标准库","仅使用标准库","仅依赖标准库","go标准库","无第三方依赖",
        "standardlibrary","standardlibraryonly","onlystandardlibrary","stdlib","stdlibonly","onlystdlib"}
    if key=="version":return text.lower().removeprefix("go").strip().removeprefix("v")==str(expected)
    return text==str(expected)


def provider_blocker(exc):
    # 仅记录服务商错误码和HTTP状态，不复制密钥、请求正文或完整响应。
    body=getattr(exc,"body",None)
    error=body.get("error",body) if isinstance(body,dict) else {}
    code=error.get("code") or error.get("type") if isinstance(error,dict) else None
    status=getattr(exc,"status_code",None)
    if status is None:status=getattr(getattr(exc,"response",None),"status_code",None)
    if status in (401,403) or str(code).lower() in {"arrearage","invalidapikey","invalid_api_key","insufficient_quota","accessdenied"}:
        return {"code":str(code or "authentication_or_permission_error"),"http_status":status}
    return None


def ordinary_checks_for(case,turns):
    limit=case.get("ordinary_constraint",{}).get("max_characters",30)
    indices=case.get("ordinary_turns")
    if indices is None:
        indices=[i+1 for i,q in enumerate(case["turns"]) if "回复不超过 30 字" in q or "回复不超过 30 个字符" in q]
    # 评分使用数据集明确标注的轮次，不依赖生产端的要求解析器；空答复也不算通过。
    return [bool(t["reply"].strip()) and len(t["reply"].strip())<=limit for t in turns if t["turn"] in indices]


async def evaluate(args):
    if not args.live:
        raise RuntimeError("质量评测必须显式 --live；离线机制测试使用 pytest，不能替代任务完成率")
    if not settings.llm_api_key:
        raise RuntimeError("真实模型密钥未配置，未运行真实评测")
    dataset_path=Path(getattr(args,"dataset",None) or "eval/context_cases.jsonl")
    if not dataset_path.is_absolute():dataset_path=ROOT/dataset_path
    dataset=dataset_path.read_bytes()
    cases=[json.loads(s) for s in dataset.decode("utf-8").splitlines() if s.strip()]
    source_files=["app/agents/graph.py","app/agents/tools.py","app/services/chat.py","app/services/memory.py","app/config.py","eval/run_context_eval.py"]
    source_files += sorted(str(p.relative_to(ROOT)).replace("\\","/") for p in (ROOT/"app/context").glob("*.py"))
    source_sha={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in source_files if (ROOT/p).exists()}
    cases=[c for c in cases if args.split=="all" or c["split"]==args.split]
    if args.case:
        requested=set(args.case.split(","));available={c["id"] for c in cases}
        if not requested<=available:raise RuntimeError("指定任务未在当前split中找到，请核对--split和--case："+",".join(sorted(requested-available)))
        cases=[c for c in cases if c["id"] in requested]
    cases=cases[:args.limit] if args.limit else cases
    if not cases:raise RuntimeError("没有匹配到评测任务，未发起模型请求")
    rows=[];calls=total_tokens=0;stop_reason=None
    started=time.perf_counter();factory=graph.get_llm;experiment_id=uuid.uuid4().hex
    def model():
        # 所有实验组同一模型、输出额度与重试策略。
        return EvaluationModel(factory(max_retries=0).bind(max_tokens=384))
    modes={"A":"off","B":"enforce","C":"enforce","D":"enforce"}
    target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True)
    guard=usage.EvaluationBudget(args.max_calls,args.max_tokens,args.max_cost)
    budget_token=usage.evaluation_budget.set(guard)
    with ExitStack() as stack:
        stack.enter_context(patch.object(settings,"cache_enabled",False))
        stack.enter_context(patch.object(settings,"context_output_tokens",384))
        if args.history_tokens is not None:stack.enter_context(patch.object(settings,"context_history_tokens",args.history_tokens))
        if args.summary_target is not None:stack.enter_context(patch.object(settings,"context_summary_target_ratio",args.summary_target))
        stack.enter_context(patch.object(graph,"get_llm",model))
        stack.enter_context(patch.dict(graph._tools_by_name,{"search_knowledge":fixed_search}))
        if hasattr(settings,"context_mode"):
            stack.enter_context(patch.object(settings,"context_mode",modes[args.group]))
            stack.enter_context(patch.object(settings,"context_history_enabled",args.group in ("C","D")))
            stack.enter_context(patch.object(settings,"context_summary_enabled",args.group=="D"))
        semaphore=asyncio.Semaphore(args.workers)
        async def run_case(case,repeat):
            nonlocal calls,total_tokens,stop_reason
            async with semaphore:
                if stop_reason:return
                session=hashlib.sha256(b"context-eval").hexdigest()+":"+case["id"]+f"-{args.group}-{repeat}-{experiment_id}"
                memory.clear(session);turns=[];aborted=False
                for index,question in enumerate(case["turns"]):
                    if stop_reason:aborted=True;break
                    if calls>=args.max_calls or total_tokens>=args.max_tokens:
                        stop_reason="评测达到调用或 Token 上限";aborted=True;break
                    begin=time.perf_counter()
                    try:result=await chat_module.chat(question,session)
                    except Exception as exc:
                        from app.services.tracing import traces
                        trace=next((t for t in traces.recent(10) if t.get("session_id")==session),{})
                        result={"reply":"","steps":[],"context_stats":trace.get("context_usage",{}),"error_type":type(exc).__name__}
                        blocked=provider_blocker(exc)
                        if blocked:
                            result["provider_error"]=blocked
                            stop_reason=f"服务商账户或配置不可用: {blocked['code']}"
                        # 预算耗尽停止整个实验；单个任务失败仍纳入样本，其余任务继续测量。
                        if isinstance(exc,usage.EvaluationLimitExceeded):stop_reason=f"评测预算停止: {type(exc).__name__}"
                        aborted=True
                    measured=result.get("context_stats") or {}
                    records=measured.get("calls",[])
                    calls+=len(records)
                    total_tokens+=measured.get("known_token_usage",{}).get("total_tokens",0)
                    turns.append({"turn":index+1,"reply":result["reply"],"elapsed_ms":round((time.perf_counter()-begin)*1000,2),
                                  "context_stats":measured,"steps":result.get("steps",[]),"error_type":result.get("error_type"),
                                  "provider_error":result.get("provider_error")})
                    print(f'{args.group} {case["id"]} {repeat+1} {index+1}/{case["length"]}',flush=True)
                    if aborted:break
                answer=parse_answer(turns[-1]["reply"]) if turns and not aborted else {}
                constraints={k:matches(k,answer.get(k,""),v) for k,v in case["expected"].items()}
                # 尾部证据必须在用户请求的当轮答复中实际使用，不能只检查投影文本。
                evidence_checks=[bool(re.search(r"250\s*(?:ms|毫秒)",t["reply"],re.I))
                    for t,q in zip(turns,case["turns"]) if "确认资料中的超时数值" in q]
                ordinary_checks=ordinary_checks_for(case,turns)
                rows.append({"id":case["id"],"kind":case["kind"],"length":case["length"],"split":case["split"],"repeat":repeat,"completed":not aborted,
                             "task_pass":not aborted and all(constraints.values()) and all(evidence_checks),
                             "constraints":constraints,"evidence_checks":evidence_checks,"ordinary_checks":ordinary_checks,"turns":turns})
                # 每条任务落盘，长矩阵中断后仍保留已执行样本和真实费用记录。
                target.write_text(json.dumps({"status":"running","group":args.group,"source_sha256":source_sha,
                    "model_calls":calls,"known_total_tokens":total_tokens,"results":rows},ensure_ascii=False,indent=2),encoding="utf-8")
        await asyncio.gather(*(run_case(case,repeat) for case in cases for repeat in range(args.repeats)))
        rows.sort(key=lambda r:(r["id"],r["repeat"]))
    executed=[r for r in rows if r["turns"]]
    usage.evaluation_budget.reset(budget_token)
    stats=[t["context_stats"] for r in rows for t in r["turns"]]
    latencies=sorted(t["elapsed_ms"] for r in rows for t in r["turns"])
    costs=[s.get("cost_estimate") for s in stats]
    uncached_costs=[s.get("uncached_cost_estimate") for s in stats]
    all_calls=[c for s in stats for c in s.get("calls",[])]
    evidence_checks=[check for r in rows for check in r["evidence_checks"]]
    ordinary_checks=[check for r in rows for check in r["ordinary_checks"]]
    duplicate_requests=0
    for row in rows:
        seen=set()
        for turn in row["turns"]:
            for step in turn.get("steps",[]):
                if step.get("type")=="tool_call" and step.get("tool")=="search_knowledge":
                    key=json.dumps(step.get("args",{}),ensure_ascii=False,sort_keys=True)
                    if key in seen:duplicate_requests+=1
                    seen.add(key)
    report={"model_source":"configured","model":settings.llm_model,"group":args.group,
            "grading_version":"semantic-aliases-v4-annotated-character-turns",
            "dataset_version":cases[0].get("dataset_version",1) if cases else None,
            "history_tokens":args.history_tokens or settings.context_history_tokens,
            "summary_target_ratio":args.summary_target if args.summary_target is not None else settings.context_summary_target_ratio,
            "parameters":{"temperature":0.2,"max_output_tokens":384,"summary_temperature":0,"repeats":args.repeats,"workers":args.workers,"seed":None},
            "dataset_sha256":hashlib.sha256(dataset).hexdigest(),"source_sha256":source_sha,
            "scope":"真实模型独立生成长对话；固定工具语料v2按主题返回证据；终局结构化约束回忆任务，不代表任意工程任务完成率",
            "stop_reason":stop_reason,"model_calls":calls,"known_total_tokens":total_tokens,
            "evaluation_budget":{"requests":guard.requests,"tokens_charged_for_limit":guard.tokens,
                "cost_charged_for_limit":guard.cost,"unknown_calls":guard.unknown_calls,
                "unknown_token_upper_reserve":guard.unknown_token_reserve,"unknown_cost_upper_reserve":guard.unknown_cost_reserve},
            "task_errors":[{"id":r["id"],"repeat":r["repeat"],"turn":r["turns"][-1]["turn"],
                            "error_type":r["turns"][-1]["error_type"],"provider_error":r["turns"][-1].get("provider_error")} for r in rows if not r["completed"] and r["turns"]],
            "scheduled_tasks":len(cases)*args.repeats,"started_tasks":len(executed),"finished_tasks":sum(r["completed"] for r in rows),
            "task_completion_rate":sum(r["task_pass"] for r in executed)/len(executed) if executed else None,
            "constraint_retention_rate":sum(sum(r["constraints"].values()) for r in executed)/(len(executed)*4) if executed else None,
            "evidence_retention_rate":sum(evidence_checks)/len(evidence_checks) if evidence_checks else None,
            "ordinary_constraint_retention_rate":sum(ordinary_checks)/len(ordinary_checks) if ordinary_checks else None,
            "input_tokens":sum(c["usage"]["input_tokens"] for c in all_calls if c.get("usage")),
            "output_tokens":sum(c["usage"]["output_tokens"] for c in all_calls if c.get("usage")),
            "unknown_usage_calls":sum(c.get("usage") is None for c in all_calls),
            "retrieval_requested":sum(s.get("retrieval_requested",0) for s in stats),
            "retrieval_executed":sum(s.get("retrieval_executed",0) for s in stats),
            "retrieval_reused":sum(s.get("retrieval_reused",0) for s in stats),
            "duplicate_retrieval_requests":duplicate_requests,
            "summary_calls":sum(c["stage"]=="summary" for c in all_calls),
            "counter_underestimates":sum(c.get("input_estimate",0)<c["usage"]["input_tokens"] for c in all_calls if c.get("usage") and c["stage"]!="embedding"),
            "turn_p50_ms":statistics.median(latencies) if latencies else None,
            "turn_p95_ms":latencies[max(0,math.ceil(.95*len(latencies))-1)] if latencies else None,
            "elapsed_ms":round((time.perf_counter()-started)*1000,2),
            "cost_estimate":sum(costs) if costs and all(c is not None for c in costs) else None,
            "uncached_cost_estimate":sum(uncached_costs) if uncached_costs and all(c is not None for c in uncached_costs) else None,
            "currency":stats[0].get("currency") if stats else None,"results":rows}
    target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("报告：",target.resolve())
    return 2 if stop_reason or any(not r["completed"] for r in rows) else 0


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live",action="store_true");p.add_argument("--group",choices=list("ABCD"),default="A")
    p.add_argument("--dataset",default="eval/context_cases.jsonl",help="冻结脚本文件；历史回归与独立留出集分别指定，不能混用结果")
    p.add_argument("--split",choices=["dev","holdout","all"],default="dev");p.add_argument("--case")
    p.add_argument("--limit",type=int,default=1);p.add_argument("--repeats",type=int,default=1)
    p.add_argument("--max-calls",type=int,default=120);p.add_argument("--max-tokens",type=int,default=200000)
    p.add_argument("--output",default="eval/reports/context/baseline.json")
    p.add_argument("--history-tokens",type=int)
    p.add_argument("--summary-target",type=float)
    p.add_argument("--max-cost",type=float)
    p.add_argument("--workers",type=int,default=1,choices=range(1,9),help="独立会话并发数；各实验组须保持一致")
    args=p.parse_args()
    try:sys.exit(asyncio.run(evaluate(args)))
    except RuntimeError as exc:print(str(exc),file=sys.stderr);sys.exit(2)
