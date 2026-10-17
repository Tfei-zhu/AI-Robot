"""S8 evaluation validity and cost guards. No paid model calls; Docker is explicit."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.go_validation.contracts import StageReport,ValidationReport,artifact_hash
from eval.go_fixtures import output
from eval.multi_agent_protocol import (ARMS,CostLedger,aggregate,freeze,load_freeze,live_preflight,
    positive_decimal,valid_usage,validate_cases,write_json)
from eval.multi_agent_scoring import label,score,scoring_bundle
from eval.run_multi_agent_eval import TrackingModel,run_trial,audit_rows,evaluate

ROOT=Path(__file__).resolve().parents[1]


def dev_case(index=0):
    return [json.loads(line) for line in (ROOT/"eval/multi_agent_cases.jsonl").read_text().splitlines()
            if json.loads(line)["split"]=="dev"][index]


def test_frozen_splits_and_native_vs_equal_limits():
    rows=[json.loads(line) for line in (ROOT/"eval/multi_agent_cases.jsonl").read_text().splitlines()]
    validate_cases(rows)
    assert len({r["group_id"] for r in rows})==30
    assert not {r["id"] for r in rows if r["split"]=="dev"}&{r["id"] for r in rows if r["split"]=="holdout"}
    assert [ARMS[k]["max_calls"] for k in ARMS]==[3,8,3,3]
    a,b=ARMS["single_equal3"],ARMS["multi_equal3"]
    assert all(a[k]==b[k] for k in ("max_calls","call_seconds","code_output","supervisor_output"))


def test_freeze_rejects_changes_and_overwrite(tmp_path):
    frozen=freeze(tmp_path/"freeze","test-image")
    assert load_freeze(tmp_path/"freeze")==frozen
    with pytest.raises(FileExistsError):freeze(tmp_path/"freeze","test-image")
    frozen["cases"][0]["split"]="holdout"
    write_json(tmp_path/"freeze/freeze.json",frozen)
    with pytest.raises(ValueError,match="altered"):load_freeze(tmp_path/"freeze")


@pytest.mark.parametrize("cap",[None,0,-1,"NaN","Infinity",True])
def test_illegal_cost_caps_are_rejected(cap):
    with pytest.raises(ValueError):positive_decimal(cap)


def test_durable_cost_guard_unknown_never_refunds_and_restarts_cannot_reset(tmp_path):
    rates=dict(input_ceiling_per_million="1",output_ceiling_per_million="2")
    path=tmp_path/"budget.json"
    ledger=CostLedger(path,"2","CNY",rates,"model-v1")
    first=ledger.reserve(1000000,0,"first")
    ledger.finish(first,None)
    second=CostLedger(path,"2","CNY",rates,"model-v1").reserve(1000000,0,"second")
    with pytest.raises(RuntimeError):ledger.reserve(1000000,0,"third")
    ledger.finish(second,None)
    rows=json.loads(path.read_text())["requests"]
    assert [r["actual_estimate"] for r in rows]==[None,None]
    assert sum(float(r["charged_reserve"]) for r in rows)==2
    with pytest.raises(ValueError):CostLedger(path,"3","CNY",rates,"model-v1")
    with pytest.raises(ValueError):ledger.finish(first,None)


def test_concurrent_requests_reserve_before_send(tmp_path):
    path=tmp_path/"budget.json";rates=dict(input_ceiling_per_million="1",output_ceiling_per_million="2")
    CostLedger(path,"2","CNY",rates,"same-model")
    def request(_):
        ledger=CostLedger(path,"2","CNY",rates,"same-model")
        try:return ledger.reserve(1000000,0,"concurrent")
        except RuntimeError:return None
    with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(request,range(12)))
    assert sum(r is not None for r in results)==2
    assert len(json.loads(path.read_text())["requests"])==2


def test_live_preflight_blocks_missing_cap_alias_unknown_prices(tmp_path):
    frozen=freeze(tmp_path/"frozen","test-image")
    problems=live_preflight(frozen)
    assert any("累计费用" in p for p in problems)
    assert any("别名" in p for p in problems)
    assert any("单价" in p for p in problems)


def test_tracking_guard_blocks_before_underlying_client_and_keeps_failure(tmp_path):
    async def run():
        model=SimpleNamespace(ainvoke=AsyncMock(side_effect=RuntimeError("actual failure")))
        state=dict(calls=[],trial_id="trial")
        tracker=TrackingModel(model,"single",state,tmp_path,dict(ARMS["single_equal3"],max_calls=1))
        with pytest.raises(RuntimeError,match="actual failure"):await tracker.ainvoke([])
        with pytest.raises(RuntimeError,match="cap exhausted"):await tracker.ainvoke([])
        assert model.ainvoke.await_count==1
        assert state["calls"][0]["status"]=="failed" and state["calls"][0]["usage"] is None
        assert json.loads((tmp_path/"call-01.json").read_text())["error"].endswith("actual failure")
    asyncio.run(run())


def test_cost_guard_blocks_before_underlying_client(tmp_path):
    async def run():
        ledger=CostLedger(tmp_path/"budget.json","0.01","CNY",dict(input_ceiling_per_million="1000",output_ceiling_per_million="1000"),"model")
        model=SimpleNamespace(ainvoke=AsyncMock())
        state=dict(calls=[],trial_id="blocked")
        tracker=TrackingModel(model,"code",state,tmp_path,ARMS["multi_native"],cost_ledger=ledger)
        with pytest.raises(RuntimeError,match="budget exhausted"):await tracker.ainvoke([])
        assert model.ainvoke.await_count==0 and state["calls"]==[]
    asyncio.run(run())


def test_matched_input_cap_and_version_mismatch_block_later_requests(tmp_path):
    async def run():
        from langchain_core.messages import AIMessage,HumanMessage
        model=SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content="ok",response_metadata={"model_name":"wrong-version"})))
        state=dict(calls=[],trial_id="guard")
        tracker=TrackingModel(model,"single",state,tmp_path,ARMS["single_equal3"],input_limit=1)
        with pytest.raises(RuntimeError,match="input estimate"):await tracker.ainvoke([HumanMessage(content="long input"*100)])
        assert model.ainvoke.await_count==0
        tracker.input_limit=None;tracker.expected_revision="frozen-version"
        await tracker.ainvoke([])
        with pytest.raises(RuntimeError,match="already stopped"):await tracker.ainvoke([])
        assert model.ainvoke.await_count==1 and state["evaluation_stop"]=="model_version_unverified"
    asyncio.run(run())


def test_independent_labels_do_not_accept_approve_or_missing_test_events():
    case=dev_case()
    report=ValidationReport(status="passed",container_removed=True,stages=[
        StageReport(stage=s,exit_code=0,output='{"Action":"pass","Test":"TestEvalContextIdentity"}' if s=="test" else "ok")
        for s in ("policy","compile","vet","test")])
    verdict=label(case,report)
    assert verdict["correct"] is None  # Missing independent test evidence stays unknown.
    assert verdict["checks"][1]["status"]=="unknown"
    failed=report.model_copy(update={"status":"failed"})
    assert label(case,failed)["correct"] is False
    assert label(case,None)["correct"] is None


def test_scoring_removes_model_tests_and_injects_independent_probes():
    case=dev_case(4)
    bundle=output(case["scenario"]).bundle
    bundle.files[1].content='package example\n// all tests removed by malicious model'
    scored=scoring_bundle(case,bundle)
    assert not any(f.name=="solution_test.go" for f in scored.files)
    assert {f.name for f in scored.files}>={"server_acceptance_test.go","eval_independent_test.go","eval_requirements_test.go"}
    assert artifact_hash(scored.files)!=artifact_hash(bundle.files)


def test_unknown_usage_and_nonzero_failure_denominators():
    assert valid_usage(SimpleNamespace(usage_metadata={"input_tokens":1})) is None
    assert valid_usage(SimpleNamespace(usage_metadata={"input_tokens":1,"output_tokens":2,"total_tokens":4})) is None
    row=dict(arm="single_native",feasible=True,business_status="passed",stop_reason="passed",
        independent=dict(correct=False,checks=[dict(status="fail")]),initial_independent=dict(correct=False),
        calls=[dict(role="single",usage=None)],generation_ms=100,scoring_ms=50,cost_estimate=None)
    stats=aggregate([row])["single_native"]
    assert stats["independent_success_rate"]==0 and stats["false_accepts"]==stats["false_accept_denominator"]==1
    assert stats["total_tokens"] is stats["cost_estimate"] is None
    assert stats["unknown_usage_calls"]==1 and stats["repair_success_rate"]==0


def test_live_missing_authorization_rejects_before_clients_or_holdout_marker(tmp_path,monkeypatch):
    frozen=freeze(tmp_path/"freeze","test-image")
    import eval.run_multi_agent_eval as runner
    image=AsyncMock(side_effect=AssertionError("must not inspect image before auth"))
    monkeypatch.setattr(runner,"image_id",image)
    args=SimpleNamespace(mode="live",split="holdout",cost_cap=None,cost_ledger=None,
                         rerun_of=None,reason=None,freeze=str(tmp_path/"freeze"))
    with pytest.raises(ValueError,match="累计费用"):asyncio.run(evaluate(args,frozen))
    assert not (tmp_path/"freeze/holdout-started-live.json").exists()
    image.assert_not_called()


def test_crashed_pending_trial_is_preserved_as_unknown_not_zero(tmp_path):
    frozen=freeze(tmp_path/"freeze","test-image")
    folder=tmp_path/"results/crashed";folder.mkdir(parents=True)
    raw=dict(trial_id="crashed",case_id=dev_case()["id"],arm="single_native",state="started",calls=[])
    write_json(folder/"trial.json",raw,exclusive=True)
    rows=audit_rows(tmp_path/"results",frozen)
    stats=aggregate(rows)["single_native"]
    assert stats["unverified_runs"]==1
    assert stats["model_calls"] is stats["total_tokens"] is stats["cost_estimate"] is None
    assert json.loads((folder/"trial.json").read_text())==raw


@pytest.mark.parametrize("stop",["cancel","timeout"])
def test_controlled_interrupts_preserve_actual_calls_and_report(tmp_path,stop):
    async def run():
        frozen=freeze(tmp_path/"freeze","test-image")
        row=await run_trial(dev_case(),"single_equal3",frozen,tmp_path/"trial",inject=stop)
        assert row["business_status"]==("cancelled" if stop=="cancel" else "timeout")
        assert row["actual_client_calls"]==1 and row["calls"][0]["status"]=="cancelled"
        assert row["independent"]["correct"] is None
        assert (tmp_path/"trial/result.json").exists() and (tmp_path/"trial/reports.sqlite3").exists()
    asyncio.run(run())


@pytest.mark.skipif(os.environ.get("AIROBOT_TEST_DOCKER")!="1",reason="S8 real independent Docker scorer")
@pytest.mark.parametrize("index",[0,6,12])
def test_real_independent_base_probes_execute_for_each_scenario(index):
    async def run():
        case=dev_case(index)
        checked=await score(case,output(case["scenario"]).bundle)
        assert checked["correct"] is True,checked
        assert all(c["status"]=="pass" for c in checked["checks"])
        assert checked["report"]["container_removed"]
    asyncio.run(run())


@pytest.mark.skipif(os.environ.get("AIROBOT_TEST_DOCKER")!="1",reason="S8 real independent Docker scorer")
def test_real_independent_doc_check_rejects_correct_behavior_without_required_comment():
    async def run():
        case=dev_case(4);bundle=output(case["scenario"]).bundle
        first=await score(case,bundle)
        assert first["correct"] is False
        assert next(c for c in first["checks"] if c["id"]=="r-doc")["status"]=="fail"
        bundle.files[0].content=bundle.files[0].content.replace("func WaitForCancel","// "+case["marker"]+"\nfunc WaitForCancel")
        final=await score(case,bundle)
        assert final["correct"] is True
        assert final["artifact_hash"]!=first["artifact_hash"]
        assert final["report"]["container_removed"]
    asyncio.run(run())
