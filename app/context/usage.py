"""逐次记录模型调用；服务商没有返回用量时保持未知。"""
import asyncio
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from threading import RLock

from app.services.resilience import ainvoke_with_retry

current_run=ContextVar("context_usage_run",default=None)
evaluation_budget=ContextVar("context_evaluation_budget",default=None)


class EvaluationLimitExceeded(RuntimeError):pass


class EvaluationBudget:
    """仅评测使用：每次请求前预留最坏输出额度，避免超限后继续调用。"""
    def __init__(self,max_calls,max_tokens,max_cost=None):
        self.max_calls,self.max_tokens,self.max_cost=max_calls,max_tokens,max_cost
        self.requests=0;self.tokens=0;self.cost=0.0;self.unknown=False
        self.pending_tokens=0;self.pending_cost=0.0
        self.unbounded_unknown=False;self.unknown_calls=0
        self.unknown_token_reserve=0;self.unknown_cost_reserve=0.0
    def reserve(self,input_tokens,output_tokens,model):
        from app.context.pricing import estimate
        item={"stage":"planning","model":model,"usage":{"input_tokens":input_tokens,"output_tokens":output_tokens,"total_tokens":input_tokens+output_tokens}}
        _,upper_cost,_=estimate([item])
        if self.unbounded_unknown:raise EvaluationLimitExceeded("用量缺失且没有预留上界，停止评测")
        reserved=input_tokens+output_tokens
        if self.requests+1>self.max_calls or self.tokens+self.pending_tokens+reserved>self.max_tokens:
            raise EvaluationLimitExceeded("达到评测调用或 Token 预算")
        if self.max_cost is not None and (upper_cost is None or self.cost+self.pending_cost+upper_cost>self.max_cost):
            raise EvaluationLimitExceeded("金额预算不足或单价不完整")
        self.requests+=1
        # 并发评测请求也须先占用预算，返回后释放预留并计入实际用量。
        self.pending_tokens+=reserved;self.pending_cost+=upper_cost or 0
        return reserved,upper_cost or 0
    def finish(self,call,reservation=None):
        from app.context.pricing import estimate
        if reservation is not None:
            self.pending_tokens-=reservation[0];self.pending_cost-=reservation[1]
        usage=call.get("usage")
        if usage is None:
            self.unknown=True;self.unknown_calls+=1
            if reservation is None:self.unbounded_unknown=True
            else:
                # 未知实际用量保持未知；预算按请求前预留的保守上界扣减，不能当零。
                self.tokens+=reservation[0];self.cost+=reservation[1]
                self.unknown_token_reserve+=reservation[0];self.unknown_cost_reserve+=reservation[1]
            return
        self.tokens+=usage["total_tokens"]
        amount,_,_=estimate([call])
        if amount is not None:self.cost+=amount


@dataclass
class UsageLedger:
    calls: list[dict] = field(default_factory=list)
    context: dict = field(default_factory=dict)

    def begin(self, stage, model):
        call = {"stage": stage, "model": model, "attempt": len(self.calls)+1,
                "status": "running", "usage": None, "elapsed_ms": None}
        self.calls.append(call)
        return call

    def finish(self, call, response, started, status="passed"):
        usage = getattr(response, "usage_metadata", None) if response is not None else None
        call.update(status=status, elapsed_ms=round((time.perf_counter()-started)*1000, 2))
        if usage and all(k in usage for k in ("input_tokens", "output_tokens", "total_tokens")):
            # Token 来自服务商；缓存细目原样保留，不把流事件数当作 Token。
            call["usage"] = {k: usage[k] for k in ("input_tokens", "output_tokens", "total_tokens",
                               "input_token_details", "output_token_details") if k in usage}

    def report(self):
        known = [c["usage"] for c in self.calls if c["usage"] is not None]
        complete = len(known) == len(self.calls)
        totals = {k: sum(u[k] for u in known) for k in ("input_tokens", "output_tokens", "total_tokens")}
        from app.context.pricing import estimate
        cost,uncached,currency=estimate(self.calls)
        return {"model_calls": sum(c["stage"]!="embedding" for c in self.calls),
                "embedding_calls":sum(c["stage"]=="embedding" for c in self.calls), "usage_complete": complete,
                "token_usage": totals if complete else None, "known_token_usage": totals,
                "unknown_usage_calls": len(self.calls)-len(known), "calls": [dict(c) for c in self.calls],
                "cost_estimate":cost,"uncached_cost_estimate":uncached,"currency":currency,
                "cost_note":"按配置单价和服务商用量估算，不等于账单；未覆盖的用量保持未知" if cost is not None else "单价、端点或实际用量不完整，金额未知",**self.context}


