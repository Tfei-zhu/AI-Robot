# S2–S4 独立审查（2026-10-17）

结论：不建议将 S2–S4 整体标记为验收完成。发现 2 项 P1、5 项 P2；未修改业务源码或已有测试。S3 的 T12 接入明确缺失，S4 的运行时额度和超时/用量边界仍有缺口。正常闭环通过与这些反例失败同时成立。

审查对象：`main`，HEAD `1ea7e6b7abbde3bd1a5963f03cd142fac553685a`；工作区源码清单 SHA256 `4dd5a0b0dc236d79cf66aade27c96de889e2e78448409ca617a40cb32086b6dd`；相对 HEAD 的已跟踪差异 SHA256 `421f2f86ed91a55d6ad2df075d2f4c63558d7f43417ae47e3adc7a3c027c275c`。未跟踪代码包含于源码清单，执行日志和 evidence 排除以避免自引用。逐文件摘要见 `source-before.json` / `source-after.json`。

## R1 [P1] 启用开关没有接入现有 Go 任务入口（T12）

位置：`app/agents/graph.py:277–278`；`app/agents/go_workflow.py:284–295`。

现有图的 START 对 Go 请求仍无条件路由到旧 `go_retrieve`；没有任何地方读取 `go_multi_agent.enabled` 来选择流程。把有效配置设为 enabled=true，经真实 `GoTaskService.run()`（模型、验证器替身，内存存储）执行后，仍返回 `single-v1 / passed`、1 次模型调用、0 份审查报告。新 gate 完全没有参与用户入口。S3 提示词和 T12 明确要求此时接入图及开关，不能仅把组件测试通过视为 S3 完成。需在现有图建立选择入口，并验证 true/false 两条真实 service 路径；T16–T19 的后续存储/事件扩展不能替代这一入口。

证据：`probes.txt` 的 ENTRY，`test_enabled_switch_selects_multi_workflow` 实际失败。

## R2 [P1] 角色输入/窗口额度未在模型发送前执行（T11/T15）

位置：`app/agents/role_runtime.py:112–117`。

配置里的 supervisor/code input_tokens、window、safety_tokens 仅参与启动期数值校验；调用路径没有使用它们校验实际提示词。`context_usage.invoke()` 只有在另一个实验性 context_mode=enforce 开关启用时才检查全局窗口，且使用全局模型参数，不能替代独立角色额度。实测在 enabled=true、两角色 input_tokens=1、context_mode=off 下，首个提示词本地估算 599 tokens，仍发送共 3 次模型请求并返回 passed。完整源码/修复报告增大时将同样越过配置，失败只能交给服务商处理并消耗重试。需按实际角色计量并在发送前拒绝超限；未知计量明确标记保守/未知，必要源码不能静默截断，也不能依赖实验性上下文开关。

证据：`probes.txt` 的 INPUT_BUDGET，`test_role_input_budget_blocks_before_model_send` 实际失败。

## R3 [P2] 编排层验证超时构造无 hash 报告，导致丢失超时及调用证据（T13/T15）

位置：`app/agents/go_workflow.py:389–392`。

外层 wait_for 超时时，新建的 ValidationReport 没有 artifact_hash，紧接着 bind_validation 必然按 S1 规则拒绝。因此 _loop 来不及追加 Attempt，run 的兜底异常将真正的 timeout 变成 unavailable。实测 10ms 验证上限、200ms 验证替身：结果 unavailable、错误是“验证器未绑定实际输入版本”、validation_calls=0、attempts=[]，但共享账本 validations=1。真实 Docker runner 在外层限时先取消它时也进入这条路径，不能依赖其内部 finally 设置一个未返回的报告。需保留本次发送时冻结的版本与清理结果，创建可验证的当前超时证据及计数，不可通过放宽 bind_validation 接受历史无 hash 报告来修复。

证据：`probes.txt` 的 VALIDATION_TIMEOUT，`test_validation_stage_timeout_is_retained_as_timeout` 实际失败。

## R4 [P2] 独立注入的角色账本被漏汇总并丢弃（T08/T15）

位置：`app/agents/go_workflow.py:466`，关联 `:314–315`。

SupervisorAgent 和 CodeAgent 独立构造时各自生成 run_id，MultiAgentGoWorkflow 又生成第三个 run_id。_result 只读取工作流 run_id 的账本，随后 finally 丢弃三个账本。实测正常 3 次模型调用、总 tokens=138，但 context_stats.model_calls=0、context_stats.token_usage 全 0。角色信息保留在 agent_calls 并不能挽救 context_stats 内丢失的实际请求、用量完整性和费用依据。需将注入角色关联至同一任务账本，或完整合并其账本后再清理；补充注入角色的汇总一致性测试。

证据：`probes.txt` 的 ROLE_LEDGERS，`test_injected_role_usage_is_in_task_ledger` 实际失败。

## R5 [P2] 缺失用量被补成已知零值（T15）

