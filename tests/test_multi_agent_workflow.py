"""S3 闭环 + S4 强制测试：固定模型与验证替身跑通五条主路径，真实沙箱类单独启用。

ScriptedModel/StubRunner 记录底层实际调用；断言基于真实请求序列，证明
超限后没有继续请求、每轮报告绑定当前版本、环境故障不进入修复。
"""
import asyncio
import os
import unittest

from app.agents.code_agent import CodeAgent
from app.agents.go_workflow import MultiAgentGoWorkflow, SharedBudget
from app.agents.supervisor import SupervisorAgent
from app.go_validation.contracts import (
    GoTaskRequest, StageReport, ValidationReport, artifact_hash,
)
from app.go_validation.runner import DockerGoRunner
from test_multi_agent_agents import (
    SOLUTION_A, TEST_A, TEST_A_FIXED, ScriptedModel, fenced, plan_json, review_json,
)

REQUIREMENT = "任务R-9271：等待取消并返回 ctx.Err()，取消前不得提前返回"
BROKEN = 'package example\nimport "context"\nfunc WaitForCancel(ctx context.Context) error { SentinelA(); return nil }\nfunc SentinelA() {}\n'
BROKEN2 = BROKEN.replace("return nil", "return error(nil)")
BROKEN3 = BROKEN.replace("func SentinelA()", "func SentinelA2()")


def request():
    return GoTaskRequest(requirement=REQUIREMENT, scenario="context_cancel")


def blocking_review(**changes):
    issue = {"issue_id": "i-1", "requirement_id": "r-cancel", "severity": "blocking",
             "file": "solution.go", "line": 3, "evidence": "未等待取消即返回",
             "repair_instruction": "等待 ctx.Done() 后返回 ctx.Err()"}
    data = {"verdict": "revise", "issues": [issue],
            "requirement_checks": None}  # 由下方构造完整 JSON
    data.update(changes)
    import json
    payload = json.loads(review_json())
    payload["verdict"] = data.get("verdict", "revise")
    payload["issues"] = data["issues"]
    if data.get("verdict") == "approve":
        payload["issues"] = []
    return payload


def revise_json():
    import json
    return json.dumps(blocking_review(), ensure_ascii=False)


class StubRunner:
    """验证替身：按脚本返回结果，报告按提交副本绑定 hash（对齐真实 runner 行为）。"""

    def __init__(self, *outcomes):
        self.outcomes, self.bundles = list(outcomes), []

    async def validate(self, bundle):
        self.bundles.append(bundle)
        outcome = self.outcomes.pop(0) if self.outcomes else "passed"
        if outcome in ("unavailable", "timeout", "cancelled"):
            report = ValidationReport(status=outcome)
        else:
            stages = [StageReport(stage=name, exit_code=0, output=f"{name} ok")
                      for name in ("policy", "compile", "vet", "test")]
            if outcome == "failed":
                stages[3] = StageReport(stage="test", exit_code=1, output=(
                    "FAIL: TestServerAlreadyCancelled\nfixture-machine-error-9527\nexit status 1"))
            report = ValidationReport(status=outcome, stages=stages, container_removed=True)
        report.artifact_hash = artifact_hash(bundle.files)
        return report


def make(*sup_replies, code_replies, outcomes=("passed",), budget=None, retrieve=None, runner=None):
    sup_model, code_model = ScriptedModel(*sup_replies), ScriptedModel(*code_replies)
    workflow = MultiAgentGoWorkflow(
        supervisor=SupervisorAgent(model=sup_model), code=CodeAgent(model=code_model),
        runner=runner if runner is not None else StubRunner(*outcomes),
        retrieve=retrieve, budget=budget)
    return workflow, sup_model, code_model


def text_of(messages):
    return "".join(str(getattr(m, "content", m)) for m in messages)


class ClosedLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_pass_uses_three_model_calls_and_review_summary(self):
        workflow, sup, code = make(plan_json(), review_json(),
                                   code_replies=[fenced(("solution.go", SOLUTION_A),
                                                        ("solution_test.go", TEST_A))])
        result = await workflow.run(request())
        self.assertEqual(result.status, "passed")
        self.assertEqual(result.stop_reason, "completed")
        self.assertEqual(result.workflow_version, "multi-v1")
        self.assertEqual(result.final_summary, "符合需求")  # 复用审查摘要，无额外调用
        self.assertEqual((len(sup.inputs), len(code.inputs)), (2, 1))  # 计划+审查 / 生成
        self.assertEqual(result.model_calls, 3)
        self.assertEqual([c.stage for c in result.agent_calls], ["plan", "generate", "review"])
        self.assertEqual([a.number for a in result.attempts], [0])
        self.assertEqual(len(result.artifacts), 1)
        self.assertEqual(workflow.budget.used["normal"], 3)
        self.assertEqual(workflow.budget.used["validations"], 1)
        self.assertIsNone(result.error)

    async def test_repair_passes_after_machine_failure_with_fresh_reports(self):
        workflow, sup, code = make(
            plan_json(), revise_json(), review_json(),
            code_replies=[fenced(("solution.go", BROKEN), ("solution_test.go", TEST_A)),
                          fenced(("solution.go", SOLUTION_A), ("solution_test.go", TEST_A_FIXED),
                                 change="CHANGE: 修复为等待取消")],
            outcomes=("failed", "passed"))
        result = await workflow.run(request())
        self.assertEqual((result.status, result.stop_reason), ("passed", "completed"))
        self.assertEqual([a.number for a in result.attempts], [0, 1])
        self.assertEqual(len(result.artifacts), 2)
        self.assertNotEqual(result.artifacts[0].artifact_hash, result.artifacts[1].artifact_hash)
        # 禁止复用旧版本报告：每轮验证与审查都绑定当轮 hash 与轮次
        for index in (0, 1):
            self.assertEqual(result.attempts[index].validation.artifact_hash,
                             result.artifacts[index].artifact_hash)
            self.assertEqual(result.reviews[index].artifact_hash,
                             result.artifacts[index].artifact_hash)
            self.assertEqual(result.reviews[index].round, index)
        self.assertEqual((len(sup.inputs), len(code.inputs)), (3, 2))
        self.assertEqual(workflow.budget.used["validations"], 2)
        self.assertEqual(workflow.budget.used["repairs"], 1)
        # 修复请求内容：原需求 + 当前完整源码 + 实际错误日志 + 问题 ID 与修复要求
        repair_prompt = text_of(code.inputs[1])
        self.assertIn(REQUIREMENT, repair_prompt)
        self.assertIn(BROKEN, repair_prompt)
        self.assertIn("fixture-machine-error-9527", repair_prompt)
        self.assertIn("i-1", repair_prompt)
        self.assertIn("等待 ctx.Done() 后返回 ctx.Err()", repair_prompt)

    async def test_machine_passed_but_blocking_requirement_issue_still_repairs(self):
        workflow, sup, code = make(
            plan_json(), revise_json(), review_json(),
            code_replies=[fenced(("solution.go", SOLUTION_A), ("solution_test.go", TEST_A)),
                          fenced(("solution.go", SOLUTION_A), ("solution_test.go", TEST_A_FIXED),
                                 change="CHANGE: 按审查要求调整")],
            outcomes=("passed", "passed"))
        result = await workflow.run(request())
        self.assertEqual((result.status, result.stop_reason), ("passed", "completed"))
        self.assertEqual(len(result.artifacts), 2)  # 机器通过仍被要求修复
        self.assertEqual(result.reviews[0].verdict, "revise")

    async def test_model_approve_cannot_override_machine_failure_until_repair_limit(self):
        workflow, sup, code = make(
            plan_json(), review_json(), review_json(), review_json(),
            code_replies=[fenced(("solution.go", name), ("solution_test.go", TEST_A))
                          for name in (BROKEN, BROKEN2, BROKEN3)],
            outcomes=("failed", "failed", "failed"))
        result = await workflow.run(request())
        self.assertEqual((result.status, result.stop_reason), ("failed", "repair_limit"))
        self.assertEqual(len(result.artifacts), 3)  # 3 份进入验证的代码版本
        self.assertEqual(len(result.attempts), 3)
        self.assertEqual((len(sup.inputs), len(code.inputs)), (4, 3))  # 计划+3审查 / 3生成
        self.assertEqual(result.model_calls, 7)  # 首版最坏路径恰好容纳
        self.assertEqual(workflow.budget.used, {"normal": 7, "retries": 0, "model": 7,
                                                "validations": 3, "retrievals": 0, "repairs": 2})

    async def test_decision_side_budget_exhaustion_reports_budget_exceeded(self):
        budget = SharedBudget(max_normal_calls=3, max_retries=1, max_model_calls=4)
        workflow, sup, code = make(plan_json(), revise_json(),
                                   code_replies=[fenced(("solution.go", BROKEN),
                                                        ("solution_test.go", TEST_A))],
                                   outcomes=("failed",), budget=budget)
        result = await workflow.run(request())
        self.assertEqual((result.status, result.stop_reason), ("budget_exceeded", "budget_exceeded"))
        self.assertEqual((len(sup.inputs), len(code.inputs)), (2, 1))

    async def test_ledger_stops_request_before_send_when_total_exhausted(self):
        budget = SharedBudget(max_normal_calls=2, max_retries=1, max_model_calls=2)
        workflow, sup, code = make(plan_json(), review_json(),
                                   code_replies=[fenced(("solution.go", SOLUTION_A),
                                                        ("solution_test.go", TEST_A))],
                                   outcomes=("failed",), budget=budget)
        result = await workflow.run(request())
        self.assertEqual((result.status, result.stop_reason), ("budget_exceeded", "budget_exceeded"))
        # 关键证明：计划+生成共 2 次后，审查请求从未发送到底层客户端
        self.assertEqual((len(sup.inputs), len(code.inputs)), (1, 1))
        self.assertEqual(workflow.budget.used["model"], 2)
        self.assertEqual([c.stage for c in result.agent_calls], ["plan", "generate"])

    async def test_environment_unavailable_terminates_without_review_or_repair(self):
        workflow, sup, code = make(plan_json(),
                                   code_replies=[fenced(("solution.go", SOLUTION_A),
                                                        ("solution_test.go", TEST_A))],
                                   outcomes=("unavailable",))
        result = await workflow.run(request())
        self.assertEqual((result.status, result.stop_reason), ("unavailable", "unavailable"))
        self.assertEqual((len(sup.inputs), len(code.inputs)), (1, 1))  # 无审查、无修复
        self.assertEqual(len(result.attempts), 1)
        # 不可用报告同样绑定提交版本
        self.assertEqual(result.attempts[0].validation.artifact_hash,
                         result.artifacts[0].artifact_hash)

    async def test_identical_failed_artifact_stops_as_no_progress(self):
        same = fenced(("solution.go", BROKEN), ("solution_test.go", TEST_A))
        workflow, sup, code = make(plan_json(), revise_json(), revise_json(),
                                   code_replies=[same, same], outcomes=("failed", "failed"))
        result = await workflow.run(request())
        self.assertEqual((result.status, result.stop_reason), ("failed", "no_progress"))
        self.assertEqual(len(result.artifacts), 2)
        self.assertEqual(len(result.attempts), 2)  # 第二轮验证后即停止
        self.assertEqual((len(sup.inputs), len(code.inputs)), (3, 2))

    async def test_review_format_error_consumes_shared_retry_then_passes_or_fails(self):
        good = make(plan_json(), "不是 JSON", review_json(),
                    code_replies=[fenced(("solution.go", SOLUTION_A), ("solution_test.go", TEST_A))])
        result = await good[0].run(request())
        self.assertEqual(result.status, "passed")
        self.assertEqual(len(good[1].inputs), 3)  # 计划 + 审查失败 + 重试
        self.assertEqual(good[0].budget.used["retries"], 1)
        bad = make(plan_json(), "不是 JSON", "仍然不是 JSON",
                   code_replies=[fenced(("solution.go", SOLUTION_A), ("solution_test.go", TEST_A))])
        result = await bad[0].run(request())
        self.assertEqual((result.status, result.stop_reason), ("failed", "review_error"))
        self.assertEqual(len(bad[1].inputs), 3)
        self.assertEqual(bad[0].budget.used["retries"], 1)  # 共享重试只此一次

    async def test_generate_parse_failure_consumes_shared_retry_and_counts(self):
        workflow, sup, code = make(
            plan_json(), review_json(),
            code_replies=["没有文件头的输出",
                          fenced(("solution.go", SOLUTION_A), ("solution_test.go", TEST_A))])
        result = await workflow.run(request())
        self.assertEqual(result.status, "passed")
        self.assertEqual(len(code.inputs), 2)
        self.assertEqual(workflow.budget.used["retries"], 1)
        self.assertEqual(workflow.budget.used["normal"], 3)  # 计划+生成+重试生成后审查
        self.assertEqual(workflow.budget.used["model"], 4)

    async def test_expired_deadline_rejects_every_request_before_send(self):
        box = [0.0]
        budget = SharedBudget(seconds=100.0, clock=lambda: box[0])
        box[0] = 100.0
        workflow, sup, code = make(plan_json(), review_json(),
                                   code_replies=[fenced(("solution.go", SOLUTION_A),
                                                        ("solution_test.go", TEST_A))],
                                   budget=budget)
        result = await workflow.run(request())
        self.assertEqual((result.status, result.stop_reason), ("timeout", "timeout"))
        self.assertEqual((len(sup.inputs), len(code.inputs)), (0, 0))  # 截止后零请求

    async def test_cancellation_propagates_and_no_further_requests(self):
        cancelled = asyncio.CancelledError()
        workflow, sup, code = make(plan_json(),
                                   code_replies=[cancelled])
        with self.assertRaises(asyncio.CancelledError):
            await workflow.run(request())
        self.assertEqual((len(sup.inputs), len(code.inputs)), (1, 1))
        self.assertEqual(workflow.budget.used["model"], 2)
        self.assertEqual([c.status for c in workflow.supervisor.runner.calls
                          + workflow.code.runner.calls].count("cancelled"), 1)
        workflow2, sup2, code2 = make(plan_json(), cancelled,
                                      code_replies=[fenced(("solution.go", SOLUTION_A),
                                                           ("solution_test.go", TEST_A))])
        with self.assertRaises(asyncio.CancelledError):
            await workflow2.run(request())
        # 审查请求发出后被取消（sup 第 2 次输入），此后无任何新请求
        self.assertEqual((len(sup2.inputs), len(code2.inputs)), (2, 1))
        self.assertEqual([c.status for c in workflow2.supervisor.runner.calls], ["passed", "cancelled"])

    async def test_retrieval_reserved_once_and_degrades_on_failure(self):
        calls = []

        async def retrieve(query):
            calls.append(query)
            return {"chunks": [{"content": "资料sentinel-RETR"}], "sources": ["kb://go/x"]}

        workflow, sup, code = make(plan_json(), revise_json(), review_json(),
                                   code_replies=[fenced(("solution.go", BROKEN),
                                                        ("solution_test.go", TEST_A)),
                                                 fenced(("solution.go", SOLUTION_A),
                                                        ("solution_test.go", TEST_A_FIXED))],
                                   outcomes=("failed", "passed"), retrieve=retrieve)
        result = await workflow.run(request())
        self.assertEqual(result.status, "passed")
        self.assertEqual(calls, [REQUIREMENT])  # 修复轮复用资料，只检索一次
        self.assertEqual(result.sources, ["kb://go/x"])
        self.assertIn("资料sentinel-RETR", text_of(code.inputs[0]))
        self.assertIn("资料sentinel-RETR", text_of(code.inputs[1]))
        self.assertEqual(workflow.budget.used["retrievals"], 1)

        async def broken_retrieve(query):
            raise RuntimeError("检索不可用")

        workflow2, sup2, code2 = make(plan_json(), review_json(),
                                      code_replies=[fenced(("solution.go", SOLUTION_A),
                                                           ("solution_test.go", TEST_A))],
                                      retrieve=broken_retrieve)
        result = await workflow2.run(request())
        self.assertEqual(result.status, "passed")  # 检索失败降级，不阻断任务
        self.assertEqual(result.sources, [])
        self.assertEqual(workflow2.budget.used["retrievals"], 1)  # 失败也计数

    async def test_plan_failure_after_retry_is_generation_error(self):
        workflow, sup, code = make("坏 JSON", "还是坏 JSON", code_replies=[])
        result = await workflow.run(request())
        self.assertEqual((result.status, result.stop_reason), ("generation_error", "generation_error"))
        self.assertEqual(len(sup.inputs), 2)  # 计划 + 共享重试各一次
        self.assertEqual(len(code.inputs), 0)
        self.assertIsNone(result.task_spec)
        self.assertEqual(workflow.budget.used, {"normal": 1, "retries": 1, "model": 2,
                                                "validations": 0, "retrievals": 0, "repairs": 0})


