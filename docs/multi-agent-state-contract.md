# S1：状态、契约与服务端不变量

此文先于 S1 实现建立。S1 只提供契约、配置及可独立执行的服务端判定；角色调用、主图接入及运行时共享账本分别在 S2–S4 实现。新流程默认关闭，现有 Go/普通聊天路径不切换。

## 状态流转

| 当前阶段 | 服务端确认的输入/条件 | 下一阶段或终态 |
| --- | --- | --- |
| planning | TaskSpec 合法，原始需求及固定场景接口已保留 | generating |
| generating / repairing | 完整源码合法，注入本场景可信测试后冻结并计算 hash | validating |
| validating | 验证器返回代码检查 passed 或 failed，报告绑定当前 hash | reviewing（失败也需审查） |
| validating | unavailable / 沙箱级 timeout / cancelled | 对应终态，禁止代码修复 |
| reviewing | 机器完整通过、当前版本 approve、必要条目均检查通过、无 blocking | passed |
| reviewing | 报告非法、陈旧、cannot_assess、漏检查 | 共享异常重试尚有额度且总模型/时间额度足够：reviewing；否则 failed/review_error |
| reviewing | 有可修复代码或需求问题 | 未超过两轮修复且剩余生成/审查/验证/时间额度足够：repairing；否则 failed/repair_limit 或 budget_exceeded |
| repairing | 与上一失败版本内容完全相同 | failed/no_progress |
| 任意运行阶段 | 用户取消 / 总截止时间到达 | cancelled / timeout，终止并保留进度 |
| 任意终态 | 再次尝试推进 | 拒绝；不可恢复为运行态或用新结论改写已结束任务 |

业务状态仍使用现有 GoTaskResult.status；内部 phase 单独表示 planning/generating/validating/reviewing/repairing/finished，避免把 HTTP 200、SSE 结束或模型文本当作 passed。

## 不变量

1. TaskSpec、需求、问题、代码版本及报告均有受长度/格式限制的 ID；需求 ID 唯一，验收条件引用已存在的需求。必要需求清单由服务端持有的 TaskSpec 决定，不能由审查报告自行缩小。
2. 模型输出仍是现有 GeneratedCode/围栏源码。服务端先追加 `server_acceptance_test.go`，再按文件名排序，对完整文件名及原始 UTF-8 内容使用无歧义 JSON 序列化计算 SHA-256。文件顺序不影响版本，任何源码/测试/文件名变化都改变版本；不截断、不删除空白、不作换行替换。文件名沿用现有 ASCII 单层文件规则，不小写合并不同文件。
3. CodeArtifact 是冻结快照；重新加载时重新校验完整文件、当前场景可信测试及 hash。模型提供的摘要或 hash 不是事实来源；实际验证器根据提交副本绑定报告 hash，服务端绑定函数只补任务/版本 ID 与轮次，缺 hash 的历史报告或已有不匹配 hash 必须拒绝重标。
4. 通过判定重新检查 task/artifact/report 的 ID、轮次和 hash 关联。机器 passed 还必须有固定 Go 版本、policy/compile/vet/test 四阶段顺序、全部退出码 0、日志未截断、容器已确认删除。旧版缺 hash 的报告可以读取，但不能进入新流程成功门。
5. approve 同时带 blocking 属于非法报告；check/issue ID 唯一，证据与修复要求非空。指向源码的文件/行号须存在；允许整体问题没有单行定位。approve 的必要需求必须明确通过；仅有 suggestion 可通过。
6. requirements_complete 只证明服务端清单中必要条目均有显式 pass 和证据，不证明模型理解/源码语义正确。语义仍需完整源码审查与不可由模型改写的独立行为测试；S1 不宣称形式化正确性或效果提升。
7. 纯判定函数不调用模型、工具、Docker 或网络。重试、修复和终态选择由服务端决定；机器失败不能被 approve 覆盖。模型不能传入最终 status 或修改额度来控制路由。
8. 配置默认正常模型 7 次、共享异常重试 1 次、总模型 8 次、业务修复 2 轮、验证 3 次、检索 1 次、总时间 360 秒；阶段上限 120/60/90 秒且不得大于任务上限。允许收紧，不允许提高首版调用/修复硬上限；非法数值、布尔值、非有限时间和模型/上下文参数启动拒绝。每个阶段取剩余时间较小值；发送前占用及实际账本接入属于 S4，S1 不将配置字段当作已完成的预算拦截器。
9. 新嵌套字段对旧报告提供默认值，保留旧 attempts/status 含义。读取历史 passed 不触发新流程成功认证；新流程通过必须重新取得带当前版本的证据。

## S1 验收

正向：当前版本完整验证与审查通过；仅建议可通过；旧历史 JSON（含嵌套 attempts/validation）可读取。

反向：机器 failed 但 approve、approve+blocking、任一报告 hash 不符、必要需求缺失/不通过、ID/行号不匹配、可信测试被改、预算耗尽/修复耗尽、非法配置均不得通过。使用真实 Pydantic 对象及服务端函数执行离线断言，不依赖付费模型、tiktoken 词表或 Docker。