位置：`app/agents/role_runtime.py:56–60`；`app/agents/go_workflow.py:453–457`。

usage_of 对部分 metadata 用 get(k,0) 补零；例如服务商仅给 input_tokens=12，就记录 output_tokens=0、total_tokens=0。_result 又从全零 totals 出发忽略所有 None，用空白/部分用量产生看似完整的 token_usage。实测三次调用均无 usage，agent_calls 的 None 正确保留，但顶层 token_usage 全零；注入路径还同时出现 R4 导致 usage_complete=true、unknown_usage_calls=0。即使修好 R4，顶层补零及部分字段伪造仍需独立修正。需区分 known totals 与未知实际总量，保留 unknown 次数，字段不全不能补成完整用量。

证据：`probes.txt` 的 UNKNOWN_USAGE 和 PARTIAL_USAGE，两项断言实际失败。

## R6 [P2] cleanup_timeout 未传入执行器，也未分配总截止内的清理时间（T15）

位置：`app/agents/go_workflow.py:385–388`，关联 `app/go_validation/runner.py:30–35`。

默认执行器只收到 validation_timeout，_remove 继续固定 wait_for(...,15)；新的 cleanup_timeout 配置没有运行时使用者。实测 cfg.cleanup_timeout=0.001，运行生产 Docker 适配器（仅替换 OS 子进程），实际三次 wait_for 上限为 [90,90,15]，模拟清理用时 30ms 仍 passed。总任务超时触发取消后 runner 又 shield 等待清理，故 360s 不是包含清理的总墙钟上界；当前日志只写清理 ≤15s，没有实现配置的收紧或预留。需传递清理上限，明确从统一截止时间中预留清理预算或明确单独的有界收尾规则，仍需确认容器删除结果。

证据：`cleanup-probe.txt`，`test_configured_cleanup_budget_reaches_docker_adapter` 实际失败。此证据是进程替身，不能算作真实 Docker 故障实验。

## R7 [P2] 带说明文字的 JSON 提取漏掉末尾右括号（T07/T10）

位置：`app/agents/role_runtime.py:47–50`。

非围栏回退分支把 rfind("}") 当作切片的排除式 end，text[start:end] 会丢掉右括号。有效输出如 `说明：{"verdict":"approve"}\n结束` 因此稳定抛 JSONDecodeError，计划/审查会浪费唯一共享重试并最终失败，与函数声明支持前后说明文字不一致。需包含闭括号，或使用 JSONDecoder.raw_decode 提取完整对象，并覆盖纯 JSON、围栏和说明包裹三种情况。

证据：`probes.txt`，`test_json_surrounded_by_prose_can_be_parsed` 实际 ERROR。

## 本次实际验证与边界

所有命令、退出码、时间和原始输出摘要在 `commands.json`。重新执行脚本：`.venv/bin/python docs/evidence/review-s2s4-20261017/run_review.py`；真实 Docker 专项加 `--docker`。脚本强制禁用 dotenv/模型凭据，使用 S0.1 的 DNS/TCP 拦截器；Docker 使用 Unix socket 和本地固定镜像。审查只读源码，新增审查证据与执行记录。

| 类别 | 本次结果 |
| --- | --- |
| 已有离线测试 | 212 passed、24 skipped、132 subtests passed；3 条原有 jieba SyntaxWarning；退出 0 |
| 审查反例（模型/验证/进程替身） | 首批 7 项：6 FAIL、1 ERROR；追加清理探针：1 FAIL；均是预期行为断言未满足的产品缺陷证据，非验收通过 |
| 真实 Docker + 模型替身 | test_multi_agent_workflow.py 共 16 passed、0 skipped，其中 14 项是替身验证，2 项实际执行 Docker（首次通过、失败修复通过）；退出 0 |
| Docker 环境 | Server 29.7.2 linux/arm64；镜像 sha256:381dd0955d9414dc0debedafb6201a28d4da15b32ce0883310a5e4430fa2d4af；结束后 airobot-go-* 容器数 0 |
| 真实模型/Embedding 评测 | 未运行；无累计费用上限，无模型网络请求 |
| 其他检查 | git diff --check 通过；审查前后源码指纹一致；网络拦截审计 0 事件 |
| 未运行 | 本次未重跑原有 22 项真实 Docker 专项、远程 CI、Python 3.11、浏览器与后续 S5 接口验收 |
| 环境阻塞 | 本次所需检查无环境阻塞；Docker 使用已授权沙箱外本地执行 |

没有把历史 S2/S3/S4 数字计作本次结果。历史记录“67 项 OK”实际原文为 Ran 67 / skipped=2，应读作 65 通过、2 跳过；24 个离线 Docker skip 中 2 个是 S3/S4 新增闭环，而非全部原有。历史 S2/S3/S4 缺少完整源码/未提交差异指纹，不能只凭相同 HEAD 把其结果绑定到当前代码，本次已独立重跑并记录指纹。
