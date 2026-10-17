# 多 Agent 执行记录

本记录从 S0 开始建立。仅下文标记“本次实际运行”的结果来自本机；README、旧目录说明、`GO_VALIDATION_CHECKLIST.md`、`docs/go-validation-fixture-report.json` 和上下文历史评测均不是本次结果。

## S0 / T01–T03：可信基线与旧实现复用分析

执行日期：2026-10-17，Asia/Shanghai。本次基线命令运行于 11:13–11:15；完整 UTC 起始时间、退出码、耗时、参数和输出 SHA-256 见 [commands.json](evidence/s0-20261017/commands.json) 与 [supplementary-commands.json](evidence/s0-20261017/supplementary-commands.json)。

目标：确认实际代码版本和环境，实际执行不调用付费模型的基线检查，只读分析旧多 Agent 实现，固定首版边界。依赖：无前置开发任务，仅需要读取仓库；行为测试依赖本地 Python 包/词表，真实沙箱依赖 Docker Linux 引擎和固定镜像。

改动范围：新增本文件和 `docs/evidence/s0-20261017/` 内的复现脚本、命令结果、源码指纹及证据校验清单；未修改应用、测试、CI、依赖声明或两份原有计划文档，未创建提交。没有实施 S1 或后续步骤。

验收条件：根目录/HEAD/分支/本地差异明确；依赖及测试配置可追溯；离线检查实际运行并保留失败；旧实现逐项列明复用点、接口差异和取舍；首版范围不扩张。环境不足的验证标记阻塞，不能记作通过。

| 任务 | 状态 | 变更文件/交付 | 实际结论 | 剩余问题 |
| --- | --- | --- | --- | --- |
| T01 | 完成基线记录；行为验收子项阻塞 | 本文件；`docs/evidence/s0-20261017/*` | Git、版本、依赖、语法、导入及可执行离线回归已有本次证据 | pytest、词表缓存、Docker 阻塞；完整 Go/上下文回归未取得结果 |
| T02 | 完成（静态分析） | 本文件的逐项复用清单；新旧源码指纹 | 旧实现及相关改动/13 个测试方法已只读分析；没有复制模块或执行旧实现 | 未来迁移需在新版实际测试，静态判断不代表运行通过 |
| T03 | 完成（范围固定） | 本文件的首版范围与服务端不变量 | 沿用计划中的 1 主 Agent + 1 代码 Agent + Go 验证工具及三个场景 | 契约、配置与新增服务端判定留待 S1；此处未声称已经实现 |

S0 的基线与分析交付完成，完整行为回归仍有环境阻塞，不是“全量测试通过”，不据此宣布 M1–M5 完成。

### 仓库、说明与代码指纹

已读取用户提供的 AGENTS.md 指令（Postman CLI 可用，本步骤无 API 工程调用需求），检查祖先目录以及新旧仓库内适用的 AGENTS.md，未发现额外文件。已读取新版 README、开发/Go 验证指南、实施计划、执行提示词、依赖/CI、当前工作流与测试；旧版读取 multi_agent、相关 Git 差异、测试及说明。开始前不存在本执行记录，未发现已实现新版多 Agent 的证据；不能仅凭计划的“待执行”字样作此结论。

