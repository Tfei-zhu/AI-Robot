"""S2 角色组件测试：固定模型验证计划/审查/生成/修复的消息内容、服务端锚定与任务隔离。

ScriptedModel 捕获每次调用实际收到的消息；断言基于真实输入而非组件自述。
验证报告与审查均为替身，不代表真实模型能力或 Docker 证据。
"""
import asyncio
import json
import unittest

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agents.code_agent import CODE_SYSTEM, CodeAgent
from app.agents.role_runtime import AgentError
from app.agents.supervisor import PLAN_SYSTEM, REVIEW_SYSTEM, SupervisorAgent
from app.config import GoMultiAgentSettings, settings
from app.go_validation.contracts import (
    SCENARIO_SPECS, GoTaskRequest, RepairRequest, artifact_hash,
)
from app.go_validation.fixtures import ACCEPTANCE_FILE, ACCEPTANCE_TESTS
from multi_agent_fixtures import artifact, budget, issue, review, task, validation


class ScriptedModel:
    """记录实际收到的消息并按脚本回复；不访问网络。"""

    model_name = "scripted-fixture"

    def __init__(self, *replies):
        self.replies, self.inputs = list(replies), []

    async def ainvoke(self, messages, *args, **kwargs):
        self.inputs.append(list(messages))
        if not self.replies:
            raise AssertionError("没有预置回复")
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return AIMessage(content=reply,
                         usage_metadata={"input_tokens": 12, "output_tokens": 34, "total_tokens": 46})


class SlowModel:
    model_name = "slow-fixture"

    async def ainvoke(self, messages, *args, **kwargs):
        await asyncio.sleep(0.3)
        return AIMessage(content="{}")


def fenced(*files, change="CHANGE: 默认改动说明"):
    parts = [f"=== FILE: {name} ===\n```go\n{content}\n```" for name, content in files]
    return "\n".join(parts) + "\n" + change


def plan_json(**overrides):
    data = {"requirements": [{"requirement_id": "r-cancel", "text": "传播取消错误", "required": True},
                             {"requirement_id": "r-wait", "text": "取消前不能返回", "required": True}],
            "acceptance_criteria": [{"criterion_id": "a-cancel", "requirement_id": "r-cancel",
                                     "text": "取消后返回 ctx.Err()"},
                                    {"criterion_id": "a-wait", "requirement_id": "r-wait",
                                     "text": "取消前保持等待"}],
            "constraints": ["仅标准库"], "source_refs": []}
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def plan_json_channel():
    return plan_json(requirements=[{"requirement_id": "r-sum", "text": "关闭后返回总和", "required": True}],
                     acceptance_criteria=[{"criterion_id": "a-sum", "requirement_id": "r-sum",
                                           "text": "求和结果正确"}])


def review_json_channel():
    return review_json(requirement_checks=[
        {"requirement_id": "r-sum", "status": "pass", "evidence": "solution.go:6 循环求和后返回"}])


def review_json(**overrides):
    data = {"verdict": "approve",
            "requirement_checks": [
                {"requirement_id": "r-cancel", "status": "pass", "evidence": "solution.go:4 返回 ctx.Err()"},
                {"requirement_id": "r-wait", "status": "pass", "evidence": "solution.go:4 阻塞等待"}],
            "issues": [], "summary": "符合需求"}
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


