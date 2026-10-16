"""P1 原始历史、隔离、幂等、摘要版本与计量边界。"""
import hashlib
import json
import pytest
from langchain_core.messages import HumanMessage,AIMessage
from app.config import settings
from app.context.store import ContextStore
from app.context.token_counter import TokenCounter,validate_config,SERIALIZER_VERSION
from app.context.budget import check
from app.context.contracts import ContextBudgetExceeded


def test_history_recovery_idempotency_and_scope(tmp_path):
    path=tmp_path/"context.sqlite3";store=ContextStore(path)
    for i in range(25):store.commit("a","s",f"run-{i}",f"user-{i}",f"ai-{i}")
    assert store.commit("a","s","run-24","different","different")==25
    assert len(store.turns("a","s"))==25 and store.turns("b","s")==[]
    result_id=store.save_result("a","s","run-24",{"answer":"完整结果"})
    assert store.result("b","s",result_id) is None and store.result("a","other",result_id) is None
    store.close();reopened=ContextStore(path)
    assert reopened.turns("a","s")[-1]["assistant"]=="ai-24"
    assert reopened.result("a","s",result_id)["answer"]=="完整结果"
    reopened.close()


def test_summary_version_and_atomic_turn_commit():
    store=ContextStore(":memory:");store.commit("a","s","r1","约束","已记录")
    summary={"version":1,"covered_until_turn":1,"constraints":[{"text":"约束","source_turns":[1]}]}
    with pytest.raises(ValueError):store.commit("a","s","r2","q","a",summary,expected_version=4)
    assert len(store.turns("a","s"))==1 and store.summary("a","s") is None
    store.commit("a","s","r2","q","a",summary,expected_version=0)
    assert store.summary("a","s")["covered_until_turn"]==1
    bad={**summary,"version":2,"covered_until_turn":2,"constraints":[{"text":"x","source_turns":[3]}]}
    with pytest.raises(ValueError):store.commit("a","s","r3","q","a",bad,expected_version=1)
    assert len(store.turns("a","s"))==2
    assert len(store.summary_versions("a","s"))==1
    second={**summary,"version":2,"covered_until_turn":2}
    store.commit("a","s","r3","q","a",second,expected_version=1)
    assert [s["version"] for s in store.summary_versions("a","s")]==[1,2]
    assert store.summary_versions("b","s")==[]
    store.clear("a","s")
    assert store.summary_versions("a","s")==[]
    store.close()


def test_legacy_import_is_once():
    store=ContextStore(":memory:");messages=[HumanMessage(content="q"),AIMessage(content="a")]
    store.import_legacy("a","s",messages);store.import_legacy("a","s",messages)
    assert len(store.turns("a","s"))==1;store.close()


def test_existing_summary_is_archived_on_database_upgrade(tmp_path):
    import sqlite3
    path=tmp_path/"previous.sqlite3"
    payload={"version":4,"covered_until_turn":8,"constraints":[]}
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE context_summaries(owner TEXT,sid TEXT,version INTEGER,covered INTEGER,payload TEXT,PRIMARY KEY(owner,sid))")
        db.execute("INSERT INTO context_summaries VALUES(?,?,?,?,?)",("a","s",4,8,json.dumps(payload)))
    store=ContextStore(path)
    assert store.summary_versions("a","s")==[payload]
    store.close()
    reopened=ContextStore(path)
    assert reopened.summary_versions("a","s")==[payload]
    assert reopened.summary_versions("a","other")==[]
    reopened.close()


def calibration(tmp_path):
    data={"model":settings.llm_model,"endpoint_sha256":hashlib.sha256(settings.llm_base_url.encode()).hexdigest(),
          "encoding":"cl100k_base","serializer":SERIALIZER_VERSION,"samples":20,"factor":1.1,"validated":True}
    p=tmp_path/"counter.json";p.write_text(json.dumps(data),encoding="utf-8");return str(p)


def test_unknown_model_not_allowed_in_enforce(monkeypatch):
    monkeypatch.setattr(settings,"context_mode","observe");validate_config()
    monkeypatch.setattr(settings,"context_mode","enforce")
    monkeypatch.setattr(settings,"context_model_window",32768)
    monkeypatch.setattr(settings,"context_calibration_path","")
    with pytest.raises(ValueError,match="校准"):validate_config()


def test_count_includes_tool_schema_and_budget(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"context_calibration_path",calibration(tmp_path))
    monkeypatch.setattr(settings,"context_model_window",32768)
    monkeypatch.setattr(settings,"context_mode","enforce")
    validate_config();counter=TokenCounter()
    messages=[HumanMessage(content="中文 Go 代码 <|endoftext|>")]
    schema={"type":"function","function":{"name":"read","description":"read evidence","parameters":{"type":"object","properties":{}}}}
    assert counter.count(messages,[schema])>counter.count(messages)
    monkeypatch.setattr(settings,"context_input_limit",10)
    with pytest.raises(ContextBudgetExceeded):check(messages)
    monkeypatch.setattr(settings,"context_mode","observe")
    assert check(messages)["input_estimate"]>10


def test_missing_calibration_does_not_break_off(monkeypatch,tmp_path):
    monkeypatch.setattr(settings,"context_mode","off")
    monkeypatch.setattr(settings,"context_calibration_path",str(tmp_path/"missing.json"))
    assert TokenCounter().verified is False
    assert TokenCounter().count([HumanMessage(content="正常请求")])>0
