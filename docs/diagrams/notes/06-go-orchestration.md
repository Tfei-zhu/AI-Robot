Go 专用任务由服务端按开关选择 **旧流程 `single-v1`** 或 **多智能体流程 `multi-v1`**；默认关闭多智能体，验证器始终是工具，最终成功由服务端判定。

以下基于当前源码，未修改代码、未读取 `.env`。实线表示执行顺序，虚线表示事件或异常后的恢复路径，粗线表示报告保存。

---

**主图：配置分支、旧 Go 流程与公共收尾。**

<!-- readme-diagram:06-go-orchestration-01 -->
![Go 专用任务的两条分支](../png/06-go-orchestration-01.png)

<details>
<summary>展开原始完整流程</summary>

```mermaid
flowchart TB
    go_entry["Go 专用请求<br/>已通过鉴权、参数校验与会话占用"]
    go_service["GoTaskService<br/>创建 run_id、原始需求与截止时间<br/>保存初始 running 报告，产生 go_start<br/>在超时范围内等待 Semaphore(2)"]
    go_switch{"LangGraph 入口<br/>go_multi_agent.enabled？<br/>默认 false"}

    subgraph single_flow["旧 Go 流程：single-v1，默认"]
        single_retrieve["go_retrieve<br/>检查模型配置<br/>可用时检索一次参考资料<br/>无 Embedding 或检索失败时使用空资料"]
        single_running{"状态仍为 running？"}
        single_model_budget{"累计模型调用是否小于 3？"}
        single_generate["go_generate<br/>同一模型生成或修复完整代码与测试<br/>修复输入包含上轮代码与验证报告<br/>本节点最多尝试 2 次，计入总额度 3 次"]
        single_output{"调用、代码解析及固定测试处理<br/>是否成功？"}
        single_tool_budget{"go_tools 是否小于 4？"}
        single_validate["go_validate<br/>validate_go_code → DockerGoRunner<br/>执行固定沙箱验证并保存 Attempt"]
        single_validation{"验证结果"}
        single_repair{"仍为 failed 且<br/>本次后验证次数小于 3？"}
        single_finish["go_finish → END<br/>保留实际终态"]
        single_generation_error["generation_error"]
        single_budget_error["budget_exceeded"]
    end

    multi_entry["多智能体 multi-v1<br/>进入下一张图"]
    report_finish["GoTaskService 公共收尾<br/>等待工作流清理，释放已取得的执行槽<br/>整理最终 GoTaskResult"]
    go_store[("GoTaskStore<br/>校验并保存账户隔离的完整报告")]
    go_response["记录近期 traces<br/>产生 go_done<br/>JSON：run() 消费事件后返回报告<br/>SSE：逐条推送事件"]

    go_entry --> go_service
    go_service --> go_switch
    go_switch -->|"false：默认"| single_retrieve
    go_switch -->|"true：显式启用"| multi_entry

    single_retrieve --> single_running
    single_running -->|"否：例如缺模型配置 unavailable"| single_finish
    single_running -->|"是"| single_model_budget
    single_model_budget -->|"是"| single_generate
    single_model_budget -->|"否"| single_budget_error
    single_generate --> single_output
    single_output -->|"失败"| single_generation_error
    single_output -->|"成功"| single_tool_budget
    single_tool_budget -->|"否"| single_budget_error
    single_tool_budget -->|"是"| single_validate
    single_validate --> single_validation
    single_validation -->|"passed"| single_finish
    single_validation -->|"unavailable / timeout / cancelled"| single_finish
    single_validation -->|"failed"| single_repair
    single_repair -->|"是：最多两次修复"| single_model_budget
    single_repair -->|"否：维持 failed"| single_finish
    single_generation_error --> single_finish
    single_budget_error --> single_finish

    %% 旧流程没有 SupervisorAgent、需求评估或模型审查门禁。
    single_finish --> report_finish
    multi_entry -->|"返回终态报告"| report_finish
    report_finish ==> go_store
    go_store --> go_response

    %% 外层取消会清理并保存 cancelled 后重新抛出，不保证产生 go_done。
```

