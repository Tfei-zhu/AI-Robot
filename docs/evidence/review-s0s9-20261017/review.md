# S0–S9 完成后代码审查（2026-10-17）

结论：确认 **1 项 P1、4 项 P2**，当前版本不宜据现有全绿测试认定整体验收通过。审查没有修改 app、sandbox、eval、tests、前端或配置，仅新增本目录证据并追加执行记录；未调用收费模型。

## 版本与范围

- 工作区：`AI-Robot-latest`，HEAD `1ea7e6b7abbde3bd1a5963f03cd142fac553685a`，main，包含原有大量未提交改动。
- 审查前后源码清单均为 `b0a72a1788389b3c883e50a7fa42fe56c5e0be4e13a8bbd947834badb8d77709`，与 S9 最终版本相同；逐文件清单见 source-before.json / source-after.json。清单排除证据和执行记录。
- 阅读实际 HTTP/Service/图入口、角色/预算/上下文账本、契约门禁、Docker 验证器、存储/取消、Dashboard、评测预算与评分、CI 配置及相关测试。未声称穷尽全部缺陷。
- 使用真实 `.venv` Python 3.13、真实 tiktoken 缓存；禁 dotenv/模型凭据/追踪，离线 guard 阻止 TCP/DNS，仅允许本地 Docker Unix socket。上下文 enforce 探针使用隔离的合成校准配置以进入错误处理分支，不代表实际供应商计数已校准。

## R1 [P1] 沙箱没有确认服务端验收测试实际执行

位置：`sandbox/go/runner.go:159–186`（尤其 186）；新流程通过 `app/agents/go_workflow.py:75` 信任这份四阶段报告。

`testEvents` 只要求至少一个测试、run/pass 数量相等、没有 skip 和包 pass，没有检查服务端必需测试集合。生成包可在 `init` 中修改 `os.Args` 的测试筛选参数，仅执行自己的无效断言测试；服务端验收文件及 hash 完全不变。AST 策略允许这段源码。

真实 Docker + 实际 Service/图 + 固定角色复现：错误实现 `WaitForCancel` 直接返回 nil，测试事件只包含 `TestOnlyModel`，零个 TestServer 测试，却得到 `multi-v1 / passed`，完整四阶段退出码为零，容器已清理。主角色 approve 是固定响应，用于证明机器门禁不能独立阻挡错误认可，非真实模型攻击成功率结论。

配对对照仅删除测试筛选篡改，同一错误实现执行三个服务端测试并返回 failed。两次均真实 Go 1.26.2 / Docker，镜像 ID `sha256:381dd0955d9414dc0debedafb6201a28d4da15b32ce0883310a5e4430fa2d4af`。

证据：docker_probe.py、sandbox-probe.txt（预期保障断言失败）、sandbox-selection-result.json；sandbox-control.txt、sandbox-control-result.json（对照成功）。这是沿用验证器的潜在缺陷，在新流程仍可触发，不是此前 R1–R7 修复回退。

建议：可信验证侧持有必需验收测试集合，逐项校验实际执行/通过/唯一性，缺失一项即失败；限制不可信包干预测试入口和筛选，补运行时篡改与测试事件伪造反例。不能只靠源码 hash、提示词或增加一条黑名单宣称完整解决。

## R2 [P2] JSON 客户端断线未触发取消

位置：`app/main.py:222–230`。

普通 JSON 路由只 await Service，没有监听 `http.disconnect`。现有 JSON 中断测试调用的是 `job.cancel()`，这不是客户端断线；SSE 才使用真实 disconnect 事件。

实际 ASGI 探针在计划等待期间发出 `http.disconnect`，随后允许固定模型返回。断线事件始终未被消费，任务仍继续代码生成、验证和审查，最后 passed，3 次模型请求、1 次验证。真实部署可在客户端已放弃后继续计费并占用容量至完成/超时。

证据：probes.py::test_json_disconnect_stops_work；json-disconnect.json；probes-final.txt/xml。

建议：JSON 入口并行监测断线并取消/等待业务任务，保留已有清理及落库保证；用真实 ASGI disconnect 验证 JSON 与 SSE，不能以手动取消服务端 task 替代。

## R3 [P2] 断线可覆盖已持久化终态

位置：`app/go_validation/service.py:123–128`，无条件赋值 cancelled。

`go_progress` 的 finish 快照已落库 passed 后，客户端在 go_done 前关闭流，GeneratorExit 分支仍无条件保存 cancelled。复现中读取数据库前值为 passed，关闭后为 cancelled，stop_reason=cancelled，final_summary 却仍为“符合需求”。这违反已结束任务不可改写的契约，并导致查询结果取决于网络发送时机。

