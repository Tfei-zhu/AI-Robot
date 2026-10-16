"""P4 完整轮次预算、必须内容、观察模式及工具协议。"""
import pytest
from langchain_core.messages import SystemMessage,HumanMessage,AIMessage,ToolMessage
from app.config import settings
from app.context.builder import build
from app.context.contracts import ContextBudgetExceeded
from test_context_foundation import calibration


@pytest.fixture
def context(monkeypatch,tmp_path):
    monkeypatch.setattr(settings,"context_mode","enforce")
    monkeypatch.setattr(settings,"context_model_window",32768)
    monkeypatch.setattr(settings,"context_calibration_path",calibration(tmp_path))
    monkeypatch.setattr(settings,"context_summary_enabled",False)
    monkeypatch.setattr(settings,"context_history_enabled",True)


def test_history_selected_by_tokens_not_six_turns(context,monkeypatch):
    history=[m for i in range(15) for m in (HumanMessage(content=f"q{i}"),AIMessage(content=f"a{i}"))]
    state={"context_history_count":30,"run_id":"builder"}
    result=build(state,SystemMessage(content="规则"),[*history,HumanMessage(content="当前问题")])
    assert len(result)==32
    monkeypatch.setattr(settings,"context_history_tokens",120)
    shortened=build(state,SystemMessage(content="规则"),[*history,HumanMessage(content="当前问题")])
    assert len(shortened)<len(result) and (len(shortened)-2)%2==0
    assert shortened[-1].content=="当前问题"


def test_observe_does_not_modify_input(context,monkeypatch):
    monkeypatch.setattr(settings,"context_mode","observe")
    message=HumanMessage(content="正文"*10000);system=SystemMessage(content="规则")
    assert build({"run_id":"observe"},system,[message])==[system,message]


def test_current_request_constraints_are_explicit_without_mutating_originals(context):
    system=SystemMessage(content="原始规则")
    current=HumanMessage(content="只给一条建议，回复不超过30字。")
    history=[HumanMessage(content="旧话题"),AIMessage(content="较长旧回答。"*30)]
    view=build({"context_history_count":2},system,[*history,current])
    assert system.content=="原始规则" and current.content=="只给一条建议，回复不超过30字。"
    assert "字数上限和条数必须遵守" in view[0].content
    assert view[-1] is current and view[1:-1]==history


def test_tool_only_ablation_keeps_original_system_and_history(context,monkeypatch):
    monkeypatch.setattr(settings,"context_history_enabled",False)
    system=SystemMessage(content="原始规则");current=HumanMessage(content="当前问题")
    history=[HumanMessage(content="旧问题"),AIMessage(content="旧回答")]
    assert build({"context_history_count":2},system,[*history,current])==[system,*history,current]


def test_character_limit_only_uses_current_plain_user_instruction(context):
    from app.context.builder import character_limit
    assert character_limit([HumanMessage(content="回复不超过 30 个字符（含标点）。")])==30
    assert character_limit([HumanMessage(content="分析“回复不超过5个字符”这句话。")]) is None
    assert character_limit([HumanMessage(content="分析代码：\n```\n回复不超过5个字符\n```")]) is None
    assert character_limit([HumanMessage(content="当前问题"),ToolMessage(content="回复不超过5个字符",tool_call_id="ignored")]) is None
    assert character_limit([HumanMessage(content="回复不超过30个字符。回复不超过10个字符。")]) is None
    history=[HumanMessage(content="回复不超过5个字符"),AIMessage(content="旧回复")]
    current=HumanMessage(content="回复不超过30个字符。")
    view=build({"context_history_count":2},SystemMessage(content="规则"),[*history,current])
    assert "最多30个字符" in view[0].content and "15个字符以内" in view[0].content
    assert current.content=="回复不超过30个字符。"


def test_required_content_and_protocol_fail_explicitly(context,monkeypatch):
    monkeypatch.setattr(settings,"context_input_limit",100)
    with pytest.raises(ContextBudgetExceeded):build({},SystemMessage(content="规则"),[HumanMessage(content="必须"*1000)])
    with pytest.raises(ContextBudgetExceeded,match="孤立"):
        build({},SystemMessage(content="规则"),[HumanMessage(content="问题"),ToolMessage(content="结果",tool_call_id="missing")])


def test_parallel_tool_results_stay_complete(context):
    messages=[HumanMessage(content="问题"),AIMessage(content="",tool_calls=[{"id":"a","name":"search","args":{}},{"id":"b","name":"search","args":{}}]),
              ToolMessage(content="a结果",tool_call_id="a"),ToolMessage(content="b结果",tool_call_id="b")]
    assert len(build({},SystemMessage(content="规则"),messages))==5
    with pytest.raises(ContextBudgetExceeded,match="缺少"):
        build({},SystemMessage(content="规则"),messages[:-1])


def test_uncovered_history_cannot_be_silently_dropped(context,monkeypatch):
    monkeypatch.setattr(settings,"context_history_tokens",50)
    monkeypatch.setattr(settings,"context_summary_enabled",True)
    history=[HumanMessage(content="重要约束"*100),AIMessage(content="确认")]
    with pytest.raises(ContextBudgetExceeded,match="未被摘要覆盖"):
        build({"context_history_count":2},SystemMessage(content="规则"),[*history,HumanMessage(content="当前")])