</details>

旧流程首次追加服务端验收测试，修复时保留首轮的固定验收文件；模型自己的测试可以更新。生成重试会消耗三次模型总额度，因此不保证一定有足够额度完成两次修复。

两种流程只属于 Go 专用入口。普通聊天没有 `go_request`，不会进入这些分支。

源码：[graph.py:272](../../../app/agents/graph.py#L272)、[service.py:76](../../../app/go_validation/service.py#L76)、[nodes.py:65](../../../app/go_validation/nodes.py#L65)、[nodes.py:94](../../../app/go_validation/nodes.py#L94)、[nodes.py:191](../../../app/go_validation/nodes.py#L191)。

---

**多智能体图：两个角色由服务端顺序驱动，验证工具不参与角色决策。**

<!-- readme-diagram:06-go-orchestration-02 -->
![多智能体：两个角色顺序协作](../png/06-go-orchestration-02.png)

<details>
<summary>展开原始完整流程</summary>

```mermaid
flowchart TB
    subgraph server_control["服务端控制逻辑：MultiAgentGoWorkflow"]
        multi_entry["run_in_graph<br/>检查模型配置，创建两个角色与共享预算<br/>沿用服务层绝对截止时间"]
        plan_reserve["预占正常模型调用额度<br/>计算主智能体阶段时限"]
        plan_contract["解析 PlanningOutcome 并校验契约<br/>服务端绑定 run_id、原始需求、场景<br/>模型不能修改固定接口或新增服务端权限"]
        assessment{"assessment.decision"}

        clarify_end["clarify<br/>必须有原文证据和可回答的问题<br/>task_spec=null<br/>failed / clarification_needed"]
        unsupported_end["unsupported<br/>必须有能力冲突证据与已知约束<br/>questions 为空，task_spec=null<br/>failed / clarification_needed"]

        retrieve["proceed 后才检索<br/>无检索函数则跳过<br/>有检索函数先预占检索额度<br/>检索失败使用空参考资料继续"]
        generate_reserve["预占正常模型调用额度<br/>计算代码角色阶段时限"]
        freeze_artifact["服务端解析并冻结产物<br/>追加不可修改的验收测试<br/>计算完整源码 artifact_hash<br/>首次 round=0，修复逐轮增加"]
        validate_reserve["预留清理时间并预占验证额度<br/>限制本轮执行时长"]
        bind_report["bind_validation 绑定当前版本<br/>保存本轮 Attempt"]
        environment_result{"验证报告是否为<br/>unavailable / timeout / cancelled？"}

        review_reserve["预占正常模型调用额度"]
        review_contract["解析与校验 ReviewReport<br/>非超时调用失败或输出无效时得到 None<br/>必要需求覆盖等交由判定函数检查"]
        server_decision["decide_after_review<br/>使用当前产物、机器报告、审查报告<br/>以及服务端剩余预算<br/>具体分支见下一张图"]
        review_retry["预占全任务共享重试额度<br/>仅重做当前版本审查"]
        repair_request["创建并校验 RepairRequest<br/>携带原需求、完整源码、真实日志<br/>审查问题与修复指令<br/>预占修复额度和正常模型调用额度"]

        role_failure["计划或代码调用失败 / 输出无效<br/>非超时错误：服务端尝试原阶段重试<br/>占用全任务唯一共享重试额度<br/>超时不重试；具体终态见表"]
        multi_stop["终止并构造实际状态报告<br/>failed / generation_error / budget_exceeded<br/>timeout / unavailable / cancelled"]
        multi_passed["passed / completed<br/>构造报告时再次校验成功证据"]
    end

    subgraph supervisor_role["主智能体：SupervisorAgent"]
        supervisor_plan["plan<br/>同一次模型调用完成需求评估与任务规划<br/>输出 assessment 与 task_spec"]
        supervisor_review["review<br/>读取 TaskSpec、当前完整源码<br/>以及实际机器验证报告<br/>逐条审查必要需求并给出问题"]
    end

    subgraph code_role["代码智能体：CodeAgent"]
        code_generate["generate<br/>根据 TaskSpec 与参考资料<br/>生成完整实现和测试"]
        code_repair["repair<br/>处理当前审查问题并提交完整新版本<br/>复用首次参考资料，不重新检索"]
    end

    subgraph validation_tool["验证工具：不是智能体"]
        go_validator["DockerGoRunner<br/>固定 Go 1.26.2 隔离容器<br/>policy → compile → vet → test<br/>返回机器报告并确认容器清理"]
    end

    multi_entry --> plan_reserve
    plan_reserve --> supervisor_plan
    supervisor_plan --> plan_contract
    plan_contract -->|"合法"| assessment
    plan_contract -->|"输出无效"| role_failure
    supervisor_plan -->|"调用失败或超时"| role_failure

    %% clarify 与 unsupported 都立即结束，不挂起等待用户。
    assessment -->|"clarify"| clarify_end
    assessment -->|"unsupported"| unsupported_end
    clarify_end --> multi_stop
    unsupported_end --> multi_stop
    assessment -->|"proceed：必须有合法 TaskSpec"| retrieve

    retrieve --> generate_reserve
    generate_reserve --> code_generate
    code_generate --> freeze_artifact
    code_repair --> freeze_artifact
    code_generate -->|"调用失败或超时"| role_failure
    code_repair -->|"调用失败或超时"| role_failure
    freeze_artifact -->|"解析或冻结失败"| role_failure
    freeze_artifact -->|"合法产物"| validate_reserve

    %% 每次代码变化都重新验证，不能复用上一版本报告。
    validate_reserve --> go_validator
    go_validator --> bind_report
    bind_report --> environment_result
    environment_result -->|"是：不进入代码修复"| multi_stop
    environment_result -->|"否：passed 或 failed"| review_reserve
    review_reserve --> supervisor_review
    supervisor_review --> review_contract
    review_contract --> server_decision

    server_decision -->|"passed"| multi_passed
    server_decision -->|"finish：其他终态"| multi_stop
    server_decision -->|"retry_review"| review_retry
    review_retry --> supervisor_review
    server_decision -->|"repair"| repair_request
    repair_request --> code_repair

    %% 原阶段重试包含该阶段的解析与契约检查，成功后返回原流程。
    role_failure -.->|"计划重试成功"| assessment
    role_failure -.->|"生成或修复重试成功"| validate_reserve
    role_failure -->|"无法重试、再次失败或超时"| multi_stop

    %% 所有额度预占、输入预算和时限检查均可能直接终止，不重复绘制异常边。
    classDef agent fill:#eef5ff,stroke:#5279a4,color:#172b4d;
    classDef tool fill:#eef8eb,stroke:#618950,color:#25401c;
    class supervisor_plan,supervisor_review,code_generate,code_repair agent;
    class go_validator tool;
```

</details>

这里有三个关键顺序：

- **先评估与规划，再检索。** 当前首次计划收到的参考资料为 `[]`；检索结果用于后续代码生成，修复复用已有资料。
- **机器验证失败也可以进入审查。** 只有验证环境不可用、验证超时或取消会直接结束，不让模型修复基础设施。
- **`clarify` 与 `unsupported` 都是当前任务终态。** 用户补充需求后需重新提交，生成新的 `run_id`；没有自动等待回复或恢复执行。

源码：[go_workflow.py:334](../../../app/agents/go_workflow.py#L334)、[go_workflow.py:358](../../../app/agents/go_workflow.py#L358)、[go_workflow.py:473](../../../app/agents/go_workflow.py#L473)、[supervisor.py:102](../../../app/agents/supervisor.py#L102)、[code_agent.py:87](../../../app/agents/code_agent.py#L87)。

---

**服务端判定图：先判断能否成功，再判断是否继续修复。**

<!-- readme-diagram:06-go-orchestration-03 -->
![服务端成功与修复门禁](../png/06-go-orchestration-03.png)

<details>
<summary>展开原始完整流程</summary>

```mermaid
flowchart TB
    decision_entry["decide_after_review"]
    time_left{"剩余任务时间是否大于 0？"}
    timeout_end["timeout"]
    artifact_valid{"TaskSpec 与 CodeArtifact 合法<br/>任务和场景匹配？"}
    artifact_error["failed / artifact_error"]
    validation_valid{"验证报告版本绑定正确？<br/>自称 passed 时是否满足完整机器门禁？"}
    validation_error["failed / validation_report_error"]
    validation_environment{"验证状态是否为<br/>unavailable / timeout / cancelled？"}
    environment_end["保留对应终态"]

    review_valid{"审查结构与版本有效？<br/>不是 cannot_assess<br/>覆盖全部必要需求？"}
    review_retry_budget{"共享 retries 大于 0<br/>且总 model_calls 大于 0？"}
    retry_review["retry_review<br/>同版本重新审查，不重新验证"]
    review_error["failed / review_error"]

    success_check{"machine_passed<br/>且 verdict=approve<br/>且必要需求全部 pass<br/>且没有 blocking 问题？"}
    passed_end["passed / completed"]
    same_artifact{"与上一失败产物 hash 相同？"}
    no_progress["failed / no_progress"]
    repair_limit{"当前 round 已达到 max_repairs？<br/>默认最大为 2"}
    repair_end["failed / repair_limit"]
    repair_budget{"剩余总模型调用至少 2<br/>剩余正常模型调用至少 2<br/>剩余验证至少 1？"}
    budget_end["budget_exceeded"]
    repair_next["repair<br/>原因：validation_failed<br/>或 requirements_failed / review_revision"]

    decision_entry --> time_left
    time_left -->|"否"| timeout_end
    time_left -->|"是"| artifact_valid
    artifact_valid -->|"否"| artifact_error
    artifact_valid -->|"是"| validation_valid
    validation_valid -->|"否"| validation_error
    validation_valid -->|"是"| validation_environment
    validation_environment -->|"是"| environment_end
    validation_environment -->|"否"| review_valid

    review_valid -->|"否"| review_retry_budget
    review_retry_budget -->|"有额度"| retry_review
    review_retry_budget -->|"无额度"| review_error
    review_valid -->|"是"| success_check
    success_check -->|"是"| passed_end

    %% 成功优先于修复次数检查；最后一轮仍然可以通过。
    success_check -->|"否"| same_artifact
    same_artifact -->|"是"| no_progress
    same_artifact -->|"否"| repair_limit
    repair_limit -->|"达到"| repair_end
    repair_limit -->|"未达到"| repair_budget
    repair_budget -->|"不足"| budget_end
    repair_budget -->|"足够"| repair_next
```

</details>

多智能体成功需要同时满足：

1. 当前请求有合法的 `proceed` 评估，任务、场景和原始需求绑定一致。
2. 验证与审查对应同一个 `task_id / artifact_id / artifact_hash / round`。
3. `machine_passed`：状态为 `passed`，Go 版本正确，容器已清理；阶段严格为 `policy、compile、vet、test`，全部退出码为 0，日志未标记截断。
4. 审查为 `approve`，所有 `required=true` 的需求检查均为 `pass`，没有 `blocking` 问题。
5. 最终报告保留相符的产物、尝试和审查证据，并通过 `GoTaskResult` 校验；`GoTaskStore.save` 保存时再次执行报告校验。

审查证据是服务端判定的输入，主智能体没有直接把任务状态设置为成功的权限。

源码：[go_workflow.py:76](../../../app/agents/go_workflow.py#L76)、[go_workflow.py:89](../../../app/agents/go_workflow.py#L89)、[contracts.py:261](../../../app/go_validation/contracts.py#L261)、[contracts.py:273](../../../app/go_validation/contracts.py#L273)、[contracts.py:427](../../../app/go_validation/contracts.py#L427)、[store.py:26](../../../app/go_validation/store.py#L26)。

---

**预算与默认配置：**

| 项目 | 旧流程 `single-v1` | 多智能体 `multi-v1` |
|---|---|---|
| 默认选择 | 多智能体开关为 `false` 时使用 | `AIROBOT_GO_MULTI_AGENT_ENABLED=true` |
| 模型调用 | 总计最多 3 次，包含生成重试 | 正常调用默认 7 次；全任务共享异常重试 1 次；总计最多 8 次 |
| 修复与验证 | 最多修复 2 次、验证 3 次，仍受模型额度约束 | 默认最多修复 2 次、验证 3 次，可配置得更低 |
| 检索 | 一个检索阶段；工具计数从 1 开始，含验证最多 4 | 默认最多 1 次；无检索函数时跳过，有函数但额度为 0 时预占失败 |
| 总时间 | 服务层默认 360 秒 | 默认 360 秒，沿用服务层截止时间，排队时间计入 |
| 模型阶段时限 | 单次生成默认 120 秒 | 主角色默认 60 秒，代码角色默认 120 秒，均受剩余时间限制 |
| 验证与清理 | `DockerGoRunner` 默认执行 90 秒、清理 15 秒 | 执行默认最多 90 秒，并在剩余任务时间内预留 15 秒清理额度 |
| 模型输入限制 | 使用旧 Go 上下文适配逻辑 | 角色输入预算始终检查，不依赖实验 `CONTEXT_MODE` 是否开启 |
| 启用前置条件 | 无多角色窗口要求 | 两个角色窗口默认均为 0；开启时必须配置足够窗口，否则配置校验失败 |

正常调用额度 7 次对应：**计划 1 次＋首次生成及审查 2 次＋两轮修复及审查 4 次**。失败请求也消耗预占额度，不返还；共享重试不是每个角色各有一次。

配置和执行依据：[config.py:30](../../../app/config.py#L30)、[go_workflow.py:164](../../../app/agents/go_workflow.py#L164)、[role_runtime.py:118](../../../app/agents/role_runtime.py#L118)。

---

**异常与终止方式：**

| 情况 | 当前实际行为 |
|---|---|
| 计划、生成或修复发生非超时 `AgentError`，包括输出无效 | 服务端尝试预占共享重试额度，原阶段重试一次；重试仍失败为 `generation_error`；无法预占额度为 `budget_exceeded`，截止时间耗尽为 `timeout` |
| 审查调用或输出无效、`cannot_assess`、缺少必要需求检查 | 有共享重试与总模型额度时重审；否则 `failed / review_error`，不会直接生成修复代码 |
| 角色超时或总任务超时 | 多智能体直接 `timeout`，不使用共享重试修复超时 |
| 输入预算或调用、验证、修复额度不足 | `budget_exceeded`；截止时间不足则 `timeout` |
| 修复产物无进展 | 未通过成功门禁且与上一失败产物哈希相同，终止为 `failed / no_progress` |
| 修复次数用尽 | 当前产物仍未通过门禁，终止为 `failed / repair_limit` |
| 验证环境不可用、容器清理不能确认 | 终止为 `unavailable`，不进入代码修复 |
| Go 测试内部 8 秒超时 | 沙箱按代码验证 `failed` 处理，仍可能进入修复；不同于验证器或任务级 `timeout` |
| 客户端断开或任务取消 | 等待工作流与容器清理，保存 `cancelled` 报告并重新传播取消，不保证发送 `go_done` |
| 报告构造、最终持久化等再抛异常 | 仍可能沿接口异常路径退出，不能保证所有错误都产生正常终态事件 |

旧流程的单次生成超时被生成节点当作调用失败处理，可占用剩余额度再试；尝试失败最终是 `generation_error`。它与多智能体的角色超时处理不同。

两种流程的任务报告通常仍通过 HTTP 200 返回，业务状态放在报告中；报告可按账户重新读取，**不能据此恢复任务执行**。
