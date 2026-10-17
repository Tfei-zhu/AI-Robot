# S7 当前版本自查

本次由实施代理做静态自查，不声称第三方独立审查。绑定 HEAD `1ea7e6b7abbde3bd1a5963f03cd142fac553685a`、分支 `main`、完整相关源码清单 SHA256 `a921ed45278e3ba7f998c83955be331a0d61afb1845210fc11168bfa1085b7dc`、tracked diff SHA256 `2be76607869053633d5a7ec7b8383b42d64137bf6724405001ee868836b93f1a`。清单包括未跟踪源码，排除证据目录和执行记录以避免递归。核对基准为 source-final-validation.json，最终 verify_evidence.py 必须确认文件逐字相同。

S7 增加两个测试文件和验收映射，不改变现有应用代码、不删除或修改已有测试断言。对本次相关源码和已有关键防线的检查结论：未发现需修改应用实现的阻断问题，结论须同时以最终测试结果为准。

- go_workflow.py 的最终成功门禁重验 TaskSpec/CodeArtifact、完整机器报告及版本绑定，再检查 approve、必要需求覆盖与 blocking。GoTaskResult 和 Store.save 在产物/持久化边界复用成功不变量，避免绕过工作流直接写 passed。失败编译即使 approve 仍需修复，新增真实编译用例保存完整两轮报告。
- CodeArtifact 在完整文件清单中核对可信验收测试原文并重新计算 hash；freeze_artifact 先注入再计算。验证报告不会被重新贴到新版本，ReviewReport.check_context 核对 task_id/artifact_id/hash/round。模型版本字段不能替换服务端版本。测试同时覆盖 rehashed 伪造可信测试，以及旧 round 0 approve 在新 round 1 连续两次返回的反例。
- SharedBudget 在外部调用前预占，正常、共享异常重试和总额独立检查；失败请求不返还。RoleRunner 使用 retry=False、默认角色 SDK max_retries=0。新增真实 ainvoke 捕获 8 次固定客户端调用（含一次 provider 异常）及第 9 次预占被拒绝；总额 2、重试仍剩 1 的低额度反例专门证明总额独立生效。
- 所有模型文本和日志只是输入数据；SupervisorAgent 从当前完整源码、实际机器日志重建审查，显式选取审查内容字段。注入 status、max_model_calls、shell、disable_tests 不改服务端预算/终态。真实 Docker 另检查无网络、无挂载、非特权、只读根、非 root、无宿主 secret 与资源限制。这不是对真实模型抗注入质量的评测。
- RoleRunner 记录 cancelled 后重新抛出；Workflow/Service 保存已有快照并等待活动任务结束。_execution_slot 等待沙箱清理后释放并发容量，SessionStreamResponse 关闭迭代器后释放会话。新计划/检索 HTTP 取消及超时用例覆盖首个产物之前的报告、1 次实际模型调用、0 次验证、计划有无、重试不增加、检索预占、用量账本回收、会话释放及跨账户 404；原有生成/审查/修复/真实沙箱中断断言全部保留。
- JSON 与 SSE 消费同一 service.stream；HTTP 测试比较六种业务结果，并验证只有一个最终事件、事件 run_id、每轮持久化和预算计数，HTTP 200 与流结束不会代替业务成功。旧原始报告直接入库重开后 GET 补默认值；开关关闭沿用原 Go 图，原问答和文章回归另报告。
- 定向失效都在隔离副本逐个执行，且先跑原控制、再期待断言失败、最后逐字恢复和重跑。五处失效被检出均为 AssertionError，非语法错误/导入失败/超时。原目录以及旧记录不改写；故意失败单独列出，不掩盖正常版本的失败。

限制：模型/检索输出受控；真实 Docker 使用本地固定镜像，不能证明云端或其他架构行为。Python 3.11、远程 CI、收费真实模型评测、本次浏览器重跑均未运行。付费评测未获累计费用上限；没有执行或宣称模型效果提升。角色超时直接 timeout，不重置截止时间；格式错误/cannot_assess 才使用共享重试，这与状态规则一致。保留第三方 jieba 的三个 SyntaxWarning，未过滤以获取通过。
