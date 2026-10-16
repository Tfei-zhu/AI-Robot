"""按脚本聚类做配对比较；未运行样本、质量失败和效率不达标均明确列出。"""
import argparse
import json
import random
import statistics
import sys
import ast
import hashlib
from pathlib import Path


def summary_source_equivalence(old_path,new_path):
    old_bytes,new_bytes=Path(old_path).read_bytes(),Path(new_path).read_bytes()
    old,new=ast.parse(old_bytes.decode("utf-8")),ast.parse(new_bytes.decode("utf-8"))
    def function(tree,name):return next(n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
    def shared(tree):
        return ast.dump(ast.Module(body=[n for n in tree.body if not(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in {"prepare","normalize"})],type_ignores=[]))
    before,after=function(old,"prepare"),function(new,"prepare")
    # A/B/C均在prepare首个条件返回；公共函数、导入、全局状态及该条件必须相同。
    guard=after.body[0]
    safe_guard=isinstance(guard,ast.If) and len(guard.body)==1 and isinstance(guard.body[0],ast.Return)
    valid=(shared(old)==shared(new) and ast.dump(before.args)==ast.dump(after.args)
           and not before.decorator_list and not after.decorator_list
           and ast.dump(before.body[0])==ast.dump(guard) and safe_guard)
    helpers=[n for n in new.body if isinstance(n,ast.FunctionDef) and n.name=="normalize"]
    valid &= all(not n.decorator_list and not n.args.defaults and not any(n.args.kw_defaults) for n in helpers)
    return {"file":"app/context/summary.py","baseline_sha256":hashlib.sha256(old_bytes).hexdigest(),
            "candidate_sha256":hashlib.sha256(new_bytes).hexdigest(),"shared_paths_unchanged":bool(valid),
            "scope":"A/B/C摘要关闭，首个分支直接返回；仅D组执行修改后的摘要专用代码。"}


def supplemental_metrics(report):
    turns=[t for row in report["results"] for t in row["turns"]]
    calls=[c for t in turns for c in t["context_stats"].get("calls",[])]
    summaries=[c for c in calls if c["stage"]=="summary"]
    triggered=[t["elapsed_ms"] for t in turns if any(c["stage"]=="summary" for c in t["context_stats"].get("calls",[]))]
    def p95(values):
        import math
        return sorted(values)[max(0,math.ceil(len(values)*.95)-1)] if values else None
    passed=sum(row["task_pass"] for row in report["results"])
    finished=sum(row["completed"] for row in report["results"])
    cost=report.get("cost_estimate")
    result={"summary_triggered_turn_p95_ms":p95(triggered),
            "summary_model_time_total_ms":sum(c["elapsed_ms"] or 0 for c in summaries),
            "summary_input_tokens":sum(c["usage"]["input_tokens"] for c in summaries if c.get("usage")),
            "summary_output_tokens":sum(c["usage"]["output_tokens"] for c in summaries if c.get("usage")),
            "cost_per_finished_task":cost/finished if cost is not None and finished else None,
            "cost_per_successful_task":cost/passed if cost is not None and passed else None}
    # 续跑报告的这些字段包含旧中断尝试，不能被仅完整任务的统计覆盖。
    for name in ("summary_triggered_turn_p95_ms","summary_model_time_total_ms","summary_input_tokens","summary_output_tokens"):
        if name in report:result[name]=report[name]
    return result


def compare(reports,summary_equivalence=None):
    baseline,final=reports["A"],reports["D"]
    keys=lambda r:{(x["id"],x["repeat"]) for x in r["results"]}
    same=all(keys(r)==keys(baseline) and not r.get("stop_reason") for r in reports.values())
    same&=all(r.get("dataset_sha256")==baseline.get("dataset_sha256") for r in reports.values())
    same_source=all(r.get("source_sha256")==baseline.get("source_sha256") for r in reports.values())
    if not same_source and summary_equivalence and summary_equivalence["shared_paths_unchanged"]:
        name=summary_equivalence["file"]
        shared_hash=lambda r:{k:v for k,v in r.get("source_sha256",{}).items() if k!=name}
        same_source=all(shared_hash(r)==shared_hash(baseline) for r in reports.values())
        same_source &= all(reports[g]["source_sha256"].get(name)==summary_equivalence["baseline_sha256"] for g in "ABC")
        same_source &= final["source_sha256"].get(name)==summary_equivalence["candidate_sha256"]
    same &= same_source
    same&=all(r.get("model")==baseline.get("model") and r.get("parameters")==baseline.get("parameters") for r in reports.values())
    same&=all(r.get("grading_version")==baseline.get("grading_version") and r.get("history_tokens")==baseline.get("history_tokens")
              and r.get("summary_target_ratio")==baseline.get("summary_target_ratio") for r in reports.values())
    final_rows={(r["id"],r["repeat"]):r for r in final["results"]}
    differences={}
    for row in baseline["results"]:
        other=final_rows.get((row["id"],row["repeat"]))
        if other is not None:differences.setdefault(row["id"],[]).append(int(other["task_pass"])-int(row["task_pass"]))
    per_script=[statistics.mean(v) for v in differences.values()]
    rng=random.Random(20261014)
    samples=sorted(statistics.mean(rng.choices(per_script,k=len(per_script))) for _ in range(10000)) if per_script else []
    interval=[samples[249],samples[9749]] if samples else None
    long_input=lambda r:r.get("long_input_tokens_including_interrupted",sum(c["usage"]["input_tokens"] for row in r["results"] if row.get("length",0)>=30
                            for t in row["turns"] for c in t["context_stats"].get("calls",[]) if c.get("usage")))
    old_long,new_long=long_input(baseline),long_input(final)
    saving=1-new_long/old_long if old_long else None
    holdout=[r for r in final["results"] if r.get("split")=="holdout"]
    expected={(f"context-{i:02d}",repeat) for i in range(30) for repeat in range(3)}
    complete_matrix=all(keys(r)==expected and len(r["results"])==90 and r.get("finished_tasks")==90 for r in reports.values())
    comparable=bool(same and complete_matrix)
    # 任务没有全部完成时，不用较少执行轮次制造Token节省或质量通过的结论。
    if not comparable:saving=None;interval=None
    old_p95,new_p95=baseline.get("turn_p95_ms"),final.get("turn_p95_ms")
    gates={"same_inputs_and_samples":same,"complete_30_scripts_times_3":complete_matrix,
           "task_noninferiority":interval is not None and interval[0]>=-.03,
           "hard_constraints":final.get("constraint_retention_rate")==1,
           "tail_evidence":final.get("evidence_retention_rate")==1,
           "ordinary_constraints_98_percent":final.get("ordinary_constraint_retention_rate",0)>=.98,
           "holdout_quality":len(holdout)==30 and all(r["task_pass"] for r in holdout),
           "actual_usage_complete":all(r.get("unknown_usage_calls")==0 for r in reports.values()),
           "counter_conservative":all(r.get("counter_underestimates",1)==0 for r in reports.values()),
           "long_input_saving_20_percent":saving is not None and saving>=.2,
           "duplicate_requests_not_increased":comparable and final.get("duplicate_retrieval_requests",0)<=baseline.get("duplicate_retrieval_requests",0),
           "p95_not_increased_over_10_percent":comparable and old_p95 is not None and new_p95 is not None and new_p95<=old_p95*1.1,
           "cost_not_increased":comparable and final.get("cost_estimate") is not None and baseline.get("cost_estimate") is not None and final["cost_estimate"]<=baseline["cost_estimate"]}
    return {"scope":"固定工具数据下的真实长对话约束任务；金额为公开单价估算，不等于账单",
            "gates":gates,"release_allowed":all(gates.values()),"paired_task_difference_95_ci":interval,
            "comparisons_valid":comparable,
            "summary_source_equivalence":summary_equivalence,
            "long_input_saving":saving,"results":{g:{**{k:v for k,v in r.items() if k not in ("results","source_sha256")},
                **supplemental_metrics(r)} for g,r in reports.items()},
            "limitations":["只对固定脚本和所测模型有效，不能外推任意工程任务。",
                "矩阵为非流式任务；首Token延迟单独通过SSE探针记录，未在四组矩阵中配对比较。",
                "并发数固定，网络时段和服务商负载不可严格控制。",
                "基线若没有成功任务，其每成功任务成本无法定义，不能以总成本替代该结论。",
                "真实Embedding凭据与向量检索必须另行通过实际调用验收。"]}


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--directory",default="eval/reports/context/final")
    p.add_argument("--output",default="eval/reports/context/final/comparison.json")
    p.add_argument("--baseline-summary-source",help="仅摘要关闭组可复用；通过AST验证公共路径一致，不能忽略任意源文件差异")
    args=p.parse_args()
    reports={g:json.loads((Path(args.directory)/f"{g}.json").read_text(encoding="utf-8")) for g in "ABCD"}
    proof=summary_source_equivalence(args.baseline_summary_source,Path(__file__).resolve().parents[1]/"app/context/summary.py") if args.baseline_summary_source else None
    result=compare(reports,proof);target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="results"},ensure_ascii=False,indent=2))
    sys.exit(0 if result["release_allowed"] else 1)
