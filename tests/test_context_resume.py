"""断点续跑只复用完整样本，原失败、未知开销与累计总预算不能被清除。"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from eval import resume_context_eval as runner


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    root = tmp_path / "project"
    (root / "app/context").mkdir(parents=True)
    for name in ("app/agents/graph.py", "app/agents/tools.py", "app/services/chat.py",
                 "app/services/memory.py", "app/config.py", "eval/run_context_eval.py"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# 冻结源文件\n", encoding="utf-8")
    dataset = root / "cases.jsonl"
    cases = [{"id": name, "kind": "constraint", "length": 2, "split": "dev", "turns": ["甲", "乙"]}
             for name in ("one", "two")]
    dataset.write_text("\n".join(json.dumps(c) for c in cases), encoding="utf-8")
    directory = root / "original"
    directory.mkdir()
    for group in runner.GROUPS:
        report = {"group": group, "dataset_sha256": runner.digest(dataset), "source_sha256": runner.source_files(root),
                  "model": "qwen-plus", "parameters": {"repeats": 2, "workers": 2, "max_output_tokens": 384},
                  "grading_version": "fixture", "dataset_version": 3, "history_tokens": 1200,
                  "summary_target_ratio": .1, "scheduled_tasks": 4, "finished_tasks": 1,
                  "evaluation_budget": {"requests": 100, "tokens_charged_for_limit": 900, "cost_charged_for_limit": 9},
                  "unknown_usage_calls": 1, "cost_estimate": None,
                  "results": [row("one", 0, True, False), row("one", 1, False, False)]}
        runner.write_json(directory / f"{group}.json", report)
    original_load = runner.load_frozen
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "load_frozen", lambda d, p: original_load(d, p, root))
    args = argparse.Namespace(directory=directory, dataset=dataset, output_directory=root / "resume", live=False,
                              max_cost=1.0, max_calls=100, max_tokens=1000)
    return args


def row(name, repeat, completed, passed):
    return {"id": name, "repeat": repeat, "kind": "constraint", "length": 2, "split": "dev",
            "completed": completed, "task_pass": passed, "turns": [{"turn": i} for i in range(1, 3 if completed else 2)]}


def progress(args):
    return runner.read_json(args.output_directory / "resume-progress.json")


def test_plan_never_calls_model_and_retains_completed_failures(frozen):
    def forbidden(*a, **kw):
        pytest.fail("计划不应发起付费请求")
    assert runner.resume(frozen, execute=forbidden) == 0
    result = progress(frozen)
    assert result["completed_by_group"] == dict.fromkeys("ABCD", 1)
    assert result["remaining_tasks"] == 12
    assert result["additional_budget_usage"]["cost_charged_for_limit"] == 0
    assert result["release_allowed"] is False
    assert result["quality_outcomes"]["A"][0]["task_pass"] is False
    assert not any(b["repeat"] == 0 and "one" in b["cases"] for b in result["pending_batches"])
    assert runner.read_json(frozen.directory / "A.json")["unknown_usage_calls"] == 1


@pytest.mark.parametrize("change", ["source", "dataset", "parameters", "missing_turn", "duplicate"])
def test_resume_rejects_changed_inputs_or_invalid_complete_rows(frozen, change):
    if change == "source":
        (Path(frozen.directory).parent / "app/config.py").write_text("changed", encoding="utf-8")
    elif change == "dataset":
        frozen.dataset.write_text(frozen.dataset.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    else:
        path = frozen.directory / "D.json"
        report = runner.read_json(path)
        if change == "parameters":
            report["parameters"]["workers"] = 4
        elif change == "missing_turn":
            report["results"][0]["turns"].pop()
        else:
            report["results"].append(deepcopy(report["results"][0]))
        runner.write_json(path, report)
    with pytest.raises(RuntimeError):
        runner.resume(frozen)


def configure_offline_live(monkeypatch):
    from app.config import settings
    from app.context import token_counter
    from app.context import pricing
    monkeypatch.setattr(settings, "llm_model", "qwen-plus")
    monkeypatch.setattr(token_counter, "TokenCounter", lambda: SimpleNamespace(verified=True))
    monkeypatch.setattr(pricing, "estimate", lambda calls: (.01, .01, "CNY"))
    monkeypatch.setattr(runner, "runtime_identity", lambda settings: {"fixture": "frozen"})


def test_live_uses_one_cumulative_budget_across_groups_and_restarts(monkeypatch, frozen):
    configure_offline_live(monkeypatch)
    frozen.live = True
    received = []
    def fake_execute(command, **kwargs):
        # 模拟付费执行器，不发起网络请求；第二批用尽剩余总额度。
        value = lambda flag: command[command.index(flag) + 1]
        received.append(float(value("--max-cost")))
        group, ids = value("--group"), value("--case").split(",")
        report = runner.read_json(frozen.directory / f"{group}.json")
        report["parameters"]["repeats"] = 1
        report["scheduled_tasks"] = len(ids)
        report["results"] = [row(name, 0, True, True) for name in ids]
        report["finished_tasks"] = len(ids)
        report["evaluation_budget"] = {"requests": 2, "tokens_charged_for_limit": 6,
                                       "cost_charged_for_limit": min(.6, received[-1])}
        report["stop_reason"] = None
        runner.write_json(value("--output"), report)
        return SimpleNamespace(returncode=0)
    assert runner.resume(frozen, execute=fake_execute) == 2
    assert received == pytest.approx([1, .4])
    result = progress(frozen)
    assert result["additional_budget_usage"]["cost_charged_for_limit"] == pytest.approx(1)
    assert result["completed_by_group"] == {"A": 4, "B": 1, "C": 1, "D": 1}
    assert runner.resume(frozen, execute=fake_execute) == 2
    assert len(received) == 2  # 再次运行不重置已经扣减的预算。
    assert runner.read_json(frozen.directory / "A.json")["cost_estimate"] is None


def test_unsettled_attempt_blocks_further_requests(monkeypatch, frozen):
    runner.resume(frozen)
    result = progress(frozen)
    result["inflight"] = {"report": "unsettled.json"}
    runner.write_json(frozen.output_directory / "resume-progress.json", result)
    frozen.live = True
    with pytest.raises(RuntimeError, match="未结算批次"):
        runner.resume(frozen, execute=lambda *a, **kw: pytest.fail("未结算时不得继续调用"))


def test_missing_final_budget_stops_and_preserves_inflight(monkeypatch, frozen):
    configure_offline_live(monkeypatch)
    frozen.live = True
    calls = []
    def interrupted(command, **kwargs):
        calls.append(command)
        runner.write_json(command[command.index("--output") + 1], {"status": "running"})
        return SimpleNamespace(returncode=2)
    with pytest.raises(RuntimeError, match="最终费用记录"):
        runner.resume(frozen, execute=interrupted)
    assert len(calls) == 1 and progress(frozen)["inflight"]
    with pytest.raises(RuntimeError, match="未结算批次"):
        runner.resume(frozen, execute=interrupted)
    assert len(calls) == 1


def test_source_report_tampering_rejected_after_plan(frozen):
    runner.resume(frozen)
    path = frozen.directory / "A.json"
    report = runner.read_json(path)
    report["unknown_usage_calls"] = 0
    runner.write_json(path, report)
    with pytest.raises(RuntimeError, match="冻结报告发生变化"):
        runner.resume(frozen)


def test_provider_blocker_halts_all_groups_and_preserves_unknown_cost(monkeypatch, frozen):
    configure_offline_live(monkeypatch)
    frozen.live = True
    count = []
    def blocked(command, **kwargs):
        count.append(1)
        value = lambda flag: command[command.index(flag) + 1]
        report = runner.read_json(frozen.directory / f'{value("--group")}.json')
        report.update(parameters={**report["parameters"], "repeats": 1},
                      scheduled_tasks=len(value("--case").split(",")), finished_tasks=0,
                      results=[row(value("--case").split(",")[0], 0, False, False)],
                      stop_reason="服务商账户或配置不可用: Arrearage",
                      evaluation_budget={"requests": 1, "tokens_charged_for_limit": 8,
                                         "cost_charged_for_limit": .1, "unknown_calls": 1})
        runner.write_json(value("--output"), report)
        return SimpleNamespace(returncode=2)
    assert runner.resume(frozen, execute=blocked) == 2
    assert len(count) == 1
    result = progress(frozen)
    assert "Arrearage" in result["stop_reason"]
    assert result["additional_budget_usage"]["cost_charged_for_limit"] == pytest.approx(.1)
    assert runner.read_json(result["attempts"][0]["report"])["cost_estimate"] is None
    assert result["release_allowed"] is False


def test_runtime_price_change_blocks_new_paid_calls(monkeypatch, frozen):
    configure_offline_live(monkeypatch)
    runner.resume(frozen)
    result = progress(frozen)
    result["resume_runtime_identity"] = {"fixture": "changed"}
    runner.write_json(frozen.output_directory / "resume-progress.json", result)
    frozen.live = True
    with pytest.raises(RuntimeError, match="计价或校准文件发生变化"):
        runner.resume(frozen, execute=lambda *a, **kw: pytest.fail("条件变化不能继续调用"))


def test_merge_keeps_interrupted_unknown_usage_and_completed_negative_outcomes(frozen):
    from eval.merge_context_resume import merge
    for group in "ABCD":
        path = frozen.directory / f"{group}.json"
        report = runner.read_json(path)
        for sample in report["results"]:
            sample.update(constraints=dict.fromkeys(("language", "version", "dependency", "task_id"), sample["task_pass"]),
                          evidence_checks=[], ordinary_checks=[])
            for turn in sample["turns"]:
                known = sample["completed"]
                turn.update(elapsed_ms=10, steps=[], context_stats={"calls": [{"stage": "planning", "input_estimate": 20,
                    "usage": {"input_tokens": 10, "output_tokens": 1, "total_tokens": 11} if known else None}],
                    "cost_estimate": .01 if known else None, "uncached_cost_estimate": .01 if known else None, "currency": "CNY"})
        runner.write_json(path, report)
    runner.resume(frozen)
    manifest = progress(frozen)
    reports, cases = runner.load_frozen(frozen.directory, frozen.dataset)
    extra = deepcopy(reports["A"])
    extra.update(parameters={**extra["parameters"], "repeats": 1}, scheduled_tasks=1, finished_tasks=1,
                 results=[deepcopy(extra["results"][0])], evaluation_budget={"requests": 2,
                    "tokens_charged_for_limit": 22, "cost_charged_for_limit": .02})
    extra["results"][0]["task_pass"] = True
    extra["results"][0]["constraints"] = dict.fromkeys(extra["results"][0]["constraints"], True)
    path = frozen.output_directory / "new.json"
    runner.write_json(path, extra)
    manifest["attempts"] = [{"group": "A", "repeat": 1, "cases": ["one"], "report": str(path), "sha256": runner.digest(path)}]
    result = merge(manifest, reports, cases)["A"]
    # 中断尝试即使用量未知也不能从总量中删除；终局结果单独按唯一任务汇总。
    assert result["model_calls"] == 5 and result["unknown_usage_calls"] == 1
    assert result["input_tokens"] == 40 and result["cost_estimate"] is None
    assert result["latest_task_turn_metrics"]["unknown_usage_calls"] == 0
    assert result["latest_task_turn_metrics"]["cost_estimate"] == pytest.approx(.04)
    assert result["finished_tasks"] == 2 and result["task_completion_rate"] == .5
    assert result["results"][0]["task_pass"] is False
    assert result["attempted_tasks_including_interrupted"] == 3
    assert result["stop_reason"] == "续跑尚未完成"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="续跑报告已变化"):
        merge(manifest, reports, cases)