| 项目 | 新版（本次执行目录） | 旧版（只读分析目录） |
| --- | --- | --- |
| 实际 Git 根目录 | `/Users/xumanchun/Documents/agent项目/AI-Robot-latest` | `/Users/xumanchun/Documents/agent项目/AI-Robot-FastAPI-LangChain-RAG-CrewAI-Agent-` |
| HEAD | `1ea7e6b7abbde3bd1a5963f03cd142fac553685a`，仍为计划基线 | `44622e6fbef5e07a409347151b1d38bcdf1a2abd` |
| 分支/本地 upstream 关系 | `main`，相对本地 `origin/main` +0/-0 | `main`，相对本地 `origin/main` +0/-2 |
| 初始本地修改 | 仅未跟踪 `docs/multi-agent-implementation-plan.md`、`docs/multi-agent-execution-prompts.md` | 18 个已跟踪文件修改；未跟踪 multi_agent.py、test_multi_agent.py、docs/、output/、tmp/、`:memory:.ses` |
| HEAD 上未提交 tracked diff SHA-256 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`（空） | `bb9aef447660cd2a83ed7069bb85f971a88614da093905c482f52b96e65f7a1e` |
| staged diff | 两侧均为空，SHA-256 同上空摘要 | 同左 |
| 源码/相关文档清单指纹 | `0821cec6571ed888c3d37f853c3ea736c01687bdd7ae26d73019b5c4921e7c24`（132 文件） | `c1a6e16fe28303cc8e453d44c3e4dcb6bbcde12da1e5833d7c849167d3be31fb`（66 文件） |

以上 upstream 关系来自本地 Git，没有 fetch，因此不声称远端当前状态。父工作区的 `.git` 与这两个仓库各自独立；命令全部指定新版 cwd，旧版 Git 命令单独指定旧根目录。

指纹算法：按相对路径排序的 `{path: SHA256(file_bytes)}` 映射，使用 UTF-8 JSON（sort_keys、无多余空格）计算 SHA-256；tracked diff 对 `git diff --binary HEAD` 原始字节计算，包含 staged + unstaged，另记录 staged 指纹。覆盖 tracked 文件及相关非 ignored untracked 文件，排除凭据/虚拟环境/缓存、旧 output/tmp/`:memory:.ses`、本日志及证据目录，避免递归哈希。完整排除规则和逐文件摘要见 [source-before.json](evidence/s0-20261017/source-before.json) / [source-after.json](evidence/s0-20261017/source-after.json)。这不是只用 HEAD 判断源码相同。

原有未跟踪计划文档分别为 `7f0c52a7da8e1678ad28c67342de6ae7257059cc623adf34bed433221496fd73` 和 `8c3f407f1a550bfb8bbd787cfbfe076c70671fe82395df2e38249a2c4f2bbf6b`，均保留。旧 `multi_agent.py` 为 `45ef1b6b3992e79a80ae4571609431e0975cfb637cff4afcbe4857d8efe289e4`，旧 `test_multi_agent.py` 为 `2c91170360c7dd27287fd35e5bb227fbfc2b29fabbd32aa917ff69e44ba24b0e`。

本次新增未提交文件的内容标识见 [artifact-manifest.json](evidence/s0-20261017/artifact-manifest.json)（逐文件 SHA-256，包含本日志，排除清单自身）。终检见 [final-checks.txt](evidence/s0-20261017/final-checks.txt)。没有 reset、checkout、stash、整文件迁移或修改旧目录。

### 环境、依赖与测试配置

| 检查项 | 本次观察 | 影响 |
| --- | --- | --- |
| 系统 Python | `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`，3.13.13；pip 26.0.1；仅 pip 和 git-filter-repo | 新版无 `.venv`/`venv`、无 `.env`；系统环境不能运行项目 pytest |
| 借用解释器 | 旧目录 `.venv/bin/python`，Python 3.13.13；仅使用已安装第三方包，新版 cwd/PYTHONPATH 加载新版应用 | 没有向旧环境安装包或执行旧源码；不等于新版已具备独立、干净的开发环境 |
| 已安装关键包 | FastAPI 0.141.1、Pydantic 2.13.5、LangChain 1.3.18、langchain-core 1.6.1、langchain-openai 1.1.9、LangGraph 1.2.11、tiktoken 0.14.0、httpx 0.28.1、tenacity 8.5.0 | 全量版本见 `borrowed-packages.txt`；当前 17/17 核心声明满足，开发依赖 17/18 满足，缺 pytest |
| 依赖完整性 | 借用环境 `pip check` 退出 0，No broken requirements found | 只说明包元数据约束相容，不说明运行行为通过；requirements 主要是下限范围，无锁文件 |
| 可选依赖 | sentence-transformers、langchain-milvus 未安装；ragas 0.3.9、langchain-community 0.3.31 已安装 | 本步关闭重排、外部服务且未运行 RAGAS；不影响已运行的基础离线测试 |
| tiktoken 数据 | cl100k_base 缓存不存在，首次实际计量试图下载公共 BPE 词表 | 即使 context_mode=off，`usage.invoke` 仍做 TokenCounter 计量；固定模型回归也受影响 |
| Docker | CLI 29.7.2，context desktop-linux；Compose v5.4.0；socket `/Users/xumanchun/.docker/run/docker.sock` 不存在，`docker version` 退出 1 | Linux 引擎不可用；镜像 inspect 同样失败，镜像是否已存在**未知**，不能断言镜像缺失 |
| 固定 Go 沙箱 | `airobot-go-validator:1.26.2`；Dockerfile 锁定 golang:1.26.2-bookworm 的摘要 | 未构建或拉取镜像；真实编译/测试/清理均待验证 |
| 宿主 Go | go1.26.5 darwin/arm64 | 不是固定 Go 1.26.2 Linux 沙箱，不拿宿主执行替代 Docker 验收 |
| 浏览器测试 | Node v22.23.1；`require.resolve('playwright')` 退出 1，MODULE_NOT_FOUND | Dashboard 脚本未运行；它们还消费历史 Go/上下文报告，不能充当本次真实执行证据 |
| Python/pytest 配置 | README 要求 3.11+；CI 使用 3.11；无 pytest.ini、pyproject.toml、setup.cfg、tox.ini、tests/conftest.py 或 .python-version | 本机只验证 3.13.13；3.11 回归未运行；19 个测试模块/145 个 test 定义为 AST 静态计数，非 pytest 收集数 |

详细依赖逐项约束与静态库存见 [dependency-audit.txt](evidence/s0-20261017/dependency-audit.txt)。CI 的 build 使用 compileall；test 包括四个脚本、unittest、固定模型 Agent 路径、导入冒烟及 pytest 全量；go-validation 设置 `AIROBOT_TEST_DOCKER=1` 并构建固定镜像；eval 配置密钥后会调用真实模型。本次没有运行 CI eval 或任一 live 入口。

安全与复现：`python3 docs/evidence/s0-20261017/run_baseline.py` 可复现基线探测。脚本对子进程移除 AIROBOT/OPENAI/LangChain/LangSmith/Pytest 相关继承配置，禁止 dotenv 自动加载，清空 LLM/Embedding/Go/MQ 配置，关闭重排和追踪，context_mode=off；`PYTHONDONTWRITEBYTECODE=1`，compileall 缓存写入 `/private/tmp/airobot-s0-pycache`。`offline_guard/sitecustomize.py` 在 DNS/连接前直接抛错且记录事件；不修改测试断言或伪造模型结果。网络拦截自检实际通过，见 `network-guard-selftest.txt`。业务基线捕获 5 次公共词表 DNS 尝试，均在解析/连接前被拦截，见 `network-audit.txt`；没有发生真实模型/Embedding 请求。

为恢复环境，另外实际尝试 `python3 -m pip --isolated install --target /private/tmp/airobot-s0-deps --no-cache-dir --disable-pip-version-check --index-url https://pypi.org/simple 'pytest>=8,<10'`，退出 1，PyPI DNS 失败。公共词表使用 Python urllib 请求 `https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken`、计划以发行包要求的 SHA-256 `223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7` 校验后缓存至 `/private/tmp/airobot-s0-tiktoken`；同样在 DNS 阶段失败，退出 1，未得到词表。原始输出分别在 `install-pytest.txt`、`cache-preparation.txt`。这两条仅获取公共测试资源，不是模型评测；没有通过替换计数器或放宽测试消除错误。网络条件不足，保留阻塞项。

