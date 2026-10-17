"""Frozen S8 protocol, independent metrics and durable pre-request cost reservations.

Evaluation helpers only: production routing and budgets are never patched.
"""
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
from decimal import Decimal
import statistics
import uuid
import re
import unicodedata

ROOT = Path(__file__).resolve().parents[1]


def require(condition,message):
    if not condition:raise ValueError(message)
ARMS = {
    "single_native": dict(multi=False, max_calls=3, normal=3, retries=0, call_seconds=120, code_output=8192, supervisor_output=4096),
    "multi_native": dict(multi=True, max_calls=8, normal=7, retries=1, call_seconds=120, code_output=8192, supervisor_output=4096),
    "single_equal3": dict(multi=False, max_calls=3, normal=3, retries=0, call_seconds=60, code_output=8192, supervisor_output=8192),
    "multi_equal3": dict(multi=True, max_calls=3, normal=3, retries=0, call_seconds=60, code_output=8192, supervisor_output=8192),
}


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(",", ":")).encode()
    return hashlib.sha256(value).hexdigest()


def write_json(path, data, *, exclusive=False):
    path=Path(path)
    text=json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+"\n"
    if exclusive:
        with path.open("x") as handle:
            handle.write(text);handle.flush();os.fsync(handle.fileno())
    else:
        temp=path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
        with temp.open("x") as handle:
            handle.write(text);handle.flush();os.fsync(handle.fileno())
        os.replace(temp,path)


def source_hashes(root=ROOT):
    return {str(p.relative_to(root)):digest(p.read_bytes()) for folder in ("app","eval","sandbox/go")
            for p in sorted((root/folder).rglob("*")) if p.is_file() and
            p.suffix in {".py",".json",".jsonl",".go",".sh"} and "reports" not in p.parts and "__pycache__" not in p.parts}


def validate_cases(cases):
    require(len(cases)==30 and len({c["id"] for c in cases})==30, "Exactly 30 unique cases required")
    require(all(c["split"] in {"dev","holdout"} and c["scenario"] in {"context_cancel","worker_pool","channel"} for c in cases),"Invalid split/scenario")
    for scenario in ("context_cancel","worker_pool","channel"):
        selected=[c for c in cases if c["scenario"]==scenario]
        require(len(selected)==10 and sum(c["split"]=="dev" for c in selected)==6 and sum(c["split"]=="holdout" for c in selected)==4,"Scenario must have 6 dev and 4 holdout")
    require(all(c["checklist"] and len({r["id"] for r in c["checklist"]})==len(c["checklist"]) for c in cases),"Missing/duplicate checklist")
    require(all(r["required"] is True and r["tests"] for c in cases for r in c["checklist"]),"Required independent probes missing")


