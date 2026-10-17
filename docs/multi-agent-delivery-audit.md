# S9 逐项交付核对

状态范围：**完成**指对应代码和本地机制证据具备，**待验证**包含明确实现缺口或未执行的交付门槛，**阻塞**指缺外部授权/配置。完成不等于真实模型效果已证实，也不把报告保存解释为恢复执行。代码/依赖清单见 [S9 证据](evidence/s9-20261017/)，本轮机器解析的最终节点与结果见 [delivery-status.json](evidence/s9-20261017/delivery-status.json)。原计划定义不改变，以下状态取代“初始待执行”。

## T01～T28

| 编号 | 原任务 | 当前状态 | 实际代码/证据与边界 |
| --- | --- | --- | --- |
| T01 | 固定提交、依赖版本、当前测试结果和 Docker 可用性 | **完成** | 。基线/依赖/提交/未提交差异、Python 和 Docker 均有实际快照；本轮环境另存。 |
| T02 | 检查旧目录的 multi_agent.py 和相关测试，逐项判断复用 | **完成** | 。旧目录只读复用分析已记录，未整文件覆盖或修改旧目录。 |
| T03 | 确定第一版角色、三个场景、接口及运行边界 | **完成** | `app/go_validation/fixtures.py`、`app/go_validation/contracts.py`。固定三场景、标准库/单包、Go 专用入口。 |
| T04 | 定义 TaskSpec、CodeArtifact、ReviewReport、RepairRequest | **完成** | `app/go_validation/contracts.py`。任务/产物/审查/修复类型、长度、关联 ID 校验。 |
| T05 | 定义状态及确定性路由规则 | **待验证** | `app/agents/go_workflow.py`。成功/修复/预算/异常路由已有防线；clarification_needed 仅枚举，标准闭环缺可达路径，完整状态设计未完成。 |
| T06 | 定义角色配置、共享预算、超时和开关 | **完成** | `app/config.py`、`.env.example`、`app/agents/go_workflow.py`。非法配置启动拒绝；发送前共享调用额度和截止时间。 |
| T07 | 实现主 Agent 的任务分解与委派 | **完成** | `app/agents/supervisor.py`。原需求服务端锚定、固定接口；固定模型证明结构与交接，不能证明任意语义识别。 |
| T08 | 封装代码子 Agent 和任务内状态 | **完成** | `app/agents/code_agent.py`。独立上下文/完整源码生成修复；不是普通聊天自动派工。 |
| T09 | 复用围栏代码解析、产物校验和服务端验收测试注入 | **完成** | `app/go_validation/nodes.py`、`app/go_validation/fixtures.py`、`app/agents/code_agent.py`。复用解析和产物边界；服务器测试不可改，模型测试可修复。 |
| T10 | 实现主 Agent 审查提示词及结构化输出 | **完成** | `app/agents/supervisor.py`、`app/go_validation/contracts.py`。结构化需求检查与定位、阻断/建议、实际源码和机器报告。 |
| T11 | 建立最小上下文交接与产物版本校验 | **完成** | `app/agents/role_runtime.py`、`app/go_validation/contracts.py`。完整必要源码/服务端 hash；不能重标历史验证。输入计数是估计，非精确供应商 token 硬上限。 |
| T12 | 接入主图和 Go 子流程，保留选择入口 | **完成** | `app/agents/graph.py`、`app/agents/go_workflow.py`。图运行时选择 Go 新/旧路径，普通聊天原路由不变。 |
| T13 | 接入现有 Docker 验证器与错误分类 | **完成** | `app/go_validation/runner.py`、`app/agents/go_workflow.py`。真实 Docker；代码失败可审查修复，环境不可用终止。 |
| T14 | 实现修复任务及问题状态跟踪 | **完成** | `app/agents/code_agent.py`、`app/agents/go_workflow.py`、`app/go_validation/contracts.py`。保留问题 ID、修复请求和各轮审查；addressed_issue_ids 表示交给修复的阻断项，不是自动证明已解决。 |
| T15 | 实现调用预算、截止时间和无进展停止 | **完成** | `app/agents/go_workflow.py`、`app/go_validation/service.py`、`app/context/usage.py`。失败/解析重试也扣额度；取消和同失败 hash 无进展停止。 |
| T16 | 扩展 GoTaskService 的角色注入和结果组装 | **完成** | `app/go_validation/service.py`。角色模型/检索/runner 独立注入及结果组装。 |
| T17 | 扩展 JSON/SSE 数据与阶段事件 | **完成** | `app/main.py`、`app/go_validation/service.py`、`app/go_validation/contracts.py`。JSON 消费同一 stream；六种业务终态一致，HTTP 200 不作标签。 |
| T18 | 保存任务计划、代码版本、审查与修复历史 | **完成** | `app/go_validation/store.py`、`app/go_validation/contracts.py`。报告保存、旧字段默认及账户隔离；没有执行断点恢复。 |
| T19 | 完善取消、异常及清理后的持久化 | **完成** | `app/go_validation/service.py`、`app/go_validation/runner.py`。各阶段取消/超时保留产物与调用，清理/落库后释放占用；强杀进程不承诺最终保存。 |
| T20 | 展示主 Agent 委派与子 Agent 工作阶段 | **完成** | `app/static/dashboard.html`、`scripts/test_multi_agent_dashboard.cjs`。实际阶段、角色、轮次和 run_id；S6 真实浏览器历史证据，S9 未重新运行浏览器。 |
| T21 | 展示审查问题、代码差异、预算和最终结论 | **完成** | `app/static/dashboard.html`、`scripts/test_multi_agent_dashboard.cjs`。审查/预算/文件文本差异/终态与旧报告展示；S6 将响应替换与真实后端固定模型+Docker 分开记录。 |
| T22 | 编写正常与失败闭环的离线测试 | **完成** | `tests/test_multi_agent_workflow.py`。首次通过、修复通过、耗尽、无进展和环境终止。 |
| T23 | 编写审查可信性与契约测试 | **完成** | `tests/test_multi_agent_review.py`、`tests/test_multi_agent_contracts.py`。错误 approve/旧 hash/可信测试/必要条目反例，S7 五处定向失效已检出并恢复。 |
| T24 | 验证 API 一致性、账户隔离、取消和预算 | **完成** | `tests/test_multi_agent_http.py`、`tests/test_multi_agent_budget.py`。真实 ASGI/SQLite 账户/会话/取消/限额；模型与部分 runner 是替身，真实 Docker 节点另列。 |
| T25 | 运行真实 Docker 验收和原业务回归 | **完成** | `tests/test_go_acceptance.py`、`tests/test_multi_agent_regressions.py`。本地真实 Docker 和原业务代码回归；外部 Go API/AMQP/Milvus 联机与远程 CI 未验证。 |
| T26 | 固定对照数据、评分规则和费用上限 | **阻塞** | `eval/multi_agent_protocol.py`、`eval/multi_agent_live_cases.jsonl`、`eval/multi_agent_live_protocol.json`。v1 机制协议和 v2 分组候选/独立评分已固定；真实模型配置、金额、币种/价格未冻结，缺用户累计费用上限。 |
| T27 | 执行固定模型测试及有预算的真实模型评测 | **阻塞** | `eval/run_multi_agent_eval.py`。固定模型 120 次/312 调用的旧机制对照已保存；真实模型未运行，v2 没有质量成绩，不能宣称改善。 |
| T28 | 整理结果、更新操作说明、演练开关回退 | **待验证** | `docs/multi-agent.md`、`README.md`、`.github/workflows/ci.yml`、`scripts/check_multi_agent_rollback.py`。本地文档、真实开关关闭和旧报告/聊天演练完成；远程 CI 未运行，T26/T27 未完成，整体推广门槛不通过。 |