### 本次实际运行结果

下表中 `P` 表示旧目录 `.venv/bin/python` 的完整绝对路径，实际 argv 均保存在 commands.json。所有命令 cwd 都是新版根目录。退出码非零保留原样；环境阻塞不计作成功或业务代码缺陷。

| 类别 / 命令 | 退出码 | 实际结果 | 证据与限制 |
| --- | --- | --- | --- |
| 语法：`python3 -m compileall -q app eval scripts tests` | 0 | **通过** | `syntax.txt`；仅语法检查，不证明行为 |
| 导入：`P -c 'import app.main, app.agents.graph; ...'` | 0 | **通过**，14 路由 | `import-smoke.txt` 打印的两个模块路径均在新版；没有执行 lifespan/启动恢复 |
| `P tests/test_stability.py` | 0 | **通过 6** | `script-stability.txt` |
| `P tests/test_integration.py` | 0 | **通过 12** | `script-integration.txt`；HTTP MockTransport/检索替身，非真实文章/Embedding 服务 |
| `P tests/test_tracing.py` | 0 | **通过 3** | `script-tracing.txt` |
| 模型替身：`P tests/test_agent.py` | 1 | **命令失败，环境阻塞**：前 2 项通过，第 3 项词表缺失报错；剩余 2 项未执行 | `script-agent.txt`；图节点存在/事件映射通过，真实工具循环未跑完 |
| `P -m unittest discover -s tests -p test_hardening.py -v` | 1 | **命令失败**：实际运行 26，runner 报告 24 通过、2 ERROR，0 skip | `hardening.txt`；两个流式测试因计量下载被拦截，随后 StopAsyncIteration；归为环境阻塞 |
| 模型替身路径：`P eval/run_agent_eval.py` | 1 | **命令失败，环境阻塞**：第一条 knowledge 因词表缺失中断，未获得完整 6 场景结果 | `agent-fixtures.txt`；绝不能记为“6/6 通过” |
| 全量：`python3 -m pytest tests -q`；`P -m pytest tests -q` | 各 1 | **环境阻塞**：No module named pytest；没有收集或执行用例 | `system-pytest.txt`、`borrowed-pytest.txt` |
| Go 专项：`P -m pytest tests/test_go_contracts.py tests/test_go_workflow.py tests/test_go_runner.py tests/test_go_acceptance.py -q` | 1 | **环境阻塞**：pytest 缺失；没有收集或执行用例 | `borrowed-go-pytest.txt` |
| 真实 Docker：`docker version`；`docker image inspect airobot-go-validator:1.26.2` | 各 1 | **环境阻塞**：引擎 socket 不存在 | `docker-version.txt`、`docker-image.txt`；未运行真实 Docker 测试/固定输出 Go 评测 |
| 依赖：`P -m pip check`；`P .../inspect_dependencies.py` | 各 0 | **检查通过**，开发缺项明确 | `borrowed-pip-check.txt`、`dependency-audit.txt`；不能当行为测试通过 |
| 防外连：网络保护自检 | 0 | **通过**，预期 DNS 调用被拒绝 | `network-guard-selftest.txt`、`guard-selftest-audit.txt`；与业务网络尝试分开计数 |

加固测试的 24 个 runner 通过中，`test_stream_failure_does_not_commit_partial_answer` 的应用日志也出现词表错误；其广义异常断言虽通过，尚未证明预期的模拟生成失败分支，因此该项行为仍待缓存恢复后复测。不把这个表面通过隐藏为完整验收。其他输出中的 jieba Python 3.13 SyntaxWarning 保留，未作为失败忽略；不涉及本次生产源码修复。