def validate_live_cases(cases):
    """Reject observable leakage; grouping remains a human reviewed design choice."""
    validate_cases(cases)
    prompts=[re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", c["requirement"]).casefold()) for c in cases]
    require(all(prompts) and len(set(prompts))==len(prompts), "Duplicate normalized public requirements")
    groups={split:{c["group_id"] for c in cases if c["split"]==split} for split in ("dev","holdout")}
    require(all(groups.values()) and not groups["dev"] & groups["holdout"], "Task family crosses development/holdout")
    require(all(c.get("family_rationale") for c in cases), "Task family rationale missing")
    for c in cases:
        if not c["feasible"]:
            require(all(r["tests"]==["server_refusal"] for r in c["checklist"]), "Refusal scoring contract missing")
            continue
        probe=c.get("extra_probe", "")
        names=set(re.findall(r"func\s+(TestEvalCase\w+)\s*\(t \*testing.T\)",probe))
        required={name for r in c["checklist"] for name in r["tests"] if name.startswith("TestEvalCase")}
        require(bool(required) and names==required and probe.startswith("package example\n"), "Independent case probes missing/mismatched")


def freeze(path, image_id, *, model=None,rates=None,cost_cap=None,cases_path=None,protocol_path=None):
    cases=[json.loads(line) for line in Path(cases_path or ROOT/"eval/multi_agent_cases.jsonl").read_text().splitlines() if line.strip()]
    validate_cases(cases)
    protocol=json.loads(Path(protocol_path or ROOT/"eval/multi_agent_protocol.json").read_text())
    if protocol.get("dataset_purpose")=="grouped-live-candidate-v2":validate_live_cases(cases)
    require(protocol["arms"]==ARMS,"Protocol arm settings differ from executable caps")
    if model is not None:
        require(set(model)==set(protocol["live_model"]),"Model config fields differ; never put credentials in frozen config")
        protocol["live_model"]=model
    protocol["live_rates"]=rates
    if cost_cap is not None:protocol["targets"]["live_total_cost_cap"]=str(positive_decimal(cost_cap))
    body=dict(protocol=protocol,cases=cases,source_hashes=source_hashes(),docker_image_id=image_id)
    frozen=dict(**body,freeze_hash=digest(body))
    Path(path).mkdir(parents=True,exist_ok=False)
    write_json(Path(path)/"freeze.json",frozen,exclusive=True)
    return frozen


def load_freeze(path):
    frozen=json.loads((Path(path)/"freeze.json").read_text())
    require(frozen["freeze_hash"]==digest({k:v for k,v in frozen.items() if k!="freeze_hash"}), "Frozen protocol was altered")
    require(frozen["source_hashes"]==source_hashes(), "Code/data/scoring changed: create a new protocol version; do not reuse holdout")
    validate_cases(frozen["cases"])
    if frozen["protocol"].get("dataset_purpose")=="grouped-live-candidate-v2":validate_live_cases(frozen["cases"])
    require(frozen["protocol"]["arms"]==ARMS,"Protocol arm settings changed")
    return frozen


def valid_usage(response):
    data=getattr(response,"usage_metadata",None)
    if not isinstance(data,dict) or any(type(data.get(k)) is not int or data[k]<0
            for k in ("input_tokens","output_tokens","total_tokens")):
        return None
    if data["total_tokens"]!=data["input_tokens"]+data["output_tokens"]:
        return None
    return {k:data[k] for k in ("input_tokens","output_tokens","total_tokens")}


def positive_decimal(value):
    try:amount=Decimal(str(value))
    except Exception as exc:raise ValueError("Explicit numeric cumulative cap/rate required") from exc
    if not amount.is_finite() or amount<=0:
        raise ValueError("A finite positive explicit cumulative cost cap is required")
    return amount


class CostLedger:
    """Cross-process/cross-restart cumulative ceiling. Unknown charges retain full reserve.

    Rates are conservative token ceilings supplied and frozen before live work,
    not a claim about an actual provider invoice. No refund on ambiguous failure.
    """
    def __init__(self,path,cap,currency,rates,identity):
        self.path=Path(path);self.cap=positive_decimal(cap)
        self.identity=dict(cap=str(self.cap),currency=currency,rates=rates,model_identity=identity)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.lock=self.path.with_suffix(self.path.suffix+".lock")
        with self.lock.open("a") as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            if self.path.exists():
                require(self._read()["identity"]==self.identity, "Existing cumulative ledger cannot be reset/repriced/re-capped")
            else:
                write_json(self.path,dict(identity=self.identity,requests=[],blocked=False),exclusive=True)

    def _read(self):
        return json.loads(self.path.read_text())

    def reserve(self,window,output,trial_id):
        worst=(Decimal(window)*Decimal(self.identity["rates"]["input_ceiling_per_million"])+
               Decimal(output)*Decimal(self.identity["rates"]["output_ceiling_per_million"]))/Decimal(1000000)
        if worst<=0:raise ValueError("Unknown/nonpositive price ceiling")
        with self.lock.open("a") as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            state=self._read()
            used=sum((Decimal(r["charged_reserve"]) for r in state["requests"]),Decimal(0))
            if state["blocked"] or used+worst>self.cap:
                raise RuntimeError("Cumulative cost budget exhausted; request not sent")
            ticket=uuid.uuid4().hex
            state["requests"].append(dict(ticket=ticket,trial_id=trial_id,charged_reserve=str(worst),
                reserved_ceiling=str(worst),status="reserved",actual_estimate=None))
            write_json(self.path,state)
            return ticket

    def finish(self,ticket,usage):
        with self.lock.open("a") as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            state=self._read();row=next(r for r in state["requests"] if r["ticket"]==ticket)
            require(row["status"]=="reserved", "Reservation cannot settle twice")
            if usage is None:
                row["status"]="unknown"  # Retain reservation, never zero.
            else:
                cost=(Decimal(usage["input_tokens"])*Decimal(self.identity["rates"]["input_ceiling_per_million"])+
                      Decimal(usage["output_tokens"])*Decimal(self.identity["rates"]["output_ceiling_per_million"]))/Decimal(1000000)
                row.update(status="known",actual_estimate=str(cost),charged_reserve=str(cost))
                if cost>Decimal(row["reserved_ceiling"]):state["blocked"]=True
            write_json(self.path,state)


def live_preflight(frozen,cap=None,rates=None,ledger=None):
    model=frozen["protocol"]["live_model"]; problems=[]
    if frozen["protocol"].get("dataset_purpose")!="grouped-live-candidate-v2":
        problems.append("机制条件样本不能用于正式真实质量评测；需要新冻结的分组任务数据")
    try:validate_live_cases(frozen["cases"])
    except (ValueError,KeyError,TypeError) as exc:problems.append("任务数据预检失败："+str(exc))
    try:positive_decimal(cap)
    except Exception:problems.append("缺少明确、有限、正数的累计费用上限")
    target=frozen["protocol"]["targets"].get("live_total_cost_cap")
    try:
        if positive_decimal(target)!=positive_decimal(cap):problems.append("运行费用上限不等于冻结上限")
    except ValueError:problems.append("累计费用目标尚未冻结；不得评测后修改目标")
    if not ledger:problems.append("缺少跨运行持久化费用账本路径")
    if not model.get("revision_verified") or not model.get("revision"):
        problems.append("模型版本未固定/核实，别名不能视为稳定快照")
    if model.get("name")!=model.get("revision"):
        problems.append("请求的模型名称必须是已核实的固定版本，不能仍请求可变别名")
    if type(model.get("context_window")) is not int or model["context_window"]<26240:
        problems.append("缺少已核实且足够的模型上下文窗口")
    if model.get("temperature")!=0.2 or model.get("sdk_retries")!=0:
        problems.append("模型参数不匹配冻结规则")
    from urllib.parse import urlparse
    url=urlparse(model.get("endpoint") or "")
    if url.scheme!="https" or not url.netloc or url.username or url.password or url.query or url.fragment:
        problems.append("缺少可信 HTTPS 模型端点（不得带凭据或查询参数）")
    if not isinstance(rates,dict) or rates.get("model")!=model.get("name") or rates.get("endpoint")!=model.get("endpoint"):
        problems.append("缺少与模型/端点绑定的冻结单价上界")
    else:
        for key in ("input_ceiling_per_million","output_ceiling_per_million"):
            try:positive_decimal(rates[key])
            except Exception:problems.append("单价上界不完整："+key)
        if not rates.get("currency") or not rates.get("verified_at"):
            problems.append("单价上界缺币种/核实时间；需包含缓存、推理等计费上界")
        if rates.get("includes_all_token_surcharges") is not True:
            problems.append("单价上界未确认覆盖缓存创建、推理等全部 Token 计费")
    return problems


def percentile(values,p):
    if not values:return None
    ordered=sorted(values);pos=(len(ordered)-1)*p
    low=math.floor(pos);high=math.ceil(pos)
    return ordered[low]+(ordered[high]-ordered[low])*(pos-low)


def wilson(success,total):
    if not total:return None
    z=1.96;phat=success/total;den=1+z*z/total
    mid=(phat+z*z/(2*total))/den
    margin=z*math.sqrt(phat*(1-phat)/total+z*z/(4*total*total))/den
    return [max(0,mid-margin),min(1,mid+margin)]


def aggregate(rows):
    out={}
    for arm in ARMS:
        selected=[r for r in rows if r["arm"]==arm];n=len(selected)
        success=sum(r["independent"]["correct"] is True for r in selected)
        labelled=[r for r in selected if r["independent"]["correct"] is not None]
        accepted=[r for r in selected if r.get("business_status")=="passed"]
        independent_good=[r for r in labelled if r["independent"]["correct"]]
        feasible=[r for r in selected if r["feasible"]]
        repairable=[r for r in selected if r.get("initial_independent",{}).get("correct") is False]
        checks=[c for r in selected for c in r["independent"]["checks"]]
        unknown=sum(c["usage"] is None for r in selected for c in r["calls"])
        uncertain_calls=sum(r.get("actual_calls_complete") is False for r in selected)
        known=sum(c["usage"]["total_tokens"] for r in selected for c in r["calls"] if c["usage"] is not None)
        by_role={role:sum(c["role"]==role for r in selected for c in r["calls"]) for role in ("single","supervisor","code")}
        role_usage={role:dict(unknown_usage_calls=sum(c["usage"] is None for r in selected for c in r["calls"] if c["role"]==role),
            known_tokens=sum(c["usage"]["total_tokens"] for r in selected for c in r["calls"] if c["role"]==role and c["usage"] is not None)) for role in by_role}
        out[arm]=dict(runs=n,independent_successes=success,independent_success_rate=success/n if n else None,
            feasible_runs=len(feasible),feasible_successes=sum(r["independent"]["correct"] is True for r in feasible),
            infeasible_runs=n-len(feasible),correct_refusals=sum(r["independent"]["correct"] is True for r in selected if not r["feasible"]),
            business_pass_rate=len(accepted)/n if n else None,
            success_wilson95=wilson(success,n),unverified_runs=n-len(labelled),
            requirement_checks=len(checks),requirement_pass_rate=sum(c["status"]=="pass" for c in checks)/len(checks) if checks else None,
            false_accepts=sum(r["independent"]["correct"] is False for r in accepted),
            false_accept_denominator=len(accepted),false_accept_unknown=sum(r["independent"]["correct"] is None for r in accepted),
            false_rejects=sum(r.get("business_status")!="passed" for r in independent_good),false_reject_denominator=len(independent_good),
            repair_eligible=len(repairable),repair_success_rate=sum(r["independent"]["correct"] is True for r in repairable)/len(repairable) if repairable else None,
            model_calls=None if uncertain_calls else sum(len(r["calls"]) for r in selected),role_calls=None if uncertain_calls else by_role,
            known_role_calls=by_role,role_usage=role_usage,
            incomplete_call_count_runs=uncertain_calls,model_calls_known_lower_bound=sum(len(r["calls"]) for r in selected),
            mean_calls=statistics.mean(len(r["calls"]) for r in selected) if n and not uncertain_calls else None,
            unknown_usage_calls=None if uncertain_calls else unknown,known_unknown_usage_calls=unknown,
            known_token_subtotal=known,total_tokens=None if unknown or uncertain_calls else known,
            cost_estimate=None if any(r["cost_estimate"] is None for r in selected) else sum(r["cost_estimate"] for r in selected),
            generation_p50_ms=percentile([r["generation_ms"] for r in selected if r["generation_ms"] is not None],.5),
            generation_p95_ms=percentile([r["generation_ms"] for r in selected if r["generation_ms"] is not None],.95),
            scoring_p50_ms=percentile([r["scoring_ms"] for r in selected if r["scoring_ms"] is not None],.5),
            scoring_p95_ms=percentile([r["scoring_ms"] for r in selected if r["scoring_ms"] is not None],.95),
            end_to_end_p50_ms=percentile([r["generation_ms"]+r["scoring_ms"] for r in selected if r["generation_ms"] is not None and r["scoring_ms"] is not None],.5),
            end_to_end_p95_ms=percentile([r["generation_ms"]+r["scoring_ms"] for r in selected if r["generation_ms"] is not None and r["scoring_ms"] is not None],.95),
            stop_reasons={reason:sum(r.get("stop_reason")==reason for r in selected) for reason in sorted({r.get("stop_reason", "unknown") for r in selected})})
    return out
