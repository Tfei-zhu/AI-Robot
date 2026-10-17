"""S4 共享预算账本测试：发送前预占、硬上限、失败计数、绝对截止时间。

纯服务端状态测试，不涉及模型、Docker 或网络。
"""
import unittest

from app.agents.go_workflow import BudgetExceededError, SharedBudget
from app.config import GoMultiAgentSettings


def fake_clock():
    box = [0.0]
    return (lambda: box[0]), box


class SharedBudgetTests(unittest.TestCase):
    def test_reservation_happens_before_send_and_failures_stay_counted(self):
        budget = SharedBudget()
        budget.reserve_model()
        self.assertEqual(budget.used["normal"], 1)  # 预占即计数，与请求成败无关
        budget.reserve_model()  # 第二次“请求失败”也不返还
        self.assertEqual(budget.used, {"normal": 2, "retries": 0, "model": 2,
                                       "validations": 0, "retrievals": 0, "repairs": 0})
        with self.assertRaises(AttributeError):  # 没有释放/返还 API
            budget.release

    def test_hard_caps_seven_normal_one_retry_eight_total(self):
        budget = SharedBudget()
        for _ in range(7):
            budget.reserve_model()
        with self.assertRaises(BudgetExceededError) as ctx:
            budget.reserve_model()
        self.assertEqual(ctx.exception.kind, "model")  # 正常额度上限 7
        budget.reserve_model(retry=True)  # 唯一共享异常重试
        self.assertEqual(budget.used["model"], 8)
        with self.assertRaises(BudgetExceededError) as ctx:
            budget.reserve_model(retry=True)
        self.assertEqual(ctx.exception.kind, "retry")
        # 总额 8 用尽后即使换别的名义也不能再发
        with self.assertRaises(BudgetExceededError):
            budget.reserve_model()

    def test_validation_repair_retrieval_caps(self):
        budget = SharedBudget()
        budget.reserve_retrieval()
        with self.assertRaises(BudgetExceededError) as ctx:
            budget.reserve_retrieval()
        self.assertEqual(ctx.exception.kind, "retrieval")
        for _ in range(3):
            budget.reserve_validation()
        with self.assertRaises(BudgetExceededError) as ctx:
            budget.reserve_validation()
        self.assertEqual(ctx.exception.kind, "validation")
        for _ in range(2):
            budget.reserve_repair()
        with self.assertRaises(BudgetExceededError) as ctx:
            budget.reserve_repair()
        self.assertEqual(ctx.exception.kind, "repair")

    def test_deadline_is_absolute_and_never_resets_across_rounds(self):
        clock, box = fake_clock()
        budget = SharedBudget(seconds=100.0, clock=clock)
        budget.reserve_repair()  # 进入修复轮
        box[0] = 50.0
        self.assertEqual(budget.seconds_left(), 50.0)
        self.assertEqual(budget.stage_timeout(60.0), 50.0)  # 阶段上限取剩余时间较小值
        self.assertEqual(budget.stage_timeout(30.0), 30.0)
        box[0] = 100.0  # 到达截止：不随轮次重置
        self.assertEqual(budget.seconds_left(), 0.0)
        for reserve in (lambda: budget.reserve_model(),
                        lambda: budget.reserve_model(retry=True),
                        lambda: budget.reserve_validation(),
                        lambda: budget.reserve_repair(),
                        lambda: budget.stage_timeout(10.0)):
            with self.assertRaises(BudgetExceededError) as ctx:
                reserve()
            self.assertEqual(ctx.exception.kind, "deadline")
        box[0] = 150.0  # 过期之后也不会恢复
        with self.assertRaises(BudgetExceededError):
            budget.reserve_model()

    def test_snapshot_reflects_remaining_not_limits(self):
        budget = SharedBudget(max_normal_calls=3, max_retries=1, max_model_calls=4, seconds=60.0)
        budget.reserve_model()
        budget.reserve_validation()
        snapshot = budget.snapshot()
        self.assertEqual((snapshot.normal_calls, snapshot.retries, snapshot.model_calls,
                          snapshot.validations), (2, 1, 3, 2))
        self.assertGreater(snapshot.seconds, 0)

    def test_invalid_limits_are_rejected(self):
        for kwargs in ({"max_normal_calls": 8}, {"max_retries": 2}, {"max_model_calls": 9},
                       {"max_model_calls": 9, "max_normal_calls": 8, "max_retries": 2},
                       {"max_repairs": 3}, {"max_validations": 4}, {"max_retrievals": 2},
                       {"seconds": 0}, {"seconds": -1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                SharedBudget(**kwargs)

    def test_from_settings_maps_first_version_limits(self):
        budget = SharedBudget.from_settings(GoMultiAgentSettings())
        for _ in range(7):
            budget.reserve_model()
        budget.reserve_model(retry=True)
        for _ in range(3):
            budget.reserve_validation()
        for _ in range(2):
            budget.reserve_repair()
        budget.reserve_retrieval()
        self.assertEqual(budget.used, {"normal": 7, "retries": 1, "model": 8,
                                       "validations": 3, "retrievals": 1, "repairs": 2})
        # 最坏业务路径（计划+3生成+3审查+1重试+3验证+2修复+1检索）恰好被上限容纳
        with self.assertRaises(BudgetExceededError):
            budget.reserve_model()


if __name__ == "__main__":
    unittest.main()