SOLUTION_A = 'package example\nimport "context"\nfunc WaitForCancel(ctx context.Context) error { SentinelA(); <-ctx.Done(); return ctx.Err() }\nfunc SentinelA() {}\n'
TEST_A = 'package example\nimport ("context"; "errors"; "testing")\nfunc TestCancel(t *testing.T) { ctx,cancel:=context.WithCancel(context.Background());cancel();if !errors.Is(WaitForCancel(ctx),context.Canceled){t.Fatal("cancel")} }\n'
TEST_A_FIXED = TEST_A.replace('t.Fatal("cancel")', 't.Fatal("cancel-fixed-marker")')
SOLUTION_B = 'package example\nimport "context"\nfunc SumChannel(ctx context.Context, input <-chan int) (int, error) { SentinelB(); sum:=0; for { select { case v,ok:=<-input: if !ok { return sum,nil }; sum+=v; case <-ctx.Done(): return 0,ctx.Err() } } }\nfunc SentinelB() {}\n'
TEST_B = 'package example\nimport ("context"; "testing")\nfunc TestSum(t *testing.T) { ch:=make(chan int,1); ch<-2; close(ch); if s,err:=SumChannel(context.Background(),ch); err!=nil||s!=2 { t.Fatal("sum") } }\n'


def request_of(scenario, requirement):
    return GoTaskRequest(requirement=requirement, scenario=scenario)


class SupervisorPlanTests(unittest.IsolatedAsyncioTestCase):
    async def test_plan_anchors_original_requirement_contract_and_records_usage(self):
        model = ScriptedModel(plan_json())
        agent = SupervisorAgent(model=model)
        request = request_of("context_cancel", "任务A唯一标记a1b2：等待取消并返回 ctx.Err()，取消前不得提前返回")
        spec = await agent.plan(request, references='[{"source": "ref-sentinel-xyz", "content": "资料"}]')
        self.assertEqual(spec.original_requirement, request.requirement)  # 服务端逐字锚定
        self.assertEqual(spec.server_contract, SCENARIO_SPECS["context_cancel"])
        self.assertEqual({r.requirement_id for r in spec.requirements}, {"r-cancel", "r-wait"})
        self.assertIs(spec, agent.task)
        self.assertEqual(len(model.inputs), 1)
        system, human = model.inputs[0]
        self.assertEqual(system.content, PLAN_SYSTEM)  # 主 Agent 计划角色提示词
        self.assertIn(request.requirement, human.content)
        self.assertIn(SCENARIO_SPECS["context_cancel"], human.content)
        self.assertIn("ref-sentinel-xyz", human.content)
        self.assertEqual(agent.calls[0].stage, "plan")
        self.assertEqual(agent.calls[0].status, "passed")
        self.assertEqual(agent.calls[0].token_usage,
                         {"input_tokens": 12, "output_tokens": 34, "total_tokens": 46})

    async def test_plan_rejects_invalid_output_and_records_failed_call(self):
        for bad in ("这不是 JSON", "[]", plan_json(acceptance_criteria=[
                {"criterion_id": "a-x", "requirement_id": "r-ghost", "text": "引用未知需求"}]),
                plan_json(requirements=[])):
            with self.subTest(bad=bad[:30]):
                model = ScriptedModel(bad)
                agent = SupervisorAgent(model=model)
                with self.assertRaises(AgentError) as ctx:
                    await agent.plan(request_of("context_cancel", "等待取消并传播错误的示例需求"))
                self.assertEqual((ctx.exception.kind, ctx.exception.role, ctx.exception.stage),
                                 ("output", "supervisor", "plan"))
                self.assertEqual(agent.calls[0].status, "failed")

    async def test_call_failure_and_timeout_are_distinct_kinds(self):
        agent = SupervisorAgent(model=ScriptedModel(RuntimeError("provider down")))
        with self.assertRaises(AgentError) as ctx:
            await agent.plan(request_of("context_cancel", "等待取消并传播错误的示例需求"))
        self.assertEqual(ctx.exception.kind, "call")
        agent = SupervisorAgent(model=SlowModel(), timeout=0.05)
        with self.assertRaises(AgentError) as ctx:
            await agent.plan(request_of("context_cancel", "等待取消并传播错误的示例需求"))
        self.assertEqual(ctx.exception.kind, "timeout")
        self.assertEqual(agent.calls[0].status, "failed")


class CodeGenerateTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_freezes_server_tests_and_prompt_carries_handoff(self):
        model = ScriptedModel(fenced(("solution.go", SOLUTION_A), ("solution_test.go", TEST_A)))
        agent = CodeAgent(model=model)
        art = await agent.generate(task(), references='[{"source": "gen-ref-77", "content": "资料"}]')
        self.assertEqual(art.round, 0)
        self.assertEqual(art.scenario, task().scenario)
        trusted = [f.content for f in art.files if f.name == ACCEPTANCE_FILE]
        self.assertEqual(trusted, [ACCEPTANCE_TESTS["context_cancel"]])  # 服务端注入原样可信测试
        self.assertEqual(art.artifact_hash, artifact_hash(art.files))  # hash 由服务端对完整产物计算
        self.assertEqual(agent.artifacts, [art])
        self.assertEqual((agent.calls[0].role, agent.calls[0].stage), ("code", "generate"))
        system, human = model.inputs[0]
        self.assertEqual(system.content, CODE_SYSTEM)  # 代码子 Agent 角色提示词
        self.assertIn(task().original_requirement, human.content)  # 原始需求交接
        self.assertIn(SCENARIO_SPECS["context_cancel"], human.content)  # 固定接口交接
        self.assertIn("r-cancel", human.content)  # 计划分解后的需求交接
        self.assertIn("a-cancel", human.content)
        self.assertIn("gen-ref-77", human.content)  # 必要资料交接

    async def test_generate_rejects_model_acceptance_file_and_malformed_output(self):
        outputs = {"提交了服务端测试": fenced(("solution.go", SOLUTION_A), ("solution_test.go", TEST_A),
                                              ("server_acceptance_test.go", "package example\n")),
                   "缺少文件头": "直接给代码，没有文件头",
                   "空文件内容": fenced(("solution.go", "   "))}
        for name, output in outputs.items():
            with self.subTest(case=name):
                agent = CodeAgent(model=ScriptedModel(output))
                with self.assertRaises(AgentError) as ctx:
                    await agent.generate(task())
                self.assertEqual((ctx.exception.kind, ctx.exception.role), ("output", "code"))
                # 请求已发出：调用计为失败但用量保留，供 S4 共享账本计入。
                self.assertEqual(agent.calls[0].status, "failed")
                self.assertEqual(agent.calls[0].token_usage["total_tokens"], 46)


class SupervisorReviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_review_reads_actual_source_and_machine_report_not_subagent_summary(self):
        art = artifact(change_summary="CHANGE-SUMMARY-SENTINEL")
        model = ScriptedModel(review_json())
        report = await SupervisorAgent(model=model).review(task(), art, validation(art))
        self.assertEqual(report.verdict, "approve")
        self.assertEqual((report.task_id, report.artifact_id, report.artifact_hash, report.round),
                         (art.task_id, art.artifact_id, art.artifact_hash, art.round))
        system, human = model.inputs[0]
        self.assertEqual(system.content, REVIEW_SYSTEM)
        for f in art.files:  # 实际源码逐字进入审查输入，不截断
            self.assertIn(f.name, human.content)
            self.assertIn(f.content, human.content)
        self.assertIn("fixture execution evidence", human.content)  # 机器验证实际输出
        self.assertIn("r-cancel", human.content)
        self.assertIn(art.artifact_hash, human.content)
        self.assertNotIn("CHANGE-SUMMARY-SENTINEL", human.content)  # 不读取子 Agent 自述

    async def test_review_ignores_model_claimed_version_fields(self):
        art = artifact()
        raw = review_json(artifact_hash="f" * 64, task_id="model-claim", artifact_id="model-claim", round=2)
        report = await SupervisorAgent(model=ScriptedModel(raw)).review(task(), art, validation(art))
        self.assertEqual((report.task_id, report.artifact_hash, report.round),
                         (art.task_id, art.artifact_hash, art.round))  # 版本字段只来自服务端产物

    async def test_review_rejects_invalid_locations_and_illegal_verdict_combination(self):
        art = artifact()
        blocking = {"issue_id": "i-1", "requirement_id": "r-cancel", "severity": "blocking",
                    "evidence": "问题", "repair_instruction": "修复"}
        bad_outputs = {
            "未知文件": review_json(issues=[{**blocking, "file": "ghost.go"}]),
            "未知需求": review_json(issues=[{**blocking, "requirement_id": "r-ghost"}]),
            "行号越界": review_json(issues=[{**blocking, "file": "solution.go", "line": 999}]),
            "approve带blocking": review_json(verdict="approve", issues=[blocking]),
            "缺少verdict": json.dumps({k: v for k, v in json.loads(review_json()).items()
                                       if k != "verdict"}, ensure_ascii=False),
            "需求ID被替换": review_json(requirement_checks=[{"requirement_id": "model-substitute",
                                                             "status": "pass", "evidence": "x"}]),
        }
        for name, raw in bad_outputs.items():
            with self.subTest(case=name):
                agent = SupervisorAgent(model=ScriptedModel(raw))
                with self.assertRaises(AgentError) as ctx:
                    await agent.review(task(), art, validation(art))
                self.assertEqual((ctx.exception.kind, ctx.exception.stage), ("output", "review"))