**跳过 / 未运行 / 阻塞分开**：本次已启动的 unittest 未出现 skip；pytest 入口在收集前失败，因此不能编造 pytest 跳过数量。代码中现有真实 Docker 用例由 `AIROBOT_TEST_DOCKER=1` 启用，这是静态配置事实，不是本次 skip 结果。真实 Docker 行为验收、Go 固定输出编译评测及 Dashboard 浏览器验收因上述环境阻塞未运行。旧目录的 13 个多 Agent 测试仅阅读，未运行（遵循只读分析范围）。所有真实模型评测未运行：用户尚未提供累计费用上限，没有调用授权；固定模型结果不代表真实模型质量。S1–S9 的新增多 Agent 契约/闭环/预算用例尚未实施或运行。

### T02：旧实现逐项复用与接口差异

以下 `old:` 都指旧仓库当前**含本地改动**的版本；不是仅比较其 HEAD。新版目前没有 `app/agents/multi_agent.py`、`supervisor.py`、`code_agent.py`、`go_workflow.py`，Go 编排实际位于 `app/agents/graph.py` + `app/go_validation/nodes.py`。旧版没有新版 Go 验证/上下文模块，整文件覆盖会删除这些能力。

| 旧逻辑 / 位置 | 可复用部分 | 新版接口差异 / 取舍 |
| --- | --- | --- |
| `old:multi_agent.py:22` Delegation / delegate_task | Pydantic extra=forbid、字段长度、角色枚举；委派由图调度，禁止伪装成外部工具直接执行 | 旧契约只有 knowledge/article + task；新契约需 TaskSpec 的原需求、需求 ID、验收/限制/来源，代码角色固定，不能直接重命名后复用 |
| `:68` _supervisor 校验 | 超额 tool_calls、invalid_tool_calls、重复角色、非委派工具均在服务端拒绝 | 旧版是聊天工具分派；新版主 Agent 还需计划/审查分开、固定接口保留、角色模型独立注入；不能直接使用共享 `runtime.get_llm()` |
| `:95` 固定任务排序与预算预分配 | 稳定输出顺序、外部调用前检查额度的思路 | 旧版限制的是业务工具次数，不限制计划/专家/摘要/重试的模型请求；新版只有一个代码 Agent，改用全任务共享调用/重试/验证/截止时间账本，不沿用 divmod 分预算 |
| `:104` _dispatch / LangGraph Send | 显式交接，子任务不收到父图和兄弟 messages | 旧版可并行两个领域专家；新版串行生成→验证→审查→修复，不能把并行专家图直接接成目标流程；继续使用 LangGraph，可用可调用组件/子图 |
| `:111` _specialist 局部 messages | 每次任务新建局部消息，清晰的角色提示词和工具范围 | 旧输入仅 task/budget，旧输出 summary/evidence；新版需要完整 CodeArtifact、上一版源码、实际验证/审查、问题 ID，必要源码不得静默裁剪 |
| `:115` 工具白名单及调用前 used 检查 | 权限在代码中检查；拒绝工具也配对 ToolMessage，保持模型协议 | 新版代码 Agent 只产代码与测试，Docker 由服务端验证器执行；不能获得旧通用工具循环或开放式命令执行权限 |
| `:138` 工具结果/来源/partial | 只累积成功工具来源，保留真实原文、失败不伪装证据 | 新版还需 ValidationReport/ReviewReport 绑定服务端 artifact_hash；旧 evidence 字符串未绑定源码，不能直接成为通过依据 |
| `:122` 专家总超时、异常与取消 | asyncio.timeout、取消不被 Exception 吞掉、保留已得证据 | 旧版专家失败仍进入最终回答，且普通错误被泛化；新版环境不可用/整体超时必须终止，代码级失败才可修复，取消要持久化进度并确认容器清理 |
| `:195` _finalize 汇总 | 同时读取证据与摘要、合成上下文不写回会话的边界思路 | 旧版“证据支持事实/标明失败”主要靠提示词，且总会尝试生成答案；新版必须审完整源码、固定需求及验证报告，approve 仅为输入，最终 passed 由服务端检查；复用审查摘要以避免额外未计费调用 |
| `:213` get_multi_agent_graph 状态与 reducer | 显式节点、结构化 reports、延迟构图 | 新版 AgentState 已含 go_*、上下文元数据和流 writer；应增加专用状态而保留 START 的 go_request/普通聊天分流，不能直接覆盖 `graph.py` |
| `old:graph.py` single/multi 选择 | 保留原执行路径作为回退和对照的设计 | 旧 `AIROBOT_AGENT_MODE=multi` 默认切换整个聊天图；新版首版只选择 Go 工作流，默认可选且普通聊天不自动委派，不能直接迁移旧入口/默认值 |
| `old:config.py` 三项多 Agent 配置 | 角色超时/工具额度可配置的动机 | 旧 max(0)/max(0.1) 会静默夹值，角色也共用模型；新版非法配置须拒绝启动，角色模型、共享异常重试、总调用/验证/时间预算应独立受控 |
| `old:services/chat.py` 事件、缓存、memory | JSON/SSE 共用执行图；handoff/agent_result 事件、失败不缓存、只提交最终答复 | 新版已有 context usage/store、go_start/go_stage/go_attempt/go_done 与 GoTaskService/store；旧聊天响应不能替换 GoTaskResult/账户隔离存储，事件只能兼容扩展，旧报告要有默认字段 |
| `old:agents/tools.py` 文章失败不产生来源 | 错误/缺失结果不自称成功的逻辑与测试意图 | 新版已存在相应错误与来源处理；无需为多 Agent 重复迁移此补丁，更不能覆盖新版上下文投影/检索用量记录 |
| `old:main.py`、schemas、dashboard、CI/eval 的相关差异 | 展示角色/阶段、保留单路径回归、分别报告机制与真实质量的思路 | 旧 UI/响应只有聊天专家模式；新版首版在 Go API/报告上扩展角色、轮次、hash、审查和停止原因；浏览器必须基于真实事件，不能照搬旧字段或把 done 等同 passed |

