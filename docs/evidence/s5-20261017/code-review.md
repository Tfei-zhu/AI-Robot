# S5 最终源码静态复查

审查日期：2026-10-17。执行者：本次实现代理自行复查；没有声称第三方独立审查或真实模型能力评测。

审查版本：`main` / HEAD `1ea7e6b7abbde3bd1a5963f03cd142fac553685a`；完整源码清单 SHA256 `d70a1763e1b34e4b0928c7c2365005eaecf1afa9db43989c6377095fa33f45af`；相对 HEAD 的 tracked diff SHA256 `907d8a2c27b1e038db0eff4e85ec699ba0047e14256b0a4e674d7c47c57b5d90`。包含未提交和未跟踪实现；清单排除本证据目录及执行日志以避免自引用。

结论：本次 S5 范围静态复查未发现剩余阻断项。行为结果以同指纹的最终离线和 Docker 检查为准，见 commands.json。多 Agent 的业务通过依然由服务器验证 GoTaskResult 的同版本机器证据与审查报告；固定模型 approve 只用于测试机制，不是正确性的独立标签。

| 复查项 | 代码依据与验证 |
| --- | --- |
| 同一业务流 | JSON 的 GoTaskService.run 只消费 stream 的 go_done；SSE 直接消费同一 stream，统一进入现有 LangGraph。没有第二个修复循环 |
| 单一成功判定 | 沿用 decide_after_review；机器/审查同 task/artifact/hash/round；必要需求完整、无 blocking；存储边界再次运行 GoTaskResult 校验，非法 passed 不能入库 |
| 快照版本一致 | 普通事件保存自己的 go_progress 快照，取消/超时使用任务本地最新引用；引用中的 asyncio.Task 不会进入 GoTaskResult 或数据库 JSON |
| 取消及清理次序 | 持有工作流 Task，取消一次并等待它收尾；不重复中断正在清理的任务。执行槽位保持到活动操作清理完成，会话保持到最终报告写入完成；ASGI level cancellation 与重复 asyncio cancellation 均有保护，原取消继续传播 |
| 首事件与断连 | go_start 之前保存 running，首事件后的 aclose 也能落 cancelled；SessionStreamResponse 在发送失败时关闭 body iterator 后才释放会话，不把连接关闭变成 passed |
| 验证异常 | 超时/取消保留当前 hash、清理标记与调用计数；意外验证器异常保留 sandbox 日志并 unavailable，不进入审查或修复 |
| 报告历史 | TaskSpec、artifacts、attempts、reviews、agent_calls、context_stats、stop_reason 都随快照保存；修复生成中断仍保留上一轮完整证据 |
| 旧报告与账户隔离 | 9 个已有实际 JSON 报告原样注入旧 SQLite 行、关闭并重开后通过真实 GET 路由读取；新增字段默认兼容，仅当前认证主体可读。写入检查 run_id 和 owner，不能覆盖他人报告 |
| 用量与预算 | 角色独立注入且共享任务计量；取消调用按发生次数保留，未知用量为 null/unknown，不补成真实零值；本步未放宽预算、hash 或 gate |
| JSON/SSE 比较 | 保留所有业务状态、完整文件/hash、机器/审查证据、次数、实际 Token 和停止原因。仅归一化独立运行 ID/耗时及受随机 ID 影响的本地输入估计；每个输入估计另与模型实际收到的消息精确核对 |

未改已有测试断言、未增加跳过已有检查的条件。新真实 Docker 项仅使用项目既有 AIROBOT_TEST_DOCKER 显式开关，并在最终 Docker 检查中全部运行。S6 Dashboard、Python 3.11、远程 CI 和真实模型评测不是本步完成声明的一部分。