class RepairTests(unittest.IsolatedAsyncioTestCase):
    async def test_repair_carries_full_context_and_freezes_new_round(self):
        code_model = ScriptedModel(fenced(("solution.go", SOLUTION_A), ("solution_test.go", TEST_A)),
                                   fenced(("solution.go", SOLUTION_A), ("solution_test.go", TEST_A_FIXED),
                                          change="CHANGE: 修复取消路径"))
        agent = CodeAgent(model=code_model)
        await agent.generate(task(), references='[{"source": "repair-ref-91", "content": "资料"}]')
        art0 = artifact()
        request = RepairRequest(task_spec=task(), previous_artifact=art0,
                                validation_report=validation(art0, "failed"),
                                review_report=review(art0, verdict="revise",
                                                     issues=[issue(), issue(issue_id="i-2",
                                                                            severity="suggestion")]),
                                remaining_budget=budget(), round=1)
        new = await agent.repair(request)
        self.assertEqual(new.round, 1)
        self.assertEqual(new.addressed_issue_ids, ("i-1",))  # 服务端记录 blocking 问题
        self.assertEqual(new.change_summary, "修复取消路径")
        self.assertEqual([f.content for f in new.files if f.name == ACCEPTANCE_FILE],
                         [ACCEPTANCE_TESTS["context_cancel"]])  # 可信测试每轮原样注入
        fixed = [f.content for f in new.files if f.name == "solution_test.go"][0]
        self.assertIn("cancel-fixed-marker", fixed)  # 模型测试允许随修复更新
        self.assertEqual((agent.calls[1].role, agent.calls[1].stage), ("code", "repair"))
        system, human = code_model.inputs[1]
        self.assertEqual(system.content, CODE_SYSTEM)
        self.assertIn(art0.files[0].content, human.content)  # 上一轮完整源码
        self.assertIn(ACCEPTANCE_FILE, human.content)  # 含服务端固定文件的说明
        self.assertIn("fixture execution evidence", human.content)  # 机器失败输出
        self.assertIn(issue()["repair_instruction"], human.content)  # 审查修复指令
        self.assertIn("i-1", human.content)
        self.assertIn(task().original_requirement, human.content)  # 原始需求仍在交接
        self.assertIn("repair-ref-91", human.content)  # 修复复用首轮资料
        self.assertEqual(agent.artifacts[-1], new)


class TaskIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_tasks_isolated_even_with_shared_role_models(self):
        sup_model = ScriptedModel(plan_json(), review_json(), plan_json_channel(), review_json_channel())
        code_model = ScriptedModel(fenced(("solution.go", SOLUTION_A), ("solution_test.go", TEST_A)),
                                   fenced(("solution.go", SOLUTION_B), ("solution_test.go", TEST_B)))
        req_a = request_of("context_cancel", "任务A唯一标记a1b2：等待取消并返回 ctx.Err()")
        req_b = request_of("channel", "任务B唯一标记c3d4：读取 channel 求和，关闭后返回总和")
        sup_a, code_a = SupervisorAgent(model=sup_model), CodeAgent(model=code_model)
        spec_a = await sup_a.plan(req_a, references='[{"source": "ref-A-777", "content": "a"}]')
        art_a = await code_a.generate(spec_a, references='[{"source": "ref-A-777", "content": "a"}]')
        report_a = await sup_a.review(spec_a, art_a, validation(art_a))
        sup_b, code_b = SupervisorAgent(model=sup_model), CodeAgent(model=code_model)
        spec_b = await sup_b.plan(req_b)
        art_b = await code_b.generate(spec_b)
        report_b = await sup_b.review(spec_b, art_b, validation(art_b))
        self.assertNotEqual(spec_a.task_id, spec_b.task_id)
        self.assertEqual((report_a.verdict, report_b.verdict), ("approve", "approve"))
        self.assertEqual(len(sup_model.inputs), 4)  # plan×2 + review×2
        self.assertEqual(len(code_model.inputs), 2)  # generate×2
        # 代码模型两次输入分别只含各自任务的标记，互不泄漏。
        markers = ["任务A唯一标记a1b2", "任务B唯一标记c3d4"]
        for index, marker in enumerate(markers):
            text = "".join(str(getattr(m, "content", m)) for m in code_model.inputs[index])
            self.assertIn(marker, text)
            self.assertNotIn(markers[1 - index], text)
        # B 的生成输入不含 A 的资料来源与源码哨兵。
        text_b = "".join(str(getattr(m, "content", m)) for m in code_model.inputs[1])
        self.assertNotIn("ref-A-777", text_b)
        self.assertNotIn("SentinelA", text_b)
        # 主 Agent 四次输入同样互不泄漏。
        for index, marker in enumerate(["任务A唯一标记a1b2", "任务A唯一标记a1b2",
                                        "任务B唯一标记c3d4", "任务B唯一标记c3d4"]):
            text = "".join(str(getattr(m, "content", m)) for m in sup_model.inputs[index])
            self.assertIn(marker, text)
        for text in ("".join(str(getattr(m, "content", m)) for m in sup_model.inputs[2:])):
            self.assertNotIn("任务A唯一标记a1b2", text)
            self.assertNotIn("ref-A-777", text)
        # 角色只收到自己的调用：主 Agent 输入均为计划/审查提示词，代码模型均为代码提示词。
        for i in range(4):
            self.assertIn(str(getattr(sup_model.inputs[i][0], "content", "")),
                          (PLAN_SYSTEM, REVIEW_SYSTEM))
        for i in range(2):
            self.assertEqual(str(getattr(code_model.inputs[i][0], "content", "")), CODE_SYSTEM)
        # 实例状态隔离：各自持有各自的计划与产物。
        self.assertIs(sup_a.task, spec_a)
        self.assertIs(sup_b.task, spec_b)
        self.assertEqual(code_a.artifacts, [art_a])
        self.assertEqual(code_b.artifacts, [art_b])

    async def test_default_models_follow_role_configuration(self):
        original = settings.go_multi_agent
        try:
            settings.go_multi_agent = GoMultiAgentSettings(
                enabled=True, supervisor_model="sup-model-x", code_model="code-model-y",
                supervisor_window=30000, code_window=30000)
            sup, code = SupervisorAgent(), CodeAgent()
            self.assertEqual(sup.model.bound.model_name, "sup-model-x")
            self.assertEqual(code.model.bound.model_name, "code-model-y")
            self.assertEqual(sup.model.kwargs["max_tokens"], GoMultiAgentSettings().supervisor_output_tokens)
            self.assertEqual(code.model.kwargs["max_tokens"], GoMultiAgentSettings().code_output_tokens)
        finally:
            settings.go_multi_agent = original


if __name__ == "__main__":
    unittest.main()