@unittest.skipUnless(os.environ.get("AIROBOT_TEST_DOCKER") == "1", "启用真实 Docker 测试")
class RealSandboxClosedLoopTests(unittest.IsolatedAsyncioTestCase):
    """真实 Linux 沙箱 + 固定模型：验证报告来自实际容器执行，不是替身。"""

    async def test_real_first_pass(self):
        workflow, sup, code = make(plan_json(), review_json(),
                                   code_replies=[fenced(("solution.go", SOLUTION_A),
                                                        ("solution_test.go", TEST_A))],
                                   runner=DockerGoRunner())
        result = await workflow.run(request())
        self.assertEqual((result.status, result.stop_reason), ("passed", "completed"))
        validation = result.attempts[0].validation
        self.assertEqual([s.stage for s in validation.stages], ["policy", "compile", "vet", "test"])
        self.assertTrue(all(s.exit_code == 0 for s in validation.stages))
        self.assertTrue(validation.container_removed)

    async def test_real_repair_after_compile_or_test_failure(self):
        workflow, sup, code = make(
            plan_json(), revise_json(), review_json(),
            code_replies=[fenced(("solution.go", BROKEN), ("solution_test.go", TEST_A)),
                          fenced(("solution.go", SOLUTION_A), ("solution_test.go", TEST_A_FIXED),
                                 change="CHANGE: 修复为等待取消")],
            runner=DockerGoRunner())
        result = await workflow.run(request())
        self.assertEqual((result.status, result.stop_reason), ("passed", "completed"))
        first, second = result.attempts[0].validation, result.attempts[1].validation
        self.assertEqual(first.status, "failed")
        self.assertTrue(any(s.exit_code != 0 for s in first.stages))
        # 审查读取的是真实失败输出，不是替身文本
        self.assertIn("FAIL", text_of(sup.inputs[1]))
        self.assertEqual(second.status, "passed")
        self.assertTrue(second.container_removed)


if __name__ == "__main__":
    unittest.main()