旧代码的模型调用使用 `ainvoke_with_retry`，专家无摘要时还会额外调用模型；它没有全任务模型调用硬上限、产物版本校验、不可变服务端测试、需求逐项检查或修复两轮闭环。它可以作为隔离/白名单的设计参考，不能当作计划 T04–T27 已完成的依据。

| 旧测试方法（tests/test_multi_agent.py） | 可复用的测试机制 | 新版需要调整/补充 |
| --- | --- | --- |
| `test_parallel_specialists_join_once_and_keep_contexts_isolated` | barrier 证明真实并发、检查各模型实际输入和单次汇合 | 首版不需并行两个专家；保留角色输入/跨任务隔离检查，增加计划与代码模型独立可注入 |
| `test_simple_question_uses_only_selected_specialist`、`test_direct_answer_skips_specialists` | 断言底层实际调用数，避免无用委派 | 改为固定 Go 角色路径与关闭新开关时普通聊天回退 |
| `test_partial_failure_preserves_other_evidence_and_disables_cache` | 失败保存已有证据、不泄漏内部异常 | 改为保存每轮源码、验证/审查/调用历史；环境故障直接终止，不能仅降级成聊天答案 |
| `test_tool_allowlist_is_enforced_outside_prompt` | 注入越权调用并断言工具零执行 | 新版加入服务端测试不可替换、禁用路径/依赖/任意命令的反例 |
| `test_global_tool_budget_is_split_between_parallel_workers`、`test_zero_budget_makes_no_tool_calls` | 可计数替身检查超限后没有底层调用 | 改为共享 8 次模型/1 次异常重试/3 次验证/2 次业务修复，发送前预占并计入失败请求 |
| `test_timeout_cancels_worker_and_still_reaches_final_answer` | 通过事件验证活动操作已取消 | 新版超时必须终止并保存已有状态，不能要求仍生成最终模型答复；增加验证器清理确认 |
| `test_duplicate_delegation_fails_closed`、`test_invalid_role_cannot_create_arbitrary_worker` | 非法模型输出不产生外部动作 | 增加 approve+blocking、陈旧 hash、缺失必要需求、非法审查格式拒绝 |
| `test_sse_and_json_share_results_and_only_final_answer_enters_memory` | 两入口共用执行流、会话不混入内部消息 | 改用 GoTaskService 的业务字段一致性、旧报告兼容及账户隔离；测试只排除合理变动字段 |
| `test_cancelling_stream_cancels_all_workers_without_memory_write` | 实际观察取消传播及资源 finally 执行 | 新版分别覆盖生成/审查/沙箱取消，保存已发生调用、已有产物并释放会话占用 |
| `test_article_unavailable_or_missing_has_no_success_source` | 缺失证据不虚构来源 | 新版已有相应文章回归；Go 检索来源继续沿用，不作为代码通过判定 |

### T03：首版范围与服务端边界固定

保持计划既定范围：1 个主 Agent（计划与审查）+ 1 个代码 Agent（首次生成与修复），Docker 是验证工具；同模型可区分角色，但实际模型需分别可配置、可注入和计量；LangGraph 编排；经现有 Go JSON/SSE 接口进入，不让普通聊天自动执行代码。实验性上下文开关保持独立，off 不得成为多 Agent 功能缺失的原因。

三个场景及固定接口保持不变：`WaitForCancel(context.Context) error`、`WorkerPool(context.Context, []int, int) ([]int, error)`、`SumChannel(context.Context, <-chan int) (int, error)`；含取消/deadline、并发上限、乘二保序、不修改输入、非法 workers、关闭与 nil channel 等现有约束。仅 `package example`、标准库、当前目录 Go 文件、最终最多 8 文件/64KiB；不接受多包、第三方依赖、go.mod 或开放式命令。服务端注入 `server_acceptance_test.go`；模型自己的测试允许合理修复，可信测试不可弱化。

从代码确认的现有基础：`contracts.py` 校验文件名、大小、数量/重复；`nodes.py` 解析围栏、保留服务端测试、3 次模型/3 次验证/1 次检索与失败修复路由；`runner.py` 检查阶段/退出码/Go 版本并确认清理，Docker 引擎不可用不降级宿主；`service.py` JSON 消费同一 SSE 执行流、账户隔离存储、360 秒总时间及取消保存；`go_adapter.py` 保留必要源码，`usage.py` 记录失败和未知用量。以上为静态实现判断，未用此替代本次真实 Docker 验收。

尚需后续实现并由服务端强制执行的不变量：最终注入可信测试后计算 artifact_hash；验证/审查必须绑定当前完整产物；`validation passed && review approve && requirements_complete && blocking_issues == 0 && hash matched` 才能通过；每次源码变化重新验证和审查；同一失败产物无进展则停止；环境不可用、整体超时、取消直接保存终态。要求条目完整不等于语义正确，语义需源码审查及不可改独立测试证据支持。