证据：probes.py::test_disconnect_after_persisted_success_does_not_rewrite_terminal；terminal-rewrite.json。该探针直接关闭真实 Service 生成器，与 HTTP StreamResponse 断线后的 aclose 收尾路径相同；未冒称外部浏览器测试。

建议：把业务终态与响应传输状态分开；收尾先取得最新结果，只取消仍 running 的任务，保存已完成终态。补终态已落库、go_done 未送达时断线及重复取消的边界。

## R4 [P2] 修复消息遗漏需求失败证据

位置：`app/agents/code_agent.py:67–84`。

审查协议允许 verdict=revise、requirement_checks 中有 fail/unknown、issues=[]，路由会创建修复任务。但 `_repair_user` 只渲染 issues，丢掉 requirement_checks、verdict、summary。复现中主角色给出明确失败定位和原因，子 Agent 收到的修复消息却写“审查发现的问题：无”，失败证据和总结均不存在。即使 issues 不为空，未重复放入 issues 的需求失败仍丢失。

证据：probes.py::test_failed_requirement_evidence_reaches_repair；repair-feedback.json（完整审查与实际发出的修复提示词）。测试不以脚本模型最终结果证明真实修复能力。

建议：交接所有未通过必要需求的 ID、状态与证据，以及审查结论和可执行修复指令；或者校验每个失败需求必须有相应阻断项，并有界重试不完整审查。不能把“无 issues”解释成没有失败原因。

## R5 [P2] 全局上下文预检错误被重试并虚增实际调用数

位置：`app/agents/role_runtime.py:135–149`；触发源 `app/context/usage.py` 的 invoke 发送前 check。

当 CONTEXT_MODE=enforce，角色额度检查允许输入但全局上下文额度拒绝时，`ContextBudgetExceeded` 在 `model.ainvoke` 之前抛出。通用异常分支仍记录 failed AgentCall，转成可重试的 AgentError。最终实际模型发送 0 次、UsageLedger 0 次，结果却为 generation_error、model_calls=2，耗尽共享异常重试1次，预算model=2。这是全局上下文与新角色预算组合路径的错误分类/计数缺口。

证据：probes.py::test_context_preflight_failure_is_not_a_sent_call；context-preflight.json。输入上限1用于确定性触发，任意因完整源码长度超过全局上限的正常任务也走同一分支。

建议：统一发送前预算检查/异常类型；上下文拒绝应传播为 budget_exceeded，不重试，不制造已经发送的调用记录。预占额度与实际发送数继续分别报告。

## 本次验证

| 检查 | 本次结果 |
| --- | --- |
| 完整离线 pytest tests | 301 passed，63 skipped，138 subtests passed；跳过项均为未开启 Docker |
| 完整 AIROBOT_TEST_DOCKER=1 pytest tests | 364 passed，0 skipped，140 subtests passed，186.33 秒；不是364个独立Docker场景 |
| 新增最终 Python 边界探针 | 4 failed，分别对应 R2–R5；保留失败未放宽断言 |
| 新增真实 Docker/Service 绕过探针 | 保障断言失败，错误代码被误放行，对应 R1 |
| 真实 Docker 配对对照 | 正确检出同一错误实现，failed 业务状态；检查脚本退出0 |
| git diff --check | 通过 |
| Docker 残留检查 | 测试完成后带 airobot.go-validation=true 标签容器为零 |
| 源码前后 | 指纹相同；业务源码未修改 |
| 收费模型、远程CI、Python3.11、浏览器 | 本轮未执行 |

3 条 jieba SyntaxWarning 为既有依赖警告。最初 probes.txt 包含先写的3个探针，最终以 probes-final.txt/xml 的4个为准，不把两轮重复累计为7个不同问题。所有测试脚本、命令参数/时间/退出码/输出摘要均保留在本目录。

复现入口：`.venv/bin/python docs/evidence/review-s0s9-20261017/run_review.py probes-final`、同脚本 `sandbox-probe` / `sandbox-control`；后两项需要已有固定 Docker 镜像与引擎。复跑当前 recorder 会覆盖本目录同名输出，复验请复制到新的证据目录或改用新标签，保留本次原始结果。

## 已知缺口，未重复计作隐藏 bug

S9 自身记录的是 T01–T28 中24项完成、2项待验证（T05/T28）、2项阻塞（T26/T27）。澄清/拒绝路径仍缺可达实现；真实模型质量、费用配置、远程CI及外部服务联机未验收。完成 S0–S9 的本地执行记录不等于这些门槛已通过。建议先修 R1，再闭合 R2/R3 生命周期和 R4/R5；修复后的全量回归必须同时纳入本次反例，之后再推进剩余交付门槛。