28 项中 24 项完成、2 项待验证（T05/T28）、2 项阻塞（T26/T27）。T14 的 addressed_issue_ids 是交给修复的任务记录，是否解决仍看当前源码/机器验证/新审查，不能以该字段自证。每项精确测试选择器、既有证据路径和本轮匹配节点保存于机器结果；缺失/跳过/失败不能记作通过。

## A01～A18

以下“完成”限于验收矩阵定义的本地机制。S7/S8.1 已有实际通过证据，本轮按相同选择器重新解析完整 JUnit；若复验不通过，机器结果不会将该行标为完成。A03 的补充需求案例和 A10 的权限边界都不证明真实模型具有通用识别或抗注入能力。

| 编号 | 验收场景 | 状态 | 证据类型/限制 |
| --- | --- | --- | --- |
| A01 | 首次通过，仅一次生成 | 完成（本地机制） | 固定模型；第二项真实 Docker |
| A02 | 真实编译错误回传，修复后重新验证/审查 | 完成（本地机制） | 固定模型 + 真实 Docker；保留 real-compile-result.json |
| A03 | 机器通过仍缺必要需求，补测后再审 | 完成（本地机制） | 模型与验证替身；检查需求 ID、修复输入、新测试/hash 和复审 |
| A04 | 两轮修复耗尽，保留三个版本 | 完成（本地机制） | 模型与验证替身；7 次底层请求、3 份验证 |
| A05 | approve 不能覆盖失败验证或阻断问题 | 完成（本地机制） | 纯契约/服务端和模型、验证替身；失效检查 machine-gate；真实编译失败即使 approve 仍修复 |
| A06 | 旧源码、hash、轮次或任务错配不能通过 | 完成（本地机制） | 服务端与固定组件；失效检查 review-hash |
| A07 | 拒绝可信测试改写；削弱模型测试不能绕过 | 完成（本地机制） | 含三个场景真实 Docker 弱测试反例；失效检查 trusted-test |
| A08 | 审查非法/无法判断有界重试；超时明确终止 | 完成（本地机制） | 模型与验证替身；覆盖 review+timeout 参数。角色超时直接 timeout，非法/无法判断共享重试一次 |
| A09 | 只有建议可通过，不强制修复 | 完成（本地机制） | 纯服务端门禁；浏览器展示沿用 S6 证据，S7 当时未重跑浏览器 |
| A10 | 恶意资料/日志/模型权限声明不改变服务端 | 完成（本地机制） | 固定恶意输入 + 真实 Docker 权限；只证明权限/预算/终态机制，不证明真实模型抗注入能力 |
| A11 | Docker 不可用/异常直接终止，不进入修复 | 完成（本地机制） | 故意模拟缺失/异常；本机 Docker 可用另有实证 |
| A12 | 各阶段取消/超时，保留报告、清理、释放占用 | 完成（本地机制） | 计划/检索新增 8 项 + 生成/审查/沙箱/修复生成 16 项中断；排队/首事件关闭/重复取消/落库与清理占用；4 个真实 Docker HTTP 中断；失效检查 cancel-propagation |
| A13 | 失败/解析/重试计数，发送前禁止超额 | 完成（本地机制） | 固定客户端捕获实际 8 请求；第 9 次在发送前预占处拒绝；低总额也独立生效；失效检查 total-budget |
| A14 | JSON/SSE 业务结果与最终事件一致 | 完成（本地机制） | 六种业务状态的真实 ASGI+SQLite（模型、验证替身），以及旧流程真实 Docker；HTTP 200 不等于 passed |
| A15 | 跨账户不可读、相同会话并发隔离与占用 | 完成（本地机制） | 真实 ASGI、SQLite，固定角色响应；409/404 与取消后同会话再运行均检查 |
| A16 | 旧 JSON 样本升级读取补默认值 | 完成（本地机制） | 9 个已有历史原始报告直接写库重开，真实 GET；S6 浏览器为历史证据 |
| A17 | 相同失败代码及时停止 | 完成（本地机制） | 模型与验证替身；2 次验证后 no_progress，不发第三轮生成 |
| A18 | 开关关闭保持旧 Go 与原问答/文章路径 | 完成（本地机制） | 旧 Go 真实 Docker；问答/检索/文章/消费者等真实应用代码、外部服务替身；另执行离线 Agent 六场景；S9 另以环境变量 false 新进程，11 次真实 Docker 验证、9 份旧报告+1 份既有 multi-v1 重开读取，六个聊天案例 |