预算沿用计划目标而不是声称当前已具备：首次生成后最多 2 次修复；正常模型最多 7 次，异常共享重试 1 次，总计最多 8 次（失败请求/重试都计入，SDK 隐式重试关闭）；检索最多 1 次，验证最多 3 次；单一 360 秒截止时间，生成 120 秒、主 Agent 60 秒、验证 90 秒均取剩余时间较小值；清理须有界且是否已完成需证据。未知 Token/费用不能当 0，真实模型评测必须先获得用户明确累计费用上限。

### 剩余问题与下一步入口

1. **环境阻塞**：为新版准备含 `requirements-dev.txt` 的独立 Python 环境；当前可临时借用核心包，但缺 pytest，且公共 PyPI DNS 不通。不能用裁剪测试集或自造 pytest 替身替代完整回归。
2. **环境阻塞**：恢复真实 cl100k_base 词表缓存（并校验发行包摘要），重跑 Agent、全部加固、6 条固定模型路径及 Go/上下文 pytest；尤其复核异常处理测试是否命中预期失败原因。
3. **环境阻塞**：Docker Linux 引擎启动且固定镜像就绪后，设置 `AIROBOT_TEST_DOCKER=1` 运行计划要求的真实沙箱用例与 `eval/run_go_eval.py --fixtures`，分别保留实际报告，不沿用历史通过数字。
4. **可选环境待准备**：Playwright/浏览器缺失，UI 验收留待相关阶段；本机 Python 3.11 与 CI 环境未运行。
5. **未授权执行**：真实模型评测尚无累计费用上限，不运行 live、RAGAS 或模型对照；不据替身测试推断效果提升。
6. S1 的输入已准备：基线、复用取舍、现有服务端检查与缺项明确；下一次执行需重新核对 Git/本日志/源码指纹及环境，不能把本次部分回归当作完整绿灯。


## S0.1 / T01 补验：独立环境、真实 Token 计量与基线恢复

执行日期：2026-10-17，Asia/Shanghai。本轮命令 UTC 起点 `2026-10-17T03:28:08.598062+00:00`，完成 `2026-10-17T03:38:33.884318+00:00`（当地时间约 11:28 起）。本轮记录追加于原 S0，不改写其失败、阻塞或通过结论；原日志完整快照见 [execution-log-before.md](evidence/s0.1-20261017/execution-log-before.md)。原 S0 证据文件逐一 SHA-256 校验未变，原 artifact-manifest 内日志摘要对应此快照；追加日志后不重生成旧清单。完整本轮结果见 [summary.json](evidence/s0.1-20261017/summary.json)，实际命令/起止/退出码/输出摘要见 [commands.json](evidence/s0.1-20261017/commands.json)。

目标与范围：恢复新版独立开发环境与真实 cl100k_base 计量，补跑原基线及真实 Docker 验收。仅新增本轮证据、独立 `.venv`（含可复用词表缓存/激活脚本）并追加本日志；没有实施 S1，没有修改生产代码、测试、依赖声明、CI 或项目 Dockerfile；旧项目只读，未安装包、未作为本轮验收解释器。没有裁剪测试集、pytest 替身、计数器替换或词表伪造。

### 源码与环境

