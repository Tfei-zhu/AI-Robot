"""校验冻结实验并续跑未完成样本；默认只生成计划，不发送模型请求。"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
GROUPS = "ABCD"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, data):
    # 原子替换清单，意外退出时保留上一版有效记录。
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def source_files(root):
    names = ["app/agents/graph.py", "app/agents/tools.py", "app/services/chat.py",
             "app/services/memory.py", "app/config.py", "eval/run_context_eval.py"]
    names += sorted(p.relative_to(root).as_posix() for p in (root / "app/context").glob("*.py"))
    return {name: digest(root / name) for name in names}


def runtime_identity(settings):
    # 只保存非敏感参数和文件哈希，密钥不进入清单；追加批次不能更换计价口径。
    names = ("context_model_window", "context_input_limit", "context_safety_tokens", "context_summary_tokens",
             "context_evidence_tokens", "context_tool_tokens", "context_read_tokens", "context_encoding",
             "context_evidence_ttl", "context_summary_timeout", "context_summary_trigger_ratio",
             "memory_max_turns", "memory_retrieve_turns", "agent_max_tool_rounds", "retry_attempts", "retry_max_wait")
    return {"endpoint_sha256": hashlib.sha256(settings.llm_base_url.encode()).hexdigest(),
            "parameters": {name: getattr(settings, name) for name in names},
            "price_book_sha256": digest(settings.context_price_book) if settings.context_price_book else None,
            "calibration_sha256": digest(settings.context_calibration_path) if settings.context_calibration_path else None}


def validate_rows(report, cases, repeats):
    seen = set()
    for row in report["results"]:
        key = (row["id"], row["repeat"])
        if key in seen or row["id"] not in cases or row["repeat"] not in range(repeats):
            raise RuntimeError("报告包含重复或不属于冻结数据集的样本")
        seen.add(key)
        case = cases[row["id"]]
        if any(row[name] != case[name] for name in ("length", "kind", "split")):
            raise RuntimeError("样本元数据与冻结数据集不一致")
        if row["completed"] and [t["turn"] for t in row["turns"]] != list(range(1, case["length"] + 1)):
            raise RuntimeError("完整样本缺少轮次，不能复用")
    if report["finished_tasks"] != sum(r["completed"] for r in report["results"]):
        raise RuntimeError("报告完成数量与逐任务记录不一致")


def load_frozen(directory, dataset, root=ROOT):
    cases = {c["id"]: c for c in (json.loads(s) for s in Path(dataset).read_text(encoding="utf-8").splitlines() if s.strip())}
    reports = {g: read_json(Path(directory) / f"{g}.json") for g in GROUPS}
    reference = reports["A"]
    actual_sources = source_files(root)
    identity = ("dataset_sha256", "source_sha256", "model", "parameters", "grading_version",
                "dataset_version", "history_tokens", "summary_target_ratio")
    for group, report in reports.items():
        if report["group"] != group or any(report.get(k) != reference.get(k) for k in identity):
            raise RuntimeError("四组冻结实验的代码、数据、模型或参数不一致")
        if report["dataset_sha256"] != digest(dataset) or report["source_sha256"] != actual_sources:
            raise RuntimeError("代码或数据已变化，不能复用旧样本")
        if report["scheduled_tasks"] != len(cases) * report["parameters"]["repeats"]:
            raise RuntimeError("只支持冻结的完整数据集，不能混入局部冒烟报告")
        validate_rows(report, cases, report["parameters"]["repeats"])
    return reports, cases


def verified_attempts(manifest, reports, cases):
    outcomes = {g: {(r["id"], r["repeat"]): r for r in report["results"]} for g, report in reports.items()}
    charges = {"requests": 0, "tokens_charged_for_limit": 0, "cost_charged_for_limit": 0.0}
    for attempt in manifest.get("attempts", []):
        path = Path(attempt["report"])
        if digest(path) != attempt["sha256"]:
            raise RuntimeError("续跑报告已变化，停止以保护费用记录")
        report = read_json(path)
        group, repeat = attempt["group"], attempt["repeat"]
        base = reports[group]
        parameters = {**base["parameters"], "repeats": 1}
        fields = ("source_sha256", "dataset_sha256", "model", "grading_version", "dataset_version",
                  "history_tokens", "summary_target_ratio")
        if report["group"] != group or report["parameters"] != parameters or any(report.get(k) != base.get(k) for k in fields):
            raise RuntimeError("续跑报告条件与冻结实验不一致")
        selected = {name: cases[name] for name in attempt["cases"]}
        if report["scheduled_tasks"] != len(selected):
            raise RuntimeError("续跑报告任务数量不一致")
        validate_rows(report, selected, 1)
        for row in report["results"]:
            key = (row["id"], repeat)
            if outcomes[group].get(key, {}).get("completed"):
                raise RuntimeError("续跑重复执行了已完成样本")
            # repeat仅用于样本编号；原始报告保留repeat=0及其文件哈希。
            outcomes[group][key] = {**row, "repeat": repeat}
        budget = report["evaluation_budget"]
        for name in charges:
            value = budget[name]
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise RuntimeError("续跑费用或用量记录无效")
            charges[name] += value
    return outcomes, charges


def pending_batches(outcomes, cases, repeats):
    return [{"group": group, "repeat": repeat, "cases": names}
            for group in GROUPS for repeat in range(repeats)
            if (names := [name for name in sorted(cases) if not outcomes[group].get((name, repeat), {}).get("completed")])]


def refresh(manifest, reports, cases):
    outcomes, charges = verified_attempts(manifest, reports, cases)
    repeats = reports["A"]["parameters"]["repeats"]
    manifest["pending_batches"] = pending_batches(outcomes, cases, repeats)
    manifest["additional_budget_usage"] = charges
    manifest["completed_by_group"] = {g: sum(r["completed"] for r in rows.values()) for g, rows in outcomes.items()}
    manifest["remaining_tasks"] = sum(len(b["cases"]) for b in manifest["pending_batches"])
    manifest["quality_outcomes"] = {g: [{"id": name, "repeat": repeat, "completed": row["completed"], "task_pass": row["task_pass"]}
                                        for (name, repeat), row in sorted(rows.items())] for g, rows in outcomes.items()}
    # 进度清单不能冒充正式比较报告；旧中断开销与未知用量始终留在原报告。
    manifest["release_allowed"] = False
    manifest["formal_comparison_required"] = True
    return manifest


def build_command(batch, base, dataset, output, remaining):
    return [sys.executable, str(ROOT / "eval/run_context_eval.py"), "--live", "--group", batch["group"],
            "--dataset", str(Path(dataset).resolve()), "--split", "all", "--case", ",".join(batch["cases"]),
            "--limit", "0", "--repeats", "1", "--workers", str(base["parameters"]["workers"]),
            "--history-tokens", str(base["history_tokens"]), "--summary-target", str(base["summary_target_ratio"]),
            "--max-calls", str(remaining["requests"]), "--max-tokens", str(remaining["tokens"]),
            "--max-cost", str(remaining["cost"]), "--output", str(output)]


def resume(args, *, execute=subprocess.run):
    directory, dataset, output = Path(args.directory).resolve(), Path(args.dataset).resolve(), Path(args.output_directory).resolve()
    if directory == output:
        raise RuntimeError("续跑输出目录必须与原始报告分开")
    if any(not math.isfinite(n) or n < 0 for n in (args.max_cost, args.max_tokens, args.max_calls)):
        raise RuntimeError("续跑累计总预算必须为有限非负数")
    reports, cases = load_frozen(directory, dataset)
    base_files = {g: {"path": str(directory / f"{g}.json"), "sha256": digest(directory / f"{g}.json")} for g in GROUPS}
    target = output / "resume-progress.json"
    manifest = read_json(target) if target.exists() else {
        "kind": "context-evaluation-resume-progress-v1", "base_reports": base_files, "attempts": [],
        "scope": "复用所有完整样本，包括未通过样本；中断样本从第一轮重跑。追加预算四组共用且跨续跑调用累计。",
        "limitations": ["原报告缺少完整运行配置快照及服务商模型版本标识，不能严格证明所有运行条件相同。",
                        "新旧批次网络时段、服务端缓存和调度边界不同；原中断尝试的费用及未知用量不得从正式验收中删除。",
                        "每个批次repeats=1，清单映射到原样本编号；不改写原始逐轮报告或冻结评测器。"]}
    if manifest["base_reports"] != base_files:
        raise RuntimeError("冻结报告发生变化，不能沿用已有续跑清单")
    refresh(manifest, reports, cases)
    write_json(target, manifest)
    if not args.live:
        print(json.dumps({k: manifest[k] for k in ("completed_by_group", "remaining_tasks", "additional_budget_usage")}, ensure_ascii=False))
        return 0
    # 上次批次若异常退出且没有完整费用记录，不能重新启动绕过累计预算。
    if manifest.get("inflight"):
        raise RuntimeError("存在未结算批次，须先恢复其完整用量记录；停止付费请求")
    sys.path.insert(0, str(ROOT))
    from app.config import settings
    from app.context.token_counter import TokenCounter
    from app.context.pricing import estimate
    if settings.llm_model != reports["A"]["model"] or not TokenCounter().verified:
        raise RuntimeError("模型不匹配或Token计数未校准，停止续跑")
    price, _, currency = estimate([{"stage": "planning", "model": settings.llm_model,
                                    "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}])
    if price is None or currency != "CNY":
        raise RuntimeError("需配置同端点人民币单价后才能执行金额预算")
    identity = runtime_identity(settings)
    if manifest.get("resume_runtime_identity", identity) != identity:
        raise RuntimeError("续跑的配置、计价或校准文件发生变化，停止付费请求")
    manifest["resume_runtime_identity"] = identity
    write_json(target, manifest)
    while manifest["pending_batches"]:
        charged = manifest["additional_budget_usage"]
        remaining = {"requests": args.max_calls - charged["requests"], "tokens": args.max_tokens - charged["tokens_charged_for_limit"],
                     "cost": args.max_cost - charged["cost_charged_for_limit"]}
        if min(remaining.values()) <= 0:
            manifest["stop_reason"] = "断点续跑累计总预算已用尽"
            break
        # 每个批次开始前重新校验全部冻结代码和数据；不修改主评测器以保留原哈希。
        load_frozen(directory, dataset)
        if runtime_identity(settings) != identity:
            raise RuntimeError("续跑配置已变化，停止付费请求")
        batch = manifest["pending_batches"][0]
        name = f'{len(manifest["attempts"]):03d}-{batch["group"]}-{batch["repeat"]}'
        report_path = output / f"{name}.json"
        manifest["inflight"] = {**batch, "report": str(report_path)}
        write_json(target, manifest)
        env = dict(os.environ)
        env["AIROBOT_CONTEXT_STORE_PATH"] = str(output / f'{batch["group"]}.sqlite3')
        with (output / f"{name}.log").open("w", encoding="utf-8") as log:
            result = execute(build_command(batch, reports[batch["group"]], dataset, report_path, remaining),
                             cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        # 缺少最终结算报告时保留inflight并停止；不把未知开销当零。
        report = read_json(report_path)
        if "evaluation_budget" not in report:
            raise RuntimeError("批次缺少最终费用记录，停止后续付费请求")
        manifest["attempts"].append({**manifest.pop("inflight"), "sha256": digest(report_path)})
        refresh(manifest, reports, cases)
        manifest["stop_reason"] = report.get("stop_reason")
        write_json(target, manifest)
        if result.returncode or report.get("stop_reason"):
            break
    write_json(target, manifest)
    return 2 if manifest["remaining_tasks"] else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", default="eval/reports/context/final-restored-v3")
    parser.add_argument("--dataset", default="eval/context_cases.jsonl")
    parser.add_argument("--output-directory", default="eval/reports/context/resume-restored-v3")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--max-cost", type=float, default=0, help="四组续跑累计总上限，单位人民币；默认0不付费")
    parser.add_argument("--max-calls", type=int, default=10000)
    parser.add_argument("--max-tokens", type=int, default=8000000)
    try:
        sys.exit(resume(parser.parse_args()))
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
