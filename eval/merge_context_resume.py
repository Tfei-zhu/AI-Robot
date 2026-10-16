"""合并已校验续跑结果；终局质量按唯一任务统计，成本及调用包含所有中断尝试。"""
import argparse
import json
import math
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from eval.resume_context_eval import digest, load_frozen, read_json, verified_attempts, write_json


def turn_metrics(rows):
    turns = [t for row in rows for t in row["turns"]]
    stats = [t.get("context_stats", {}) for t in turns]
    calls = [c for s in stats for c in s.get("calls", [])]
    latencies = sorted(t["elapsed_ms"] for t in turns)
    summaries = [c for c in calls if c["stage"] == "summary"]
    triggered = sorted(t["elapsed_ms"] for t in turns if any(c["stage"] == "summary" for c in t.get("context_stats", {}).get("calls", [])))
    def sum_known(key):
        return sum(c["usage"][key] for c in calls if c.get("usage"))
    def sum_cost(key):
        values = [s.get(key) for s in stats]
        return sum(values) if values and all(v is not None for v in values) else None
    duplicates = 0
    for row in rows:
        seen = set()
        for turn in row["turns"]:
            for step in turn.get("steps", []):
                if step.get("type") == "tool_call" and step.get("tool") == "search_knowledge":
                    key = json.dumps(step.get("args", {}), ensure_ascii=False, sort_keys=True)
                    duplicates += key in seen
                    seen.add(key)
    return {"model_calls": len(calls), "known_total_tokens": sum_known("total_tokens"),
            "input_tokens": sum_known("input_tokens"), "output_tokens": sum_known("output_tokens"),
            "unknown_usage_calls": sum(c.get("usage") is None for c in calls),
            "cost_estimate": sum_cost("cost_estimate"), "uncached_cost_estimate": sum_cost("uncached_cost_estimate"),
            "currency": next((s.get("currency") for s in stats if s.get("currency")), None),
            **{name: sum(s.get(name, 0) for s in stats) for name in ("retrieval_requested", "retrieval_executed", "retrieval_reused")},
            "duplicate_retrieval_requests": duplicates,
            "summary_calls": sum(c["stage"] == "summary" for c in calls),
            "summary_model_time_total_ms": sum(c.get("elapsed_ms") or 0 for c in summaries),
            "summary_input_tokens": sum(c["usage"]["input_tokens"] for c in summaries if c.get("usage")),
            "summary_output_tokens": sum(c["usage"]["output_tokens"] for c in summaries if c.get("usage")),
            "summary_triggered_turn_p95_ms": triggered[max(0, math.ceil(.95 * len(triggered)) - 1)] if triggered else None,
            "counter_underestimates": sum(c.get("input_estimate", 0) < c["usage"]["input_tokens"]
                                           for c in calls if c.get("usage") and c["stage"] != "embedding"),
            "turn_p50_ms": statistics.median(latencies) if latencies else None,
            "turn_p95_ms": latencies[max(0, math.ceil(.95 * len(latencies)) - 1)] if latencies else None,
            "long_input_tokens_including_interrupted": sum(c["usage"]["input_tokens"] for row in rows if row["length"] >= 30
                for t in row["turns"] for c in t.get("context_stats", {}).get("calls", []) if c.get("usage"))}


def quality_metrics(rows):
    executed = [r for r in rows if r["turns"]]
    evidence = [v for row in rows for v in row["evidence_checks"]]
    ordinary = [v for row in rows for v in row["ordinary_checks"]]
    return {"started_tasks": len(executed), "finished_tasks": sum(r["completed"] for r in rows),
            "task_completion_rate": sum(r["task_pass"] for r in executed) / len(executed) if executed else None,
            "constraint_retention_rate": sum(sum(r["constraints"].values()) for r in executed) / (4 * len(executed)) if executed else None,
            "evidence_retention_rate": sum(evidence) / len(evidence) if evidence else None,
            "ordinary_constraint_retention_rate": sum(ordinary) / len(ordinary) if ordinary else None}