HEAD/分支保持 `1ea7e6b7abbde3bd1a5963f03cd142fac553685a` / `main`。开始和结束的 tracked/staged diff 都为空，SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`；沿用 S0 指纹算法，132 文件清单 SHA-256 仍为 `0821cec6571ed888c3d37f853c3ea736c01687bdd7ae26d73019b5c4921e7c24`，逐文件与原 S0 一致。新旧目录的前后快照见 [source-before.json](evidence/s0.1-20261017/source-before.json) / [source-after.json](evidence/s0.1-20261017/source-after.json)，原 S0 证据指纹见 [s0-evidence-before.json](evidence/s0.1-20261017/s0-evidence-before.json)。原有未跟踪计划文档及全部历史结果保留，未创建提交。

新版解释器：`/Users/xumanchun/Documents/agent项目/AI-Robot-latest/.venv/bin/python`，Python 3.13.13，`include-system-site-packages = false`。先从 S0 `borrowed-packages.txt` 生成 [s0-constraints.txt](evidence/s0.1-20261017/s0-constraints.txt)，运行 `python3 -m venv .venv`，再以有效 certifi CA、官方 PyPI、`-r requirements-dev.txt -c docs/evidence/s0.1-20261017/s0-constraints.txt` 安装。与 S0 共有的全部已安装包版本均未变化，关键版本保持 FastAPI 0.141.1、Pydantic 2.13.5、LangChain 1.3.18、langchain-core 1.6.1、langchain-openai 1.1.9、LangGraph 1.2.11、tiktoken 0.14.0、httpx 0.28.1、tenacity 8.5.0。新增缺失的开发依赖 pytest 9.1.1、pluggy 1.7.0、iniconfig 2.3.1；原因是原 S0 未安装 pytest。可选 RAGAS/重排依赖未安装。安装、`pip check` 均退出 0；实际解析/下载记录见 [pip-install-report.json](evidence/s0.1-20261017/pip-install-report.json)，完整版本见 [freeze.txt](evidence/s0.1-20261017/freeze.txt)。

网络分类：沙箱内 PyPI/词表域名 `gaierror [Errno 8]`，失败发生在 DNS 阶段，不能称为 TLS 错误；沙箱外两域名 DNS 成功，使用 pip 自带 certifi CA 访问公共资源均 HTTP 200，证明此前是沙箱内解析限制。安装后的真实词表下载改用新版 `.venv` 的 certifi。记录见 [network-sandbox.txt](evidence/s0.1-20261017/network-sandbox.txt)、[network-outside-sandbox.txt](evidence/s0.1-20261017/network-outside-sandbox.txt)。没有关闭 TLS 校验，没有 trusted-host；没有向旧环境安装包。

### 真实词表与离线边界

从当前安装的 `tiktoken_ext.openai_public.cl100k_base` AST 读取官方 URL 和 `expected_hash`，从 `https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken` 实际下载 1681126 字节。词表 SHA-256 `223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7` 与该版本声明完全一致；缓存键按 tiktoken URL SHA-1 为 `9b5ad71b2ce5302211f9c61530b329a4922fc6a4`。来源、CA 摘要、声明源码摘要和缓存路径见 [token-cache.json](evidence/s0.1-20261017/token-cache.json)。缓存位于新版 `.venv/tiktoken-cache`；可在项目根执行 `source .venv/activate-s01.sh` 复用解释器、缓存和 CA，未改 `.env`。

新进程在 DNS/IPv4/IPv6 connect 全部拦截条件下实际加载 cl100k_base（词表规模 100277），完成中英文 encode/decode 往返；见 [token-cache-offline.txt](evidence/s0.1-20261017/token-cache-offline.txt)，退出 0。断网保护自检实际触发预期拒绝，单独记账；业务测试的 [offline-network-audit.txt](evidence/s0.1-20261017/offline-network-audit.txt)、异常观测及 Docker Python 测试审计均为 0 字节，即没有业务外连尝试。公共资源准备与 Docker 镜像下载明确不属于离线测试；聚合 commands 对词表下载行的原始 `network_guard=true` 误标进行了透明更正，原始分阶段记录未覆盖。

测试子进程清除继承的 AIROBOT/OPENAI/LangChain/LangSmith 配置、禁止 dotenv、清空模型/Embedding 密钥及外部 Go/MQ 配置、关闭追踪与重排；固定模型与检索替身由原测试注入。真实模型、Embedding、RAGAS、live 和真实模型对照均未执行，费用调用 0；未得到累计费用上限，不据替身结果声称真实模型效果提升。

### 本轮实际运行结果

下表 `P` 为新版 `.venv/bin/python`，不是旧项目解释器。完整参数以 commands.json 为准；统计来自原脚本输出和实际 pytest JUnit XML，不把重叠运行次数相加作为独立覆盖量。

| 检查 / 实际命令 | 退出码 | 本次通过 / 失败 / 跳过 | 独立证据 |
| --- | --- | --- | --- |
| `P -m compileall -q app eval scripts tests`；服务导入冒烟 | 0 / 0 | 语法通过；新版模块路径确认、14 路由 | `syntax.txt`、`import-smoke.txt` |
| `P tests/test_stability.py` | 0 | 6 / 0 / 0 | `script-stability.txt` |
| `P tests/test_integration.py` | 0 | 12 / 0 / 0 | `script-integration.txt`；模拟 HTTP/检索 |
| `P tests/test_agent.py` | 0 | 5 / 0 / 0 | `script-agent.txt`；真实 LangGraph、固定模型 |
| `P tests/test_tracing.py` | 0 | 3 / 0 / 0 | `script-tracing.txt` |
| `P -m unittest discover -s tests -p test_hardening.py -v` | 0 | 26 / 0 / 0 | `hardening.txt` |
| `P eval/run_agent_eval.py` | 0 | 6 路径通过 / 0 / 0 | `agent-fixtures.txt`；knowledge/article/combined/failure/budget/direct |
| Go 专项 `P -m pytest tests/test_go_*.py -q -ra`（实际参数为四个文件逐一展开） | 0 | 24 / 0 / 22 | `go-pytest.txt`、`go-pytest.xml`；真实沙箱开关未启用时的独立记录 |
| 上下文专项 `P -m pytest tests/test_context_*.py -q -ra`（实际逐一展开十个文件） | 0 | 71 / 0 / 0 | `context-pytest.txt`、`context-pytest.xml` |
| 完整离线 `P -m pytest tests -q -ra` | 0 | 147 / 0 / 22（共 169） | `full-pytest.txt`、`full-pytest.xml`；跳过仅原有真实 Docker 开关，下一行另行全部实际执行 |
| `AIROBOT_TEST_DOCKER=1 P -m pytest` 全部四个 Go 模块 | 0 | 46 / 0 / 0（含上述 22 个真实沙箱用例） | `docker-pytest.txt`、`docker-pytest.xml` |
| `AIROBOT_TEST_DOCKER=1 P eval/run_go_eval.py --fixtures --output docs/evidence/s0.1-20261017/go-fixtures-report.json` | 0 | 9/9 最终通过；首次 3/9，其余编译/行为缺陷被拦截并修复 | [go-fixtures-report.json](evidence/s0.1-20261017/go-fixtures-report.json)、`go-fixtures.txt`；真实 Docker，固定输出无模型请求 |

异常分支特别复核：保留原加固测试断言，额外通过源码异常事件和 SSE 观测记录：`test_stream_failure_does_not_commit_partial_answer` 实际输出 token `部分答案`，命中原 `tests/test_hardening.py:340` 的 `RuntimeError("流中断")` 后只发出 1 个 error，原内存未提交断言通过；没有以词表缺失替代预期错误。向量服务失败（42）、工作线程临时故障（249）、文章服务不可用（279）也都实际命中。见 [exception-witness-v2.json](evidence/s0.1-20261017/exception-witness-v2.json)。首次观测脚本只设置主线程 trace，漏记 249 的线程异常，补充观测命令退出 1（原 26 项仍通过），该失败原样保留于 `hardening-exception-witness.txt` / `exception-witness.json`。v2 新增 threading trace 后原 26 项通过、四处异常全部观测到、命令退出 0；这是证据脚本修正，没有修改基线测试或应用。本轮未发现需要修复的基线代码失败。

### 真实 Linux 沙箱与镜像恢复

Docker Desktop `desktop-linux` 引擎实际启动，Server 29.7.2、Linux/aarch64。原 `docker build -t airobot-go-validator:1.26.2 sandbox/go` 首次退出 1，原因是守护进程请求 Docker Hub 固定摘要 manifest 超时（约 121 秒）；不是 Go 编译失败，不是观察到的证书错误。失败与初始镜像缺失证据分别保留为 `docker-build.txt`、`docker-image.txt`。

宿主使用有效 CA 访问官方 registry/auth 成功，官方索引 SHA-256 与项目 Dockerfile 锁定值 `47ce5636e9936b2c5cbf708925578ef386b4f8872aec74a67bd13a627d242b19` 完全一致；从此索引选择 Linux ARM64/v8 manifest `3fc85666d679424f406bbe27d9ffb24df50d5d800380f365c9e7cf6778072a75`，逐个校验 config 和全部 layers 摘要/长度，构建本地 OCI layout。随后使用 `docker build --build-context <原锁定镜像引用>=oci-layout:///<已校验目录>@sha256:<该平台manifest> -t airobot-go-validator:1.26.2 sandbox/go`，原项目 Dockerfile 和 runner/entrypoint 原样执行，退出 0。没有换基础版本、没有改源码、没有重置 Docker 数据、没有宿主 Go 验收或降级 TLS。两处镜像源探测只返回 HTTP 401，未用于最终镜像。实际源链与恢复命令见 [golang-oci-provenance.json](evidence/s0.1-20261017/golang-oci-provenance.json)、`oci-download.txt`、`docker-build-oci.txt`、`oci-recovery-commands.json`。

