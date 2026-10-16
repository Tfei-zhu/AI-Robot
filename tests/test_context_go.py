"""P6 Go 源码不能为节省上下文而被截断，日志可精简。"""
import json
import pytest
from app.config import settings
from app.context.go_adapter import messages
from app.context.contracts import ContextBudgetExceeded
from test_context_foundation import calibration


def test_go_source_preserved_and_logs_compacted(monkeypatch,tmp_path):
    monkeypatch.setattr(settings,"context_mode","enforce")
    monkeypatch.setattr(settings,"context_model_window",32768)
    monkeypatch.setattr(settings,"context_calibration_path",calibration(tmp_path))
    source="package example\nfunc Example(){}"
    data={"requirement":"固定接口","server_contract":"原始接口", "previous_attempt":{"bundle":{"files":[{"name":"solution.go","content":source}]},
        "validation":{"stages":[{"stage":"compile","exit_code":0,"output":"成功"*1000},
                                  {"stage":"test","exit_code":1,"output":json.dumps({"Output":"solution_test.go:12: 必须返回取消错误"})}]}}}
    result=messages({"run_id":"go-budget"},"系统规则",data,8192)
    parsed=json.loads(result[-1].content)
    assert parsed["previous_attempt"]["bundle"]["files"][0]["content"]==source
    assert parsed["server_contract"]==data["server_contract"]
    assert "solution_test.go:12" in parsed["previous_attempt"]["validation"]["stages"][1]["output"]
    monkeypatch.setattr(settings,"context_input_limit",10)
    with pytest.raises(ContextBudgetExceeded):messages({"run_id":"go-budget"},"系统规则",data,8192)
