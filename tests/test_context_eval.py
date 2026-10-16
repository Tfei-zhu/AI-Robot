"""评测门禁不能把少量样本或未运行的样本当最终通过。"""
from eval.compare_context_eval import compare


def test_partial_matrix_never_allows_release():
    row={"id":"one","repeat":0,"completed":True,"task_pass":True,"split":"dev","length":10,"turns":[]}
    base={"results":[row],"stop_reason":None,"dataset_sha256":"same","source_sha256":{},"finished_tasks":1,
          "constraint_retention_rate":1,"unknown_usage_calls":0,"turn_p95_ms":1,"cost_estimate":0.1}
    result=compare({g:dict(base) for g in "ABCD"})
    assert result["release_allowed"] is False
    assert result["gates"]["complete_30_scripts_times_3"] is False
    assert result["gates"]["holdout_quality"] is False
    assert result["long_input_saving"] is None and result["paired_task_difference_95_ci"] is None
    assert result["gates"]["cost_not_increased"] is False


def test_grading_accepts_equivalent_language_not_third_party():
    from eval.run_context_eval import matches
    assert matches("dependency","standard library only","标准库")
    assert matches("dependency","仅使用标准库","标准库")
    assert not matches("dependency",["zap","testify"],"标准库")
    assert not matches("task_id","CTX-02","CTX-01")


def test_summary_ablation_cannot_hide_shared_code_or_guard_changes(tmp_path):
    from eval.compare_context_eval import summary_source_equivalence
    old='''value=1
def discard(run_id):return value
async def prepare(state,model=None):
    if not state:return state
    return {"old":True}
'''
    new=old.replace('{"old":True}','normalize(state)')+'\ndef normalize(data):return data\n'
    a,b=tmp_path/"old.py",tmp_path/"new.py"
    a.write_text(old,encoding="utf-8");b.write_text(new,encoding="utf-8")
    assert summary_source_equivalence(a,b)["shared_paths_unchanged"]
    b.write_text(new.replace('return value','return 0'),encoding="utf-8")
    assert not summary_source_equivalence(a,b)["shared_paths_unchanged"]
    b.write_text(new.replace('if not state','if state'),encoding="utf-8")
    assert not summary_source_equivalence(a,b)["shared_paths_unchanged"]


def test_provider_account_error_stops_evaluation_without_copying_secrets():
    from eval.run_context_eval import provider_blocker
    exc=RuntimeError("sensitive details")
    exc.body={"error":{"code":"Arrearage","message":"sensitive details"}}
    exc.status_code=400
    assert provider_blocker(exc)=={"code":"Arrearage","http_status":400}
    exc.body={"error":{"code":"InvalidParameter"}}
    assert provider_blocker(exc) is None
    exc.status_code=401
    assert provider_blocker(exc)=={"code":"InvalidParameter","http_status":401}


def test_frozen_dataset_has_complete_scripts_and_explicit_character_rule():
    import json
    from pathlib import Path
    cases=[json.loads(line) for line in (Path(__file__).resolve().parents[1]/"eval/context_cases.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(cases)==len({c["id"] for c in cases})==30
    assert sum(c["split"]=="dev" for c in cases)==20
    assert sum(c["split"]=="holdout" for c in cases)==10
    for case in cases:
        assert len(case["turns"])==case["length"] and case["length"] in {10,30,60}
        assert case["ordinary_constraint"]["max_characters"]==30
        assert case["ordinary_turns"] and len(case["ordinary_turns"])==len(set(case["ordinary_turns"]))
        assert all("30个字符" in case["turns"][i-1].replace(" ","") for i in case["ordinary_turns"])


def test_ordinary_grading_is_independent_and_does_not_accept_empty_answers():
    from eval.run_context_eval import ordinary_checks_for
    case={"ordinary_turns":[2,3,4],"ordinary_constraint":{"max_characters":3}}
    turns=[{"turn":1,"reply":"非评分轮次长回复"},{"turn":2,"reply":" 甲乙丙 "},
           {"turn":3,"reply":"A B。"},{"turn":4,"reply":""}]
    assert ordinary_checks_for(case,turns)==[True,False,False]


def test_filtered_out_case_is_rejected_before_any_model_call(monkeypatch):
    import asyncio
    import argparse
    import pytest
    from app.config import settings
    from eval.run_context_eval import evaluate
    monkeypatch.setattr(settings,"llm_api_key","fixture")
    args=argparse.Namespace(live=True,dataset="eval/context_cases_v2.jsonl",split="dev",case="context-25",limit=0)
    with pytest.raises(RuntimeError,match="核对--split和--case"):
        asyncio.run(evaluate(args))


def test_resume_saving_includes_interrupted_attempt_inputs():
    from copy import deepcopy
    rows = [{"id": f"context-{i:02d}", "repeat": repeat, "completed": True, "task_pass": True,
             "split": "holdout" if i >= 20 else "dev", "length": 30,
             "turns": [{"elapsed_ms": 1, "context_stats": {"calls": [{"stage": "planning", "elapsed_ms": 1,
                 "usage": {"input_tokens": 10, "output_tokens": 0, "total_tokens": 10}}]}}]}
            for i in range(30) for repeat in range(3)]
    report = {"results": rows, "stop_reason": None, "dataset_sha256": "same", "source_sha256": {},
              "finished_tasks": 90, "constraint_retention_rate": 1, "evidence_retention_rate": 1,
              "ordinary_constraint_retention_rate": 1, "unknown_usage_calls": 0, "counter_underestimates": 0,
              "turn_p95_ms": 1, "cost_estimate": .1, "long_input_tokens_including_interrupted": 900}
    reports = {g: deepcopy(report) for g in "ABCD"}
    for row in reports["D"]["results"]:
        row["turns"][0]["context_stats"]["calls"][0]["usage"]["input_tokens"] = 5
    # 只看完整任务会显示50%节省，计入中断开销后应显示增加，不能通过门禁。
    reports["D"]["long_input_tokens_including_interrupted"] = 1000
    result = compare(reports)
    assert result["comparisons_valid"] is True
    assert result["long_input_saving"] < 0
    assert result["gates"]["long_input_saving_20_percent"] is False
