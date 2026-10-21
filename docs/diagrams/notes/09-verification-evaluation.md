项目通过机制测试、集成验证和真实模型评测分别检查“实现是否正确、组件能否协作、实际效果是否达标”，最终启用仍需人工依据验收结果修改配置。

先修正两处文档与代码差异：

- `docs/development.md` 的 CI（持续集成）章节已过时。当前实际任务为 `offline`、`go-validation`、`browser`、`live-evaluation-policy`，最后一个只输出提示，**不执行收费评测**。
- 浏览器 CI 使用真实 Chromium 和 HTTP 后端，但未传 `--docker`，验证器仍使用替身；本地另有“浏览器＋真实 Docker”的证据。

依据：[当前 CI](../../../.github/workflows/ci.yml#L17)、浏览器脚本（本地参考：`scripts/verify_multi_agent_browser.py:12`）、[测试后端](../../../scripts/multi_agent_dashboard_server.py#L21)。

---

**一、主图：三条验证支线**

实线表示执行流程，虚线表示报告、证据的汇总关系。三条支线并非所有脚本共享的一条强制流水线。

<!-- readme-diagram:09-verification-evaluation-01 -->
![验证机制、集成与真实效果](../png/09-verification-evaluation-01.png)

<details>
<summary>展开原始完整流程</summary>

```mermaid
flowchart TB
    Entry["选择验证范围与对应版本"]
    Branch{"验证类型"}

    subgraph OfflineBranch["支线一：离线机制测试｜已实现，有本地证据"]
        OfflinePrepare["verify_multi_agent.py<br/>新建输出目录、隔离凭据和临时数据库<br/>禁止读取业务 .env"]
        OfflineRun["记录依赖及源码状态<br/>compileall → pytest → 独立回归脚本<br/>固定模型 Agent 路径评测 → 服务导入"]
        OfflineCoverage["检查预算、协议、状态转换、取消、存储、编码等机制<br/>模型和外部服务按测试替换"]
        OfflineReport["日志、逐节点 XML、命令退出码<br/>verification.json 与源码清单"]
    end

    subgraph IntegrationBranch["支线二：真实 Docker 与浏览器集成｜已实现，有本地证据"]
        IntegrationChoice{"集成入口"}
        DockerPrepare["构建固定 Go 验证镜像<br/>verify_multi_agent.py --docker"]
        DockerRun["真实沙箱回归、回退检查<br/>固定输出 Go 验证评测<br/>检查本次范围容器是否清理"]
        DockerGate{"Docker 可用、必选节点未跳过<br/>命令通过且无容器遗留？"}
        IntegrationFailure["集成验证失败<br/>保留日志，不能记为跳过后通过"]
        FixtureComparison["固定模型四组对照<br/>freeze → 开发集 → 留出集<br/>真实 Docker 独立评分"]
        BrowserPrepare["verify_multi_agent_browser.py<br/>真实 Chromium + 页面替身检查<br/>+ 真实 HTTP 后端检查"]
        BrowserMode{"显式传 --docker？"}
        BrowserStub["固定角色模型 + 验证器替身<br/>当前浏览器 CI 使用此路径"]
        BrowserDocker["固定角色模型 + 真实 Docker<br/>已有独立本地证据"]
        IntegrationReport["集成报告、事件、页面检查结果<br/>截图、代码产物、验证日志、独立评分"]
    end

    subgraph LiveBranch["支线三：真实模型效果评测｜实现与执行状态分别核对"]
        LiveChoice{"评测对象"}
        GoLive["Go 多智能体对照：见图二<br/>已实现预检与执行器<br/>真实收费对照尚未执行"]
        ContextLive["上下文 A/B/C/D 对照：见图三<br/>历史冻结版本已完成真实评测<br/>综合门槛未通过"]
        RagLive["run_eval.py<br/>真实 RAG 或 Agent 回答<br/>关键词命中 + 模型评委 + 可选 RAGAS"]
        LiveReport["真实模型报告<br/>回答、质量指标、用量、费用估算、延迟<br/>缺失数据保留为未知"]
    end

    EvidenceReview["分别审查机制、集成和真实效果证据<br/>本地通过不代表远程 CI 通过<br/>固定模型通过不代表真实质量达标"]
    EnableDecision["依据对应功能的验收条件判断<br/>评测脚本不自动修改功能开关"]

    Entry --> Branch
    Branch -->|离线机制| OfflinePrepare
    OfflinePrepare --> OfflineRun --> OfflineCoverage --> OfflineReport

    Branch -->|集成验证| IntegrationChoice
    IntegrationChoice -->|Docker| DockerPrepare --> DockerRun --> DockerGate
    DockerGate -->|失败| IntegrationFailure
    DockerGate -->|通过| IntegrationReport
    IntegrationChoice -->|固定模型对照| FixtureComparison --> IntegrationReport
    IntegrationChoice -->|浏览器| BrowserPrepare --> BrowserMode
    BrowserMode -->|否| BrowserStub --> IntegrationReport
    BrowserMode -->|是| BrowserDocker --> IntegrationReport

    Branch -->|真实模型| LiveChoice
    LiveChoice --> GoLive --> LiveReport
    LiveChoice --> ContextLive --> LiveReport
    LiveChoice --> RagLive --> LiveReport

    %% 三类报告只能证明各自覆盖的范围，不相互替代
    OfflineReport -.-> EvidenceReview
    IntegrationReport -.-> EvidenceReview
    LiveReport -.-> EvidenceReview
    EvidenceReview --> EnableDecision
```

</details>

CI 实际依赖关系为：

| 任务 | 实际内容 |
|---|---|
| `offline` | Windows/Ubuntu × Python 3.11/3.13；隔离离线验证 |
| `go-validation` | 等待 `offline`；Linux 真实 Docker、固定模型开发/留出对照 |
| `browser` | 等待 `offline`；真实 Chromium，但未开启真实 Docker 验证器 |
| `live-evaluation-policy` | 独立提示任务，不运行真实模型，不判断质量是否通过 |

离线模式允许明确跳过 Docker 节点；`--docker` 验收要求节点实际运行，缺节点或出现跳过会判失败。

源码：隔离验证入口（本地参考：`scripts/verify_multi_agent.py:15`）、[固定模型 Agent 路径评测](../../../eval/run_agent_eval.py#L20)、[CI Docker 对照](../../../.github/workflows/ci.yml#L45)。

---

**二、Go 多智能体：冻结、真实评测、独立评分与费用结算**

<!-- readme-diagram:09-verification-evaluation-02 -->
![Go 多智能体对照评测](../png/09-verification-evaluation-02.png)

<details>
<summary>展开原始完整流程</summary>

```mermaid
flowchart TD
    subgraph FreezePreparation["冻结与用例边界"]
        SelectCases["选择协议及数据<br/>机制集与正式真实模型候选集分别使用"]
        ValidateCases["检查 30 条用例及 18/12 划分<br/>真实候选额外检查需求去重、任务族不跨集<br/>独立探针与需求检查项对应"]
        Freeze["freeze：冻结源码原始字节、数据、评分、组别配置<br/>模型、费率、费用目标、依赖环境<br/>Docker 镜像 ID 与架构"]
        LoadFreeze["每次启动 load_freeze<br/>重新核对源码、数据、环境及镜像"]
        FreezeChanged["拒绝沿用旧冻结<br/>保留原件，建立新冻结"]
    end

    subgraph LivePreflight["真实模型预检｜已实现，当前本地记录为 blocked"]
        Preflight["prepare-live / run --mode live<br/>核对明确累计费用上限及币种<br/>固定模型版本、端点、窗口、完整费率上界<br/>数值成本目标及持久化费用账本"]
        ReadyGate{"条件完整且与冻结一致？"}
        Blocked["生成 blocked 报告<br/>不构建收费客户端、不发送模型请求"]
    end

    subgraph SplitControl["开发集与留出集控制"]
        SplitGate{"本次运行哪个集合？"}
        DevRun["开发集运行<br/>四组对照并保存完整报告"]
        HoldoutGate{"完整开发报告匹配<br/>冻结、模式及评分版本？"}
        HoldoutStart["核对首次启动标记并加锁<br/>留出集禁止 limit 和中断调试注入<br/>再次启动须提供 rerun-of 与 reason"]
        HoldoutRun["正式留出运行<br/>真实模式每组每用例重复 3 次"]
    end

    subgraph RequestBoundary["每次真实模型请求的费用边界"]
        Reserve["请求前持久化费用预占<br/>按窗口及输出上界计费<br/>累计账本跨进程、重启及输出目录继续使用"]
        ReserveGate{"剩余额度足够<br/>且账本、锁及写入正常？"}
        CallLog["先保存调用记录<br/>角色、输入、预占编号、调用序号"]
        Provider["发送模型请求<br/>记录输出、实际用量、返回模型版本"]
        Settle["结算并落盘<br/>已知用量按冻结费率估算<br/>未知用量保留预占，不补零"]
        StopGate{"取消、版本不符、结算失败<br/>或账本被封锁？"}
        StopEvaluation["停止后续收费请求<br/>保留预占、失败及未运行项"]
    end

    subgraph IndependentScoring["运行留痕与独立评分"]
        TrialRecord["保存事件、任务报告、各轮代码及 hash<br/>业务验证结果与原始调用记录"]
        ScoreKind{"用例是否可执行？"}
        CodeScore["移除模型测试，注入独立服务端探针<br/>真实 Docker 再执行<br/>绑定独立评分输入 hash"]
        RefusalScore["核对结构化 unsupported 证据<br/>请求关联、评估版本及预声明冲突类型"]
        Aggregate["汇总独立正确率、误批准、误拒绝<br/>修复率、未知项、费用及 P95 延迟<br/>生成 report.json"]
        ManualReview["按冻结目标人工验收<br/>当前未找到统一的自动启用判定器<br/>不自动修改多智能体开关"]
    end

    SelectCases --> ValidateCases --> Freeze --> LoadFreeze
    LoadFreeze -->|发生变化| FreezeChanged
    LoadFreeze -->|一致| Preflight --> ReadyGate
    ReadyGate -->|否| Blocked
    ReadyGate -->|是| SplitGate
    SplitGate -->|开发集| DevRun --> Reserve
    SplitGate -->|留出集| HoldoutGate
    HoldoutGate -->|否| Blocked
    HoldoutGate -->|是| HoldoutStart --> HoldoutRun --> Reserve

    Reserve --> ReserveGate
    ReserveGate -->|否| StopEvaluation
    ReserveGate -->|是| CallLog --> Provider --> Settle --> StopGate
    CallLog -->|落盘失败：保留预占| StopEvaluation
    StopGate -->|是| StopEvaluation
    StopGate -->|否| TrialRecord
    TrialRecord --> ScoreKind
    ScoreKind -->|可执行| CodeScore --> Aggregate
    ScoreKind -->|不可执行| RefusalScore --> Aggregate
    Aggregate -->|仍有计划任务且允许继续| Reserve
    Aggregate -->|本集合结束| ManualReview

    %% 业务 passed、主角色 approve、模型自带测试均不能直接充当独立正确标签
    %% 开发报告完整只是留出启动条件，不等于开发质量已达标
```

</details>

关键边界：

- 固定模型四组对照采用同类冻结、留痕及独立 Docker 评分流程，但不请求收费模型。固定角色会读取样本标签，因此只能验证机制。
- `native` 对照同时改变调用资源；`equal3` 只对齐调用上限，不能声称实际调用、费用或修复机会相同。
- Go 评测没有自动恢复任务内部执行。中断目录保留；再次运行使用新目录及来源、原因，继续使用原累计费用账本。未知调用不能退款或补零。
- 协议已声明留出误批准为零、质量不下降、延迟与数值成本目标；执行器实现了预检和指标汇总，**没有自动汇总这些目标并开启功能的逻辑**。

源码：[冻结与数据校验](../../../eval/multi_agent_protocol.py#L71)、[真实预检](../../../eval/multi_agent_protocol.py#L220)、[费用账本](../../../eval/multi_agent_protocol.py#L156)、[调用记录及结算](../../../eval/run_multi_agent_eval.py#L50)、[开发/留出限制](../../../eval/run_multi_agent_eval.py#L252)、[独立评分](../../../eval/multi_agent_scoring.py#L102)。

---

**三、上下文：真实四组对照、中断续跑与自动门槛**

<!-- readme-diagram:09-verification-evaluation-03 -->
![上下文四组对照与验收](../png/09-verification-evaluation-03.png)

<details>
<summary>展开原始完整流程</summary>

```mermaid
flowchart TD
    subgraph ExperimentPreparation["实验准备"]
        Dataset["选择固定长对话脚本<br/>20 条开发、10 条留出<br/>覆盖 10 / 30 / 60 轮"]
        Boundary["开发集用于调试<br/>正式留出应固定代码、数据、评分后使用<br/>用过留出排错后，不能继续宣称独立验收"]
        Identity["记录源码和数据哈希、模型名及运行参数<br/>该入口不具备 Go 评测的完整版本及环境冻结"]
        Arms["选择 A/B/C/D<br/>A：最近 6 轮基线<br/>B：工具精简和证据复用<br/>C：增加历史预算<br/>D：增加摘要"]
        ExplicitLive{"显式 --live<br/>且具备模型凭据？"}
    end

    subgraph Execution["真实模型运行｜工具语料固定"]
        Budget["每次请求前检查调用和 Token 预算<br/>金额上限可选，设置后须有可用价格<br/>B/C/D 的强制上下文检查要求窗口与计数校准"]
        RunCase["各组独立生成完整多轮回答<br/>关闭答案缓存，统一采样及输出参数"]
        Record["保存逐轮回答、调用、摘要、工具步骤<br/>实际用量、延迟、错误及预算扣减"]
        Grade["评分终局约束、尾部证据使用<br/>普通字符要求<br/>未知实际用量及完整金额保持未知"]
        OriginalReport["生成各组原始报告<br/>完整成功、完整失败和中断分别保留"]
    end

    subgraph Resume["中断续跑：resume_context_eval.py"]
        VerifyResume["校验原四组报告及当前代码、数据、模型、参数<br/>默认只生成计划，不发请求"]
        Pending["复用全部完整样本，包括完整失败<br/>只选择未运行或未完成样本"]
        InflightGate{"存在执行中或未结算批次？"}
        ResumeBlocked["停止后续收费请求<br/>不能用新批次绕过未知费用"]
        ResumeBudget["校验计数校准、价格及运行身份<br/>扣除此前追加开销<br/>四组共用追加累计预算"]
        RestartCase["新会话从样本第一轮重跑<br/>保留原报告，保存新报告与文件哈希"]
        Merge["merge_context_resume.py<br/>质量按唯一任务最终结果统计<br/>费用、调用及延迟包含原中断尝试"]
    end

    subgraph ReleaseGate["正式比较与启用依据"]
        Compare["compare_context_eval.py<br/>检查完整矩阵、可比性、质量及效率门槛"]
        Allowed{"全部门槛通过？"}
        KeepOff["release_allowed = false<br/>验收要求：保持 context_mode = off"]
        Eligible["release_allowed = true<br/>仅形成进一步启用决策依据<br/>部署者另行修改配置并重启"]
    end

    Dataset --> Boundary --> Identity --> Arms --> ExplicitLive
    ExplicitLive -->|否| RefuseRun["拒绝真实质量评测"]
    ExplicitLive -->|是| Budget --> RunCase --> Record --> Grade --> OriginalReport
    Budget -->|预算耗尽或服务商账户阻塞| OriginalReport

    OriginalReport -->|完整矩阵| Compare
    OriginalReport -->|存在未完成样本| VerifyResume --> Pending --> InflightGate
    InflightGate -->|是| ResumeBlocked
    InflightGate -->|否，且显式允许真实续跑| ResumeBudget --> RestartCase
    RestartCase --> Record
    OriginalReport -.->|原件与追加报告| Merge
    Merge --> Compare
    Compare --> Allowed
    Allowed -->|否| KeepOff
    Allowed -->|是| Eligible

    %% 续跑进度清单固定 release_allowed=false，不能替代正式比较报告
    %% 完整失败样本不得通过重复运行后挑选成功结果替换
```

</details>

上下文比较器实际要求：

| 类别 | 已实现的门槛 |
|---|---|
| 可比性 | 四组条件一致，每组完整 `30 × 3` 次 |
| 质量 | 非劣性下界不低于 `-3%`；硬约束、尾部证据 `100%`；普通字符约束至少 `98%`；D 组留出全部通过 |
| 用量 | 实际用量完整；已知调用的输入估算无低估 |
| 效率 | 长对话输入至少节省 `20%`；重复请求不增加；P95（95% 请求不超过的耗时）增幅不超过 `10%`；完整费用不增加 |

这里的开发/留出边界部分依靠实验纪律：`run_context_eval.py` 支持选择 `split`，但**不强制要求先提交完整开发报告**。续跑工具才会严格核对原报告和冻结身份。

源码：[四组执行与评分](../../../eval/run_context_eval.py#L87)、[请求前预算保护](../../../app/context/usage.py#L17)、[续跑约束](../../../eval/resume_context_eval.py#L149)、[合并统计](../../../eval/merge_context_resume.py#L66)、[正式门槛](../../../eval/compare_context_eval.py#L55)。

---

**四、哪些已有证据，哪些仍未验证**

本次只读取代码、文档和已有报告并核对哈希，没有重新执行测试、浏览器、Docker 或收费模型。

| 项目 | 实现与已有证据 | 结论边界 |
|---|---|---|
| 离线机制验证 | 2026-10-19 本地记录：`337 passed`，63 个 Docker 节点明确跳过 | 不能记为 Docker 全通过 |
| 真实 Docker 全套 | 同日本地记录：`400 passed`、无跳过；回退及容器清理检查通过 | 本地证据，不是远程 CI 成绩 |
| 浏览器集成 | 已有固定模型下的验证器替身、真实 Docker 两类本地记录 | 不证明真实模型效果 |
| Go 固定模型对照 | 开发 72 次、留出 48 次，共 120 次；300 次固定客户端调用 | 机制对照，不是模型质量结果 |
| Go 真实模型对照 | 预检和执行器已实现；现有预检为 `blocked`、`calls_sent=0` | 真实质量、费用及推理延迟仍未验证 |
| 上下文真实对照 | 历史冻结版本完成 360 次，报告 `release_allowed=false` | 质量和效率综合门槛未通过；其记录源码有 3 处与当前代码不同 |
| 远程 CI | 工作流已实现；仓库验收记录标为未运行 | 尚无匹配提交的远程通过证据 |

本次核对，多智能体本地冻结清单的 **107 个文件与当前清单完全一致**；这不代替重新验证运行环境。上下文旧报告则不能直接认证当前代码。

证据：本地修复验收（本地参考：`docs/multi-agent-remediation-results.md:23`）、多智能体冻结（本地参考：`docs/evidence/remediation-20261019/freeze-mechanism-v3.json`）、真实模型预检（本地参考：`docs/evidence/remediation-20261019/live-preflight.json`）、上下文正式比较（本地参考：`eval/reports/context/final-resumed-v3/comparison.json`）、[上下文验收结论](../../context-management-final-results.md)。

补充两个入口差异，避免把统一预算保护画到所有脚本上：

- `run_eval.py` 使用关键词、LLM-as-Judge（用模型给回答评分）和可选 RAGAS；门槛参数默认不设置，RAGAS 指标没有通过阈值。`--no-ragas` 仍调用模型评委，且该入口没有 Go 评测的累计费用账本。
- `calibrate_context_counter.py` 会发送 20 次真实计量请求；它验证计数估算，不验证回答质量，也不共享 Go 费用预检。

对应源码：[RAG 评测及可选门槛](../../../eval/run_eval.py#L222)、[计数校准](../../../scripts/calibrate_context_counter.py#L17)。

当前代码默认仍为多智能体 `false`、上下文 `off`。启动代码检查配置合法性，**不会读取验收报告自动允许或阻止启用**；报告结论与人工部署决策必须在图中分开。