_ledgers: dict[str, UsageLedger] = {}
_lock = RLock()


def ledger(run_id):
    with _lock:
        return _ledgers.setdefault(run_id, UsageLedger())


def discard(run_id):
    with _lock:
        _ledgers.pop(run_id, None)


class EmbeddingClient:
    """包装实际请求入口，读取服务商用量，不改变向量返回数据。"""
    def __init__(self,client,model,asynchronous=False):
        self.client,self.model,self.asynchronous=client,model,asynchronous
    def __getattr__(self,name):return getattr(self.client,name)
    def _record(self,started,response,status):
        run_id=current_run.get()
        if not run_id:return
        item=ledger(run_id).begin("embedding",self.model)
        item.update(status=status,elapsed_ms=round((time.perf_counter()-started)*1000,2))
        data=response if isinstance(response,dict) else response.model_dump() if response is not None else {}
        reported=data.get("usage") or {}
        if "prompt_tokens" in reported:
            n=int(reported["prompt_tokens"]);item["usage"]={"input_tokens":n,"output_tokens":0,"total_tokens":n}
    def create(self,**kwargs):
        if self.asynchronous:return self._acreate(**kwargs)
        started=time.perf_counter()
        try:response=self.client.create(**kwargs)
        except BaseException:
            self._record(started,None,"failed");raise
        self._record(started,response,"passed");return response
    async def _acreate(self,**kwargs):
        started=time.perf_counter()
        try:response=await self.client.create(**kwargs)
        except BaseException:
            self._record(started,None,"failed");raise
        self._record(started,response,"passed");return response


async def invoke(model, messages, *, run_id, stage, model_name, retry=True):
    async def attempt(payload):
        from app.context.token_counter import TokenCounter
        tools=getattr(model,"kwargs",{}).get("tools",())
        estimate=TokenCounter().count(payload,tools)
        from app.config import settings
        if settings.context_mode=="enforce":
            from app.context.budget import check
            check(payload,tools,getattr(model,"kwargs",{}).get("max_tokens"))
        guard=evaluation_budget.get()
        reservation=None
        if guard:
            if not TokenCounter().verified:
                import json
                from app.context.token_counter import payload as request_payload
                estimate=max(estimate,len(json.dumps(request_payload(payload,tools),ensure_ascii=False).encode())+32)
            reservation=guard.reserve(estimate,getattr(model,"kwargs",{}).get("max_tokens",settings.context_output_tokens),model_name)
        item = ledger(run_id).begin(stage, model_name)
        item["input_estimate"]=estimate
        started = time.perf_counter()
        try:
            response = await model.ainvoke(payload)
        except BaseException as exc:
            ledger(run_id).finish(item, None, started,
                                  "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed")
            if guard:guard.finish(item,reservation)
            raise
        ledger(run_id).finish(item, response, started)
        if guard:guard.finish(item,reservation)
        return response
    return await ainvoke_with_retry(attempt, messages) if retry else await attempt(messages)


async def stream(model, messages, *, run_id, stage, model_name):
    from app.context.token_counter import TokenCounter
    estimate=TokenCounter().count(messages)
    from app.config import settings
    if settings.context_mode=="enforce":
        from app.context.budget import check
        check(messages,output_tokens=getattr(model,"kwargs",{}).get("max_tokens"))
    item = ledger(run_id).begin(stage, model_name)
    item["input_estimate"]=estimate
    started, combined = time.perf_counter(), None
    try:
        async for chunk in model.astream(messages):
            combined = chunk if combined is None else combined+chunk
            yield chunk
    except BaseException as exc:
        ledger(run_id).finish(item, combined, started,
                              "cancelled" if isinstance(exc, (asyncio.CancelledError, GeneratorExit)) else "failed")
        raise
    ledger(run_id).finish(item, combined, started)