固定验证镜像 ID `sha256:381dd0955d9414dc0debedafb6201a28d4da15b32ce0883310a5e4430fa2d4af`，平台 linux/arm64，实际 inspect 见 [docker-image-ready.txt](evidence/s0.1-20261017/docker-image-ready.txt)。镜像已保存在 Docker 引擎中；OCI 中间下载目录 `/private/tmp/airobot-s01-golang-oci` 是临时资源，恢复脚本和完整摘要链保存在本轮证据中。Docker 守护进程直连 Hub 路径仍有网络限制，这是后续重新拉取镜像的操作限制，当前实际沙箱验收已完成。

真实沙箱测试覆盖编译/测试/vet/策略拦截、取消/超时/重复取消清理、非特权身份、只读文件系统、宿主秘密隔离、资源与断网配置、可信服务端测试保留，以及实际 JSON/SSE/账户隔离。9 条固定输出 Go 评测共 15 次实际验证、15 次本地 FixtureModel 调用（不是外部模型请求），全部 attempt 的 `container_removed=true`；`docker-containers-after.txt` 中没有残留 `airobot-go-*` 容器。

### S1 条件与仍待验证项

S0.1 环境恢复与基线补验完成。S1（T04–T06）可开始：独立依赖/真实计量/原 Go 与上下文回归/固定真实沙箱已具备，可实现 TaskSpec、CodeArtifact、ReviewReport、RepairRequest 及旧报告默认值兼容；可实现最终可信文件 hash、绑定版本的审查/验证、必要需求完整性与无 blocking 的确定性判定；可实现角色配置、共享调用/重试/验证/截止时间预算和非法配置拒绝，并在本环境运行反例测试。上述是进入条件，不是声明 S1 已实现或 M1–M5 已完成。

仍待完成：Playwright 当前 MODULE_NOT_FOUND，Dashboard 浏览器验收未运行；本机仅 Python 3.13.13，Python 3.11 未安装/未验证；远程 CI 未触发/未验证；真实模型/Embedding/RAGAS/模型对照未执行，需明确累计费用上限后另行授权和记录。费用/延迟与真实模型质量无本轮结论；S1–S9 新增多 Agent 契约、闭环、预算、UI 等仍按实施计划逐步开发验证。操作性限制是 Docker 引擎直连 Hub manifest 超时，已有同摘要验证镜像可继续本地开发与验收。