def merge(manifest, reports, cases):
    # verified_attempts同时检查样本重复、哈希及条件；原有完整失败样本不会被成功重跑替换。
    outcomes, _ = verified_attempts(manifest, reports, cases)
    result = {}
    for group, base in reports.items():
        additions = [a for a in manifest["attempts"] if a["group"] == group]
        source_reports = [base] + [read_json(a["report"]) for a in additions]
        historical_errors = [{**error, "source_report": manifest["base_reports"][group]["path"]}
                             for error in base.get("task_errors", [])]
        for attempt, source in zip(additions, source_reports[1:]):
            historical_errors += [{**error, "source_repeat": error["repeat"], "repeat": attempt["repeat"],
                                   "source_report": attempt["report"]} for error in source.get("task_errors", [])]
        rows = [row for _, row in sorted(outcomes[group].items())]
        attempt_rows = [row for report in source_reports for row in report["results"]]
        incomplete = len(rows) != base["scheduled_tasks"] or any(not r["completed"] for r in rows)
        budget_names = ("requests", "tokens_charged_for_limit", "cost_charged_for_limit", "unknown_calls",
                        "unknown_token_upper_reserve", "unknown_cost_upper_reserve")
        report = {**base, **quality_metrics(rows), **turn_metrics(attempt_rows), "results": rows,
                  "stop_reason": "续跑尚未完成" if incomplete else None,
                  "evaluation_budget": {name: sum(r["evaluation_budget"].get(name, 0) for r in source_reports) for name in budget_names},
                  "elapsed_ms": sum(r.get("elapsed_ms", 0) for r in source_reports),
                  "elapsed_scope": "各执行批次耗时之和，不含等待账户恢复的空闲时间",
                  "attempted_tasks_including_interrupted": len(attempt_rows),
                  "task_errors": [{"id": r["id"], "repeat": r["repeat"]} for r in rows if not r["completed"]],
                  "historical_attempt_errors": historical_errors,
                  "first_attempt_quality": quality_metrics(base["results"]),
                  "latest_task_turn_metrics": turn_metrics(rows),
                  "resume_provenance": {"base_report": manifest["base_reports"][group],
                      "additional_reports": [a for a in manifest["attempts"] if a["group"] == group],
                      "runtime_identity": manifest.get("resume_runtime_identity"), "limitations": manifest["limitations"],
                      "aggregation": "质量按唯一任务最后一次执行；费用、调用、检索及延迟含原中断尝试。完整失败任务保持失败。",
                      "formal_release_claim": False}}
        result[group] = report
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", default="eval/reports/context/final-restored-v3")
    parser.add_argument("--dataset", default="eval/context_cases.jsonl")
    parser.add_argument("--resume-directory", default="eval/reports/context/resume-restored-v3")
    parser.add_argument("--output-directory", default="eval/reports/context/final-resumed-v3")
    args = parser.parse_args()
    try:
        if Path(args.output_directory).resolve() in {Path(args.directory).resolve(), Path(args.resume_directory).resolve()}:
            raise RuntimeError("合并输出必须与原始报告及续跑报告目录分开")
        reports, cases = load_frozen(Path(args.directory), Path(args.dataset))
        manifest = read_json(Path(args.resume_directory) / "resume-progress.json")
        for group in reports:
            original = Path(args.directory).resolve() / f"{group}.json"
            if manifest["base_reports"][group] != {"path": str(original), "sha256": digest(original)}:
                raise RuntimeError("原始报告哈希不一致")
        if manifest.get("inflight"):
            raise RuntimeError("仍有执行或未结算批次，不能生成最终报告")
        merged = merge(manifest, reports, cases)
        for group, report in merged.items():
            write_json(Path(args.output_directory) / f"{group}.json", report)
        print(json.dumps({g: {k: r[k] for k in ("finished_tasks", "task_completion_rate", "unknown_usage_calls", "cost_estimate")}
                          for g, r in merged.items()}, ensure_ascii=False))
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