选择器原文见 [A 矩阵](multi-agent-acceptance-matrix.md)；本轮完整匹配节点以 [delivery-status.json](evidence/s9-20261017/delivery-status.json) 为准。S7 定向失效结果保留为历史证据，不宣称 S9 再做失效。没有把隔离副本中的预期失败混入正常版本通过数。

## 各类证据分开报告

| 类别 | 已知事实 | 仍未验证 |
| --- | --- | --- |
| 本地测试 | S9 显式关闭开关演练已实际通过；完整 pytest 复验、JUnit 统计及版本绑定见机器结果 | 本地不是 Python 3.11/远程 runner 结果 |
| 固定模型 | S9 回退 8 个任务、11 次 Go 模型调用和 11 次真实 Docker 验证；聊天六案例调用17次，均为非计费替身；S8 v1 完整对照 120 次/312 调用保留 | 不代表真实生成/审查能力；v2 无模型成绩 |
| 真实 Docker | S9 回退真实四阶段执行，源码/日志与清理确认已保存；完整 suite 中 Docker 项也实际启用 | Go race/全部并发输入无证明；第三方依赖/任意仓库不支持 |
| 浏览器 | S6 保存 Chromium、截图、响应替换和真实 ASGI 后端+固定模型/Docker 分列结果，当前 UI 源码没有变化 | S9 未重新运行浏览器；没有真实模型浏览器成绩 |
| 远程 CI | 已配置完整 Docker、离线回归和回退检查；移除存在 Secrets 就自动收费评测的路径，本地校验配置 | **未运行**；没有当前未提交版本的远程成功结论 |
| 真实模型 | **0 请求，阻塞**：未获得累计费用上限，缺固定版本/窗口/价格和持久账本配置 | 成功率、真实 Token/费用/推理延迟全部未知；未知不作零 |
| 外部业务联机 | 原问答/文章/检索/消费者代码的替身回归可运行 | 实际 Go API/AMQP/Milvus 本轮未连接 |

旧条件留出四组都为25%，不支持改善或推广；开发多 Agent 原样组同时使用更多调用，不能归因于多 Agent。v1 条件数据有重复/跨集基础需求，v2 按15族分集但仍为三个API上的人工相关任务，不宣称泛化代表性。整体 enablement.passed=false，保持默认关闭。

[可运行位置、配置与回退方法](multi-agent.md)列出当前实现能力。主要剩余项：正式澄清/拒绝路径未实现；真实模型和费用授权不足；远程 CI/外部服务联机未验证；没有执行恢复、普通聊天自动委派、跨进程协调。归档清单覆盖当前未提交源码，HEAD 单独不足以复现。
