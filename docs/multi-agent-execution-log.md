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

## S1 / T04–T06：契约、配置与服务端判定

执行日期：2026-10-17，Asia/Shanghai；初轮验证时间 11:48–11:55，独立环境与真实 Docker 补验从 12:00 开始。开始时读取适用说明、计划、S0 执行记录和当前 Git 状态，但没有完整处理已有 S0.1 补验段，直到终检才纠正，见下文环境更正。仍在新版实际根目录、`main`、HEAD `1ea7e6b7abbde3bd1a5963f03cd142fac553685a`，原 S0/S0.1 记录、证据和两份未跟踪计划均保留。没有后续开发提交，也没有回退、覆盖旧模块或执行旧多 Agent 实现。

目标与依赖：先定义合法状态与服务端不变量，再实现 T04 数据契约、T05 确定性判定及 T06 配置。依赖 S0 的范围与复用分析；纯契约测试只需 Pydantic 和 unittest。完整原业务及真实沙箱最终使用 S0.1 已恢复的新版独立环境；初轮的旧解释器缺项不是新版环境缺项。

验收条件：服务端拒绝机器失败但 approve、approve+blocking、陈旧/缺失 hash、必要需求漏查及非法配置；hash 包含最终可信测试；报告不能重标版本；新终态不能无证据自报成功；旧嵌套报告继续读取；记录真实测试结果及环境限制。状态表先行写入 [multi-agent-state-contract.md](multi-agent-state-contract.md)，随后实现，没有先调用模型再靠提示词维持规则。

| 任务 | 状态 | 变更文件 | 本次交付与边界 |
| --- | --- | --- | --- |
| T04 | 完成 | `app/go_validation/contracts.py`；`tests/multi_agent_fixtures.py`、`tests/test_multi_agent_contracts.py` | TaskSpec、Requirement/AcceptanceCriterion、冻结 CodeArtifact、ReviewReport/Issue/Check、RepairRequest、RemainingBudget；ID/类型/长度/枚举/关联校验；旧结果新增字段及嵌套 validation 默认值 |
| T05 | 完成（独立策略组件） | 新增 `app/agents/go_workflow.py`；`tests/test_multi_agent_review.py`；`docs/multi-agent-state-contract.md` | 合法 phase 流转、终态不可推进、成功/审查重试/修复/异常/无进展/额度不足的纯判定；`GoTaskResult(multi-v1, passed)` 再次强制检查完整证据；尚未接入主图 |
| T06 | 完成（配置及校验） | `app/config.py`、`.env.example`；`tests/test_multi_agent_config.py` | 默认关闭，角色模型可分别配置并继承现有模型，严格额度/时间/上下文窗口校验，非法配置导入即失败；配置与上下文实验开关独立；实际请求预占、共享账本及取消编排仍属 S4 |
| T04/T05 必要绑定补充 | 完成；真实容器补验通过 | `app/go_validation/runner.py`；`tests/test_multi_agent_runner_binding.py` | 验证器根据实际提交副本计算 hash，拒绝沙箱声称的不同 hash；失败报告也保留提交版本。只做局部增量，没有改变 Docker 权限或宿主降级规则 |
| 执行证据 | 完成 | 本文件；`docs/evidence/s1-20261017/` | 原始失败与最终通过输出、完整 argv/退出码、源码及未提交差异指纹、证据校验清单 |

### 服务端行为与兼容策略

- `freeze_artifact()` 先经现有 `with_acceptance_tests()` 注入本场景原样可信测试，再冻结完整文件并计算 SHA-256；文件名按现有 ASCII 单层规则验证后排序，完整 UTF-8 内容不截断、不改写空白/换行。顺序不影响 hash，源码、模型测试、可信测试或文件名改变均改变 hash。
- CodeArtifact 重新加载时重算 hash、核对可信测试，冻结对象和内部文件，给 runner 的 bundle 是副本。`DockerGoRunner.validate()` 对将发送的副本独立算 hash；`bind_validation()` 只补 task_id/artifact_id/round，拒绝缺 hash 的旧报告和任何已有不同版本，不能给历史报告换标签。
- `decide_after_review()` 重新校验对象，即便调用方使用 `model_copy`/`model_construct` 绕过初次校验也不能直接放行。成功同时要求：完整四阶段/Go 版本/退出码/未截断日志/清理确认通过；验证与审查的 task/artifact/round/hash 对齐当前快照；审查 approve；服务端 TaskSpec 的所有必要需求均有显式 pass 和证据；无 blocking。
- approve+blocking 是非法审查，进入共享异常重试策略或 review_error；缺必要条目同样不能放行，显式 fail/unknown 或阻断问题触发修复/停止。requirement_checks 的完整性仅证明结构覆盖；真实语义仍需完整源码审查和不可改的独立行为测试，未宣称形式化正确或模型效果提升。
- RepairRequest 交叉检查同一任务、上一版本完整源码、双报告及下一轮次，并复用服务端判定拒绝已成功、环境故障、无法判断或额度不足的修复任务。新 `GoTaskResult` 的 passed 还核对最终 attempt.bundle 与 artifact 同版本，不能只设置 status。
- 读取旧 JSON 默认 workflow_version=single-v1，task_spec=None，reviews/artifacts/agent_calls 为空，validation 绑定字段为 None。实际读取仓库中的旧固定输出报告验证嵌套兼容；历史 passed 的含义保留，但无版本绑定不能用于新成功门。
- 配置有首版硬上限：正常模型≤7、共享重试≤1、总模型≤8、修复≤2、验证≤3、检索≤1、总时间≤360 秒；阶段和清理上限受总时间约束。拒绝未知配置名、非法布尔/整数、负数/越界、NaN/Infinity、无效模型名及启用后未知/不足的模型窗口。默认 off；这些字段不会让尚未接入的多 Agent 图提前运行。

S1 只实现上述契约、配置和独立判定；S2 角色组件、S3 主图/审查闭环、S4 请求发送前共享预算预占与统一截止时间尚未实施。没有把“配置存在”当作“所有实际外部请求已经被该预算拦截”。现有普通聊天和原 Go 图保留，导入冒烟确认默认 flag=false、原图节点仍在。

### 本次实际验证及修复过程

初轮解释器 `P=/Users/xumanchun/Documents/agent项目/AI-Robot-FastAPI-LangChain-RAG-CrewAI-Agent-/.venv/bin/python`（Python 3.13.13 / Pydantic 2.13.5），仅借用第三方依赖，应用及测试均从新版 cwd 加载，没有修改旧源码或安装依赖。该选择遗漏了 S0.1 已准备好的独立环境，下面保留其真实结果，不能据此判断新版仍缺依赖。完整命令见 [commands.json](evidence/s1-20261017/commands.json)。

| 验证命令/类别 | 退出码 | 本次实际结果 | 输出证据 |
| --- | --- | --- | --- |
| `P -m unittest discover -s tests -p 'test_multi_agent_*.py' -v` 首轮 | 1 | **实际失败**：30 项，1 FAIL + 1 ERROR；不是环境跳过 | `contracts-review-config-1.txt` |
| 同命令第二轮 | 0 | **通过 30**（中间版本，不作为最终版本证明） | `contracts-review-config-2.txt` |
| 加入验证器绑定测试后的第三轮 | 0 | **通过 33**（中间版本） | `contracts-review-config-runner-3.txt` |
| 同命令最终版本 | 0 | **通过 33，0 failure/error/skip**：契约 11、策略 14、配置 5、Docker 客户端替身绑定 3 | [contracts-review-config-runner-final.txt](evidence/s1-20261017/contracts-review-config-runner-final.txt) |
| `P -m compileall -q app tests eval scripts` 最终版本 | 0 | **通过**，语法 | `syntax-delivery.txt` |
| 导入 app.main / settings；此前检查原图节点 | 0 | **通过**，新版路径、14 路由、默认 disabled；非服务启动/模型联调 | `import-smoke-delivery.txt`、`import-smoke-final.txt` |
| `P tests/test_stability.py` 最终版本 | 0 | **通过 6** | `regression-stability-delivery.txt` |
| `P tests/test_integration.py` 最终版本 | 0 | **通过 12**，外部服务替身 | `regression-integration-delivery.txt` |
| `P tests/test_tracing.py` 最终版本 | 0 | **通过 3** | `regression-tracing-delivery.txt` |
| `P -m pytest tests/test_go_contracts.py tests/test_multi_agent_contracts.py tests/test_multi_agent_review.py tests/test_multi_agent_config.py -q` | 1 | **旧解释器环境失败**，No module named pytest，未收集/执行；后续独立环境已补验 | `pytest-go-and-multi.txt` |
| `P -m pytest tests -q` | 1 | **旧解释器环境失败**，同上；不代表新版环境阻塞 | `pytest-all.txt` |
| 沙箱内 `docker version` | 1 | **沙箱访问权限阻塞**，permission denied；后续沙箱外探测及实际验收成功 | `docker-version.txt` |
| `git diff --check` | 0 | **通过**，tracked diff 格式检查；新增 Python 另经 compileall/unittest | `diff-check.txt` |

首轮修正依据：计划允许收紧额度，所以 `max_model_calls=7` 且正常额度 7 / 共享重试上限 1 是合法配置；错误的拒绝预期改为总额度 6 < 正常额度 7 的真实非法反例，并另加总额 7 的正向断言。篡改产物测试最初在建立验证报告时已被绑定函数拒绝，没有执行到待测路由；改为传入原始合法验证/审查报告，让路由实际接收篡改产物并断言 artifact_error。没有删除有效断言、放宽容差、忽略异常或增加 skip。最终又补充有效模型继承校验，保证启用时空默认模型也在启动前拒绝。

**指定反例的实际证据**：机器 failed+approve 只能 repair/failed；approve+blocking 在构造及路由重校验处拒绝；双报告 hash、task_id、artifact_id、round 任一错配均拒绝；必要需求漏查不能被报告缩小清单；配置非法既在模型构造检查，也在独立子进程 `import app.config` 之前拒绝启动。额外覆盖可信测试重算 hash 后篡改、历史报告重标、错误文件/行号、环境终止、无进展、两轮上限及后续生成/审查/验证额度不足。

### 独立环境更正与最终补验

终检发现已有 S0.1 补验段以及 `.venv/activate-s01.sh`：新版 `.venv/bin/python`、pytest 9.1.1、Pydantic 2.13.5、真实词表缓存已经具备。前述“缺 pytest/词表”的判断只适用于错误选择的旧解释器。已更正启动器使用新版独立解释器，设置 `TIKTOKEN_CACHE_DIR=.venv/tiktoken-cache`，使用 S0.1 的网络保护（禁 DNS/TCP，允许 Docker Unix socket），重新执行本次最终源码上的完整回归，没有下载安装包、替换计数器或修改基线测试。

首次证据终检还发现 S1 文本被插在 S0 与 S0.1 之间，导致原日志前缀校验失败（不是内容丢失）。依据追加前日志的完整 SHA-256 `e017932f22b2d3bf97649b12dba6b5170080a6e8950c92eb7b44d5bd77f78ab0` 精确恢复原 S0+S0.1 字节，并将 S1 放到文末，保存 [execution-log-before.md](evidence/s1-20261017/execution-log-before.md)。原检查没有删除或放松；终检必须同时验证 S0 与 S0.1 原证据及整个既有日志前缀不变。

下表 `N=/Users/xumanchun/Documents/agent项目/AI-Robot-latest/.venv/bin/python`。Docker 因 Unix socket 权限要求在沙箱外运行，工具权限审查通过；没有拒绝后绕过权限。Docker 命令独立记录于 [docker-commands.json](evidence/s1-20261017/docker-commands.json)。

| 最终补验 | 退出码 | 本次实际结果 | 证据 |
| --- | --- | --- | --- |
| 独立解释器/包版本与 `N -m pip check` | 0 / 0 | 新版路径、Python 3.13.13 / pytest 9.1.1 / Pydantic 2.13.5；依赖元数据检查通过 | `independent-environment.txt`、`independent-pip-check.txt` |
| `N -m unittest discover -s tests -p 'test_multi_agent_*.py' -v` | 0 | **33 通过，0 失败/跳过** | `independent-unittest.txt` |
| `N -m pytest tests -q -ra --junitxml=.../full-pytest.xml` | 0 | **180 passed、22 skipped、110 subtests passed**；跳过仅原有 Docker 开关；JUnit 312 条包含 110 子测试，不能和主测试重复相加 | `full-pytest.txt`、`full-pytest.xml` |
| `N eval/run_agent_eval.py` | 0 | **6/6 固定模型路径通过**，包括失败和预算路径；非质量评测 | `agent-fixtures.txt` |
| 沙箱外 `docker version` / 固定镜像 inspect | 0 / 0 | Linux/arm64 引擎与固定 Go 1.26.2 镜像实际可访问；镜像 ID 与 S0.1 相同 | `docker-version-restored.txt`、`docker-image-restored.txt` |
| `AIROBOT_TEST_DOCKER=1 N -m pytest` 四个原 Go 模块 + 新 runner binding 模块 | 0 | **49 passed，0 skipped**：原 46 项中含 22 项真实沙箱；另 3 项是明确的客户端替身测试 | `docker-pytest.txt`、`docker-pytest.xml` |
| `N .../real_gate_probe.py` | 0 | 两条真实 Docker + 审查报告替身：正确代码 passed；提前返回的代码机器 failed，即使 approve 也只 repair/running | `real-gate.txt`、[real-gate-report.json](evidence/s1-20261017/real-gate-report.json) |
| `docker ps -a --filter name=airobot-go-` | 0 | 未发现残留测试容器 | `docker-containers-final.txt` |

固定镜像为 `sha256:381dd0955d9414dc0debedafb6201a28d4da15b32ce0883310a5e4430fa2d4af`，未重新构建或更换工具链。真实 gate 探测保留每份完整代码、可信测试、机器阶段输出、当前 hash、替身审查及服务端决策；两份验证报告均确认容器删除、hash 与对应审查一致。三个 jieba SyntaxWarning 保留，未忽略必需检查；S0 词表造成的回归中断已由本次独立环境全量测试实际消除。

分开报告：**报告/客户端替身**为 33 项 S1 机制用例，**固定模型**为 6 条原 Agent 路径，均不代表角色自主能力或模型质量；**真实 Docker**为上述专项及两条 gate 探测，审查仍明确使用替身，不宣称完整多 Agent 已接入；**真实模型评测**未运行，尚无用户明确累计费用上限。离线全量实际跳过 22 项，已在 Docker 专项全部真实执行；没有剩余的必需 pytest/Docker 环境阻塞。业务网络审计为空，无真实模型/Embedding 请求。

### 版本、未提交差异与剩余项

最终交付代码 HEAD 仍为 `1ea7e6b7abbde3bd1a5963f03cd142fac553685a`；无提交。最终 tracked 未提交差异 SHA-256（`git diff --binary HEAD` 原始字节）为 `b167408c2ebd60aeacd03ce1b87aea8ff36dfc86b7f2c0fc86cf47cab9a33b10`。最终源码/相关文档清单含原有未跟踪文件与新增模块/测试，共 139 文件，按 S0 的同一算法计算为 `c333b4d3d199dce1e302996402c9dc8d0c55d7c89458b949927f38d111fe7547`。最终 33 项测试、21 项回归和语法/导入检查均绑定此指纹；前两轮中间结果不作为最终版本证明。

完整逐文件前后摘要见 [source-before.json](evidence/s1-20261017/source-before.json) / [source-after.json](evidence/s1-20261017/source-after.json)；本日志及证据目录按原规则排除，当前交付的逐文件摘要另见 [artifact-manifest.json](evidence/s1-20261017/artifact-manifest.json)。原 S0+S0.1 日志保留为完整前缀，原证据不改；历史 artifact manifest 中日志摘要各对应当时的快照，不能拿旧摘要校验追加后的整份日志。终检见 [final-checks.txt](evidence/s1-20261017/final-checks.txt)。

剩余项：Python 3.11、远程 CI、Dashboard 浏览器与真实模型质量未验证；均未作为本步已通过结果。Docker Unix socket 仍需沙箱外工具权限，当前镜像可用。S2–S4 接入时必须复用当前 gate 和绑定函数，不能由模型选择最终状态、重算旧报告标签或各角色独立增加重试额度。只完成 S1，没有推进 S2，也没有宣布完整多 Agent 产品验收或效果提升。

## S2 / T07–T11（组件部分）：主 Agent 与代码子 Agent 角色组件

执行日期：2026-10-17，Asia/Shanghai。开始前核对：仍在 `main`、HEAD `1ea7e6b7abbde3bd1a5963f03cd142fac553685a`，S0–S1 证据与两份未跟踪计划保留，无后续提交。解释器为 S0.1 恢复的新版 `.venv/bin/python`（Python 3.13.13、pytest 9.1.1、Pydantic 2.13.5），并设置 `TIKTOKEN_CACHE_DIR=.venv/tiktoken-cache` 使用已校验词表；本轮全部验证不调用真实模型，模型角色由记录实际输入的 `ScriptedModel` 替身承担。实际命令、退出码与输出见 [commands.txt](evidence/s2-20261017/commands.txt)。

目标与边界：实现可独立调用、模型独立注入的两个角色组件；主 Agent 负责计划与审查，代码子 Agent 负责生成与修复。**S2 只交付组件，不接入主图**（S3）、不实现发送前预算预占与统一截止时间（S4）；现有单流程 Go 图与普通聊天路径保持原样（导入冒烟确认原图节点与 14 路由不变、开关默认关闭）。

| 任务 | 状态 | 变更文件 | 本次交付与边界 |
| --- | --- | --- | --- |
| T07 计划 | 完成（组件） | 新增 `app/agents/supervisor.py` | `SupervisorAgent.plan()`：模型输出 JSON，服务端锚定 `original_requirement`（逐字来自用户请求）、`scenario`、`task_id`；固定接口通过 `SCENARIO_SPECS` 注入提示词且模型不能改写 |
| T08 代码子 Agent | 完成（组件） | 新增 `app/agents/code_agent.py` | `CodeAgent.generate()/repair()`：任务本地实例持有首轮检索资料与历次产物；修复复用已有资料；输出经现有 `parse_model_output` 围栏解析与文件契约校验 |
| T09 复用 | 完成（无改动复用） | — | 直接复用 `nodes.parse_model_output`、`fixtures.with_acceptance_tests`、S1 `freeze_artifact`：非法文件拒绝、模型不能提交 `server_acceptance_test.go`、可信测试每轮原样注入、模型测试允许随修复更新 |
| T10 审查 | 完成（组件） | `app/agents/supervisor.py` | `SupervisorAgent.review()`：审查输入由服务端从完整产物（逐字、不截断）与机器验证报告（含实际阶段日志）重建；**不读取代码子 Agent 的 `change_summary`**；审查报告版本字段（task/artifact/hash/round）只来自服务端产物，模型自报被忽略；构造后再过 `check_context`（文件/行号/需求引用必须匹配实际源码） |
| T11 交接（部分） | 完成角色侧 | `supervisor.py`、`code_agent.py`、新增 `app/agents/role_runtime.py` | 计划→生成交接保留原始需求、固定接口、分解需求与验收条件、检索资料；修复交接含上版完整源码、双报告与 blocking 问题 ID（服务端记录 `addressed_issue_ids`）；审查绑定当前 `artifact_hash` 由 S1 契约继续强制 |
| 共享执行器 | 完成 | 新增 `app/agents/role_runtime.py`；`app/agents/graph.py` | 单次调用、角色超时、取消传播、AgentCall 用量记录；输出解析失败改记该次调用 failed 但保留用量；`get_llm` 增加可选 `model` 参数支持角色模型（默认行为不变） |
| 测试 | 完成 | 新增 `tests/test_multi_agent_agents.py`；`tests/multi_agent_fixtures.py`（`artifact()` 兼容传冻结参数） | 11 项固定模型测试，覆盖下方验收点 |
| 执行证据 | 完成 | 本文件；`docs/evidence/s2-20261017/` | 命令、输出与说明 |

### 服务端锚定与隔离设计

- **消息由服务端重建**：两个角色的每次调用都从结构化服务端输入重建消息（`SystemMessage` 角色提示词 + `HumanMessage` 任务数据），实例间不共享消息或任务状态；任务内必要状态（计划结果、首轮资料、历次产物）显式持有在实例上。输入侧源码展示使用 `--- FILE ---` 标记，与输出要求的 `=== FILE ===` 区分，降低修复时把展示源码（含服务端测试）原样抄回的概率。
- **审查防"只信总结"**：审查输入包含每个产物文件名与逐字内容、机器验证各阶段实际输出与退出码；`change_summary` 不进入审查提示词（测试用哨兵字符串断言缺席）。
- **角色提示词分别管理**：`PLAN_SYSTEM`/`REVIEW_SYSTEM` 在 `supervisor.py`，`CODE_SYSTEM` 在 `code_agent.py`；共享的只有中性渲染函数（`render_task/render_files/render_validation`）。参考资料超长显式截断并标注（16K 字符）；源码任何路径不截断；阶段日志 8K/阶段显式截断并标注。
- **异常分类**：`AgentError.kind ∈ {output, timeout, call}`，取消（`CancelledError`）记录后原样传播，供 S3/S4 编排分别处理格式重试、终态与进度保存。

### 本轮验收点（全部为固定模型替身，非真实模型能力结论）

| 验收点 | 对应测试 |
| --- | --- |
| 计划：原需求逐字锚定、固定契约进入提示词、需求/验收条件解析、调用与用量记录 | `test_plan_anchors_original_requirement_contract_and_records_usage` |
| 计划：非法 JSON/数组/未知需求引用/空需求 → output 错误且调用记 failed | `test_plan_rejects_invalid_output_and_records_failed_call` |
| 计划：请求失败与超时是不同 kind | `test_call_failure_and_timeout_are_distinct_kinds` |
| 生成：交接含原需求+固定接口+分解需求+资料；服务端注入原样可信测试并计算 hash | `test_generate_freezes_server_tests_and_prompt_carries_handoff` |
| 生成：模型提交服务端测试文件/缺文件头/空内容 → 拒绝且用量保留 | `test_generate_rejects_model_acceptance_file_and_malformed_output` |
| 审查：实际源码逐字进入、机器输出进入、子 Agent 自述缺席 | `test_review_reads_actual_source_and_machine_report_not_subagent_summary` |
| 审查：模型自报版本字段被忽略，服务端产物为准 | `test_review_ignores_model_claimed_version_fields` |
| 审查：未知文件/需求/行号越界/approve+blocking/缺 verdict → 拒绝 | `test_review_rejects_invalid_locations_and_illegal_verdict_combination` |
| 修复：上版完整源码+机器失败+审查修复指令+原需求+复用资料；新轮次、blocking 问题 ID 记录、可信测试每轮原样、模型测试可更新 | `test_repair_carries_full_context_and_freezes_new_round` |
| 隔离：两个任务共用角色模型对象时消息互不泄漏（标记、资料来源、源码哨兵）；角色只收到各自调用；实例状态各自持有 | `test_two_tasks_isolated_even_with_shared_role_models` |
| 注入：角色模型独立注入；默认模型按 `supervisor_model/code_model` 配置并绑定角色输出上限 | `test_default_models_follow_role_configuration` |

### 本次实际运行结果

| 检查 | 退出码 | 结果 | 证据 |
| --- | --- | --- | --- |
| 新增组件测试 unittest | 0 | **11 通过** | `unittest-multi-agent.txt`（合并运行） |
| 全部多 Agent unittest（S1 33 + S2 11） | 0 | **44 通过，0 失败/跳过** | `unittest-multi-agent.txt` |
| `compileall app tests eval scripts` | 0 | 通过 | `syntax.txt` |
| 全量 `pytest tests -q -ra` | 0 | **191 passed、22 skipped（仅原有 Docker 开关）、123 subtests**（S1 基线 180+11） | `full-pytest.txt` |
| `AIROBOT_TEST_DOCKER=1` Go 四模块 + runner 绑定 | 0 | **49 passed，真实 Linux 沙箱**（引擎 29.7.2、固定镜像不变） | `docker-pytest.txt` |
| 原回归脚本（stability/integration/agent/tracing/agent-eval） | 0 | 全部通过，固定模型 6/6 路径 | `regression-scripts.txt` |
| 导入冒烟 | 0 | 14 路由、默认 disabled、原图节点完整 | `import-smoke.txt`（首轮冒烟命令自身有 Python 变量遮蔽错误，已更正重跑，见 commands.txt 注记） |
| `git diff --check` | 0 | 通过 | commands.txt 第 8 条 |

本轮未发生需要修改 S1 契约或基线代码的失败；三次中间测试失败均为本轮新测试 fixture/断言问题（计划 JSON 缺 r-wait 验收条件、隔离测试复用了 A 任务的审查回复、输出失败时的调用状态断言），按原有断言语义修正测试后通过，没有放宽任何校验。

### 剩余项与下一步

S3 输入已具备：角色组件、S1 判定门与绑定函数可被主图编排复用。尚未实施：主图接入与 LangGraph 闭环（S3，含选择开关与普通聊天回归）、发送前共享预算预占/统一截止时间（S4）、JSON/SSE 与存储扩展（S4–S5）、Dashboard（S5）。真实模型评测仍未运行（需用户明确累计费用上限）；Python 3.11、远程 CI、浏览器验收维持未验证。`AgentCall` 记录已为 S4 账本保留用量与失败分类，但 S2 不拦截任何超额调用——组件层没有预算强制，这是既定边界不是遗漏。

## S3+S4 / T12–T15（组件级闭环）：完整闭环编排与全任务共享预算

执行日期：2026-10-17，Asia/Shanghai。开始前核对：无 AGENTS.md（S0 已确认）；`main`、HEAD `1ea7e6b7abbde3bd1a5963f03cd142fac553685a`；S0–S2 全部本地改动与证据保留，无 reset/checkout/stash，无新提交。解释器为 S0.1 恢复的 `.venv/bin/python`，`TIKTOKEN_CACHE_DIR=.venv/tiktoken-cache`。实际命令、退出码与输出见 [commands.txt](evidence/s3s4-20261017/commands.txt)。

目标与边界：实现生成/验证/审查/修复完整闭环（S3）与发送前预占的全任务共享预算、绝对截止时间（S4）。关键通过条件、预算与终态全部由服务端强制。**主图与 GoTaskService 接入（开关选择入口）仍未实施**：本轮交付可调用组件 `MultiAgentGoWorkflow`，现有单流程图与普通聊天路径未改动（导入冒烟确认 14 路由、原图节点、默认关闭均不变）。

| 任务 | 状态 | 变更文件 | 本次交付与边界 |
| --- | --- | --- | --- |
| T12 闭环编排（组件级） | 完成（组件） | `app/agents/go_workflow.py` | `MultiAgentGoWorkflow.run()`：计划→检索→[生成/修复→隔离验证→审查→判定]+；主图接入与开关留待接口阶段，原图未动 |
| T13 验证器接入 | 完成 | 同上 | `_validate()`：每轮对产物副本 `reserve_validation` 后执行 runner，`bind_validation` 绑定当前版本（含失败/环境报告）；环境终态直接结束 |
| T14 修复任务与问题跟踪 | 完成 | 同上 + S1 契约 | `RepairRequest` 由服务端在判定为 repair 后构造：含原需求 TaskSpec、上版完整源码、实际错误日志、blocking 问题 ID 与修复要求；`previous_failed_hash` 跟踪无进展 |
| T15 预算/截止/无进展 | 完成 | `app/agents/go_workflow.py` | `SharedBudget`：模型 7 正常+1 共享重试+总 8、修复 2、验证 3、检索 1、绝对截止时间；发送前 `reserve_*` 预占，失败/重试不返还；阶段超时取剩余时间较小值 |
| 测试 | 完成 | 新增 `tests/test_multi_agent_budget.py`、`tests/test_multi_agent_workflow.py` | 账本 7 项；闭环 16 项（离线 14 + 真实 Docker 2） |
| 执行证据 | 完成 | 本文件；`docs/evidence/s3s4-20261017/` | 命令、输出、JUnit |

### 服务端强制要点（实现于代码，不是提示词）

- **发送前预占**：每次模型请求前 `budget.reserve_model()`（重试标记 `retry=True` 消耗全任务唯一共享异常重试）；验证、修复、检索同样先预占。预占失败抛 `BudgetExceededError`，请求根本不发出——测试用底层客户端实际输入数证明（计划+生成共 2 次后，审查模型输入数保持 1，审查请求从未送达）。
- **计数范围**：失败请求、解析重试、审查重试全部计数（无释放 API）；最终说明复用最终审查摘要，不产生额外总结调用；`get_llm(max_retries=0)` 关闭 SDK 隐式重试、`context_usage.invoke(retry=False)` 单发单计，S2 已建立、本轮沿用。
- **绝对截止时间**：`SharedBudget._deadline` 自建账起固定，不随修复轮次重置；`stage_timeout()` 取角色上限与剩余时间较小值，过期后一切预占直接拒绝（测试用注入时钟证明过期后零请求）；外层再包 `asyncio.timeout(task_timeout)` 兜底，超时映射为 timeout 终态。
- **取消传播**：`CancelledError` 全程不被吞（RoleRunner 记录 cancelled 后原样上抛，编排层 `except CancelledError: raise`）；容器清理由 runner 内部 shield 的 `_remove` 有界完成（≤15 秒，S1 既有行为，真实 Docker 套件后 `docker ps` 零残留）。
- **无进展停止**：连续失败产物 hash 相同时判定 `no_progress` 直接终止（S1 纯函数 + 编排层 `last_failed_hash` 传入），相同失败代码不会无限循环。
- **代码问题与环境问题分流**：验证 `unavailable/timeout/cancelled` 直接终态（不进入审查/修复，不让模型反复改代码）；验证器未预期异常同样映射 `unavailable`；只有代码级失败才产生修复轮次。
- **机器失败不可被 approve 覆盖 / 机器通过仍有 blocking 需修复**：均为 S1 `decide_after_review` 判定，本轮闭环按其决策路由并实测两条路径。
- **禁止复用旧报告**：每轮产物变化后重新验证、重新审查；`bind_validation` 拒绝任何版本错配，测试断言每轮 attempts/reviews 的 hash 与轮次对应当轮 artifacts。

### 五条主路径实测（模型替身 + 验证替身，另加真实 Docker 两条）

| 路径 | 结果 | 关键断言 |
| --- | --- | --- |
| 首次通过 | passed/completed | 3 次模型调用（计划+生成+审查），final_summary 复用审查摘要 |
| 修复通过 | passed/completed | 两轮产物 hash 不同；每轮验证/审查绑定当轮版本；修复输入含原需求+完整源码+实际错误日志+问题 ID+修复要求 |
| 测试通过但阻断性需求问题 | 修复后 passed | 机器 passed + revise(blocking) 仍进入修复，2 份产物 |
| 修复耗尽（approve 无法覆盖机器失败） | failed/repair_limit | 3 版本、3 验证、7 次模型调用恰好触及首版上限、2 次修复 |
| 环境不可用 | unavailable/unavailable | 无审查、无修复（模型输入停在计划+生成），不可用报告仍绑定提交版本 |

其余覆盖：决策侧与账本侧 budget_exceeded、审查格式错误共享重试一次后通过/失败、生成解析失败重试计数、过期截止零请求、取消传播后调用冻结、检索一次且失败降级、计划重试失败 generation_error、真实沙箱首次通过与修复通过（含审查输入含真实 FAIL 输出、容器清理确认）。

### 本次实际运行结果

| 检查 | 退出码 | 结果 | 证据 |
| --- | --- | --- | --- |
| 账本 unittest | 0 | 7 通过 | 命令 1 |
| 闭环 unittest（离线） | 0 | 16 项 OK，2 跳过（Docker 门） | 命令 2 |
| compileall | 0 | 通过 | `unittest-multi-agent.txt` |
| 全部多 Agent unittest | 0 | **67 项 OK**（S1 33 + S2 11 + S3/S4 23） | `unittest-multi-agent.txt` |
| 全量 pytest | 0 | **212 passed、24 skipped（全部原有 Docker 门）、132 subtests**（S2 基线 191+22 → +21） | `full-pytest.txt`、`.xml` |
| 真实 Docker 闭环 | 0 | 16 项全过，含 2 条真实沙箱闭环 | 命令 6 |
| 真实 Docker 全套 | 0 | **65 passed**（原 49 + 闭环 16），无残留容器 | `docker-pytest.txt` |
| 原回归脚本 + 固定模型 6 路径 + 导入冒烟 | 0 | 全部通过；14 路由、默认关闭、原图节点不变 | `regression-import.txt` |
| `git diff --check` | 0 | 通过 | 命令 11 |

本轮中间失败均已保留记录：修复了审查路径双重预占（预占移至调用方）、agent_calls 顺序（按步 drain 合并）；两处测试 fixture 错误（计划失败用例误用合法 JSON、微型预算违反 normal≤total 不变量）按原断言语义修正，未删除或放宽任何校验。

### 剩余项与下一步

未实施：主图/GoTaskService 接入与 `AIROBOT_GO_MULTI_AGENT_ENABLED` 选择入口（T12 后半）、JSON/SSE 事件与存储扩展（T16–T19）、Dashboard（T20–T21）、固定模型之外的评测（T26–T27）。真实模型评测仍未运行（用户未给出累计费用上限）；Python 3.11、远程 CI、浏览器验收维持未验证。组件级闭环与预算已被本轮 23 项新测试约束，后续接入主图时必须复用 `MultiAgentGoWorkflow` 与 `SharedBudget`，不得另行绕过预占或判定门。

## S2–S4 / T07–T15 独立审查：存在待修复项

执行日期：2026-10-17，Asia/Shanghai。本次为用户请求的审查，不修改业务源码或已有测试。审查目标：对照计划与 S2/S3/S4 执行提示词，核验角色边界、主图入口、服务端 gate、预算、终态及证据。依赖：当前工作区代码、已有执行记录、项目独立 .venv、固定 Docker 镜像；验收条件为设计要求在实际入口和边界反例上成立，不能仅依赖正常替身路径通过。适用仓库说明已检查，未发现额外 AGENTS.md；保留已有本地差异。

状态：**审查完成，S2–S4 整体不通过验收**。2 项 P1、5 项 P2。详见 [审查发现和复现说明](evidence/review-s2s4-20261017/review.md)。T12 入口仍未实现；T11/T15 运行时上下文额度及超时、清理、用量边界待修复。T16–T19/S5 不在本次审查完成声明内。

### 本次代码版本与改动范围

- 实际根目录：`/Users/xumanchun/Documents/agent项目/AI-Robot-latest`；分支 `main`；HEAD `1ea7e6b7abbde3bd1a5963f03cd142fac553685a`，无新提交。
- 已跟踪未提交差异 SHA256：`421f2f86ed91a55d6ad2df075d2f4c63558d7f43417ae47e3adc7a3c027c275c`；暂存区为空。
- 完整源码/相关文档清单（含未跟踪源码，排除 execution-log/evidence/忽略文件）SHA256：`4dd5a0b0dc236d79cf66aade27c96de889e2e78448409ca617a40cb32086b6dd`；审查前后逐文件摘要一致，见 `source-before.json` / `source-after.json`。
- 本次变更仅本记录的追加段，以及 `docs/evidence/review-s2s4-20261017/` 下复现脚本、报告、原始输出、命令元数据、版本指纹；未修改 app、tests、配置或旧目录。

### 发现与实际反例

| 编号 | 级别 / 任务 | 位置 | 本次实际观察 / 剩余修复 |
| --- | --- | --- | --- |
| R1 | P1 / T12 | `app/agents/graph.py:277` | enabled=true 仍经 service 得到 single-v1、passed、0 reviews；需接入主图开关路由 |
| R2 | P1 / T11、T15 | `app/agents/role_runtime.py:114` | 角色输入上限 1 token，首请求估算 599 token，仍发送 3 请求并 passed；需独立于 context_mode 的角色发送前额度检查 |
| R3 | P2 / T13、T15 | `app/agents/go_workflow.py:389` | 验证超时报告无 hash，绑定失败转 unavailable，验证数 0 而账本已用 1；需保存当前超时证据及计数 |
| R4 | P2 / T08、T15 | `app/agents/go_workflow.py:466` | 独立注入角色调用 3 次/138 tokens，context_stats 却为 0 次/0 tokens；需统一或合并任务账本后再清理 |
| R5 | P2 / T15 | `app/agents/role_runtime.py:56`、`go_workflow.py:453` | 缺失/部分用量补零；需保留未知状态和已知小计，不能伪装成完整总量 |
| R6 | P2 / T15 | `app/agents/go_workflow.py:385` | cleanup_timeout=0.001 仍传入固定 15 秒清理上限，未预留统一截止内的清理时间；需接入配置及有界收尾规则 |
| R7 | P2 / T07、T10 | `app/agents/role_runtime.py:47` | 带说明的有效 JSON 被截去右括号，抛 JSONDecodeError 并浪费重试；需修正完整对象提取 |

### 本次运行结果（独立于历史记录）

解释器 `.venv/bin/python`；沿用 S0.1 tiktoken 真词表缓存；禁用 dotenv/凭据与追踪，DNS/TCP 审计拦截，真实 Docker 通过 Unix socket。完整 argv、UTC 时间、退出码、输出 SHA256 见 [commands.json](evidence/review-s2s4-20261017/commands.json)。

| 验证命令 / 类别 | 实际结果 | 证据 |
| --- | --- | --- |
| `.venv/bin/python docs/evidence/review-s2s4-20261017/run_review.py` 内的 `probes.py` | 退出 1：首批 7 项，6 FAIL、1 ERROR；反例断言失败，未改断言换通过 | `probes.txt` |
| 同脚本内 `python -m pytest tests -q -ra --junitxml=.../pytest.xml` | 退出 0：212 passed、24 skipped、132 subtests passed、3 条原有 jieba 警告 | `pytest.txt`、`pytest.xml` |
| `run_review.py --docker` 内 `AIROBOT_TEST_DOCKER=1 python -m pytest tests/test_multi_agent_workflow.py -q -ra --junitxml=.../docker.xml` | 退出 0：16 passed、0 skipped；其中 2 项真实 Docker 闭环，14 项验证替身 | `docker-closed-loops.txt`、`docker.xml` |
| `probes.py ReviewProbes.test_configured_cleanup_budget_reaches_docker_adapter`（run_review.run 守卫执行） | 退出 1：1 FAIL；生产适配器+子进程替身实际 timeout 参数 [90,90,15]，未应用 0.001 配置 | `cleanup-probe.txt` |
| `docker version` / `docker image inspect` / `docker ps -a --filter name=airobot-go-` | 均退出 0；引擎 29.7.2，固定镜像 sha256:381dd0955d9414dc0debedafb6201a28d4da15b32ce0883310a5e4430fa2d4af；零残留 | `docker-*.txt` |
| `git diff --check`、源码前后指纹 | 通过；业务源码/原有测试未变 | `diff-check.txt`、`source-*.json` |
| 真实模型 / Embedding / 收费评测 | **未运行**，没有累计费用上限，模型网络请求 0 | 网络守卫与脚本 |
| 原有 22 项真实 Docker 专项、远程 CI、Python 3.11、浏览器与 S5 接口 | **本次未运行**；离线 24 个 Docker 开关项中只单独补跑新增 2 项真实闭环 | 不将历史数字算作本次结果 |
| 环境阻塞 | 本次所需检查无环境阻塞 | Docker 沙箱外执行已获工具授权 |

历史证据说明：S3/S4 原始 unittest 输出为 Ran 67、skipped=2，应理解为 65 实际通过、2 跳过；24 个离线 Docker skip 含新增 2 项，并非全部原有。S2/S3/S4 原记录缺少完整代码及差异指纹，不能以 HEAD 相同推断与当前源码相同。本次重新绑定当前源码并重跑；历史原文及输出保留，未覆盖。上述问题在本次审查中仅复现和定位，均尚未修复。

## S2–S4 / R1–R7 修复与本次复验

日期：2026-10-17，Asia/Shanghai。本轮根据上节审查修复 2 项 P1、5 项 P2。原审查脚本、断言和失败报告全部保留；新证据写入 [fix-s2s4-20261017](evidence/fix-s2s4-20261017/commands.json)，没有覆盖历史通过数字。没有创建提交、修改旧目录或运行付费模型。

状态：**七项审查发现均已修复，原边界复现及新增回归通过**。本结论限定于下表已运行的机制、入口与沙箱检查，不代替 S5 全部接口验收、S6 UI 或 S8 真实模型效果评测。

### 版本与变更范围

- HEAD 仍为 `1ea7e6b7abbde3bd1a5963f03cd142fac553685a`；保留此前全部未提交实现。
- 修复前源码清单 SHA256：`4dd5a0b0dc236d79cf66aade27c96de889e2e78448409ca617a40cb32086b6dd`，与独立审查版本一致。见 `source-before.json`。
- 修复后源码清单 SHA256：`a9e9c74e238f1cad19353c96ddadf341b8618df568e82d3906f5587e9df0d4ef`。见 `source-after.json`；同时记录 tracked diff 指纹，覆盖相关未跟踪实现及测试。
- 相对本轮基线仅改动：`app/agents/{graph,go_workflow,role_runtime}.py`、`app/context/usage.py`、`app/go_validation/{contracts,runner,service}.py`，新增 `tests/test_multi_agent_regressions.py`。另追加本日志及本轮证据；已有业务测试与原审查 probes 未改。

### 修复对应与验收证据

| 发现 | 修复 | 本次实际证据 |
| --- | --- | --- |
| R1 / P1 入口绕过 | 主图按请求配置选择 `go_multi`；Service 接收同一工作流的完整结果，支持分别注入主/代码模型并保存审查证据；关闭开关继续走原路径 | 原 probes 入口不再返回 single-v1；新增 Service 成功用例实际返回 multi-v1/passed、3 次角色调用、1 份审查；真实 Docker 服务入口的首次通过与修复通过均运行 |
| R2 / P1 输入额度未执行 | 角色发送前检查真实消息 Token 估计和角色输入/窗口预留，独立于实验 context_mode；超限直接 budget_exceeded，不占共享重试 | 输入上限 1 时模型零发送；另外检查代码角色受限时只发送此前的一次计划 |
| R3 / P2 超时报告丢失 | 编排层合成的超时报告绑定当前产物；保存 Attempt 和已预占验证计数；取消同样保留当前验证状态 | 状态 timeout、validation_calls=1、attempts=1，hash 匹配，沙箱阶段退出码 124；不触发审查或代码修复 |
| R4 / P2 角色账本漏汇总 | 注入及默认角色使用同一任务账本，结果快照形成后才清理；取消快照通过任务本地引用保留，防止图事件未排空时丢失 | 3 次角色调用与 context_stats 一致，已知总量 138 Token；审查中取消保存第 3 次 cancelled 调用和未知用量 |
| R5 / P2 未知补零 | 缺失/部分/非法用量不构造完整零值；顶层 token_usage 可为 null，保留 known_token_usage、完整性标记及未知次数；部分已知字段另存原始已知小计 | 全未知时 token_usage=null、unknown_usage_calls=3、usage_complete=false；部分用量时完整总量仍 null，并保留已知 input=36/output=68/total=92 小计（不同字段覆盖范围不同，不能当完整总量） |
| R6 / P2 清理预算未接入 | DockerGoRunner 使用配置清理时限，包含清理进程创建；验证执行前从同一截止时间预留清理额度；清理失败不能通过 | 原适配器 probe 参数为 [90.001,90,0.001]；20 秒剩余、5 秒清理预留时只给执行 15 秒；只剩清理时间时不再启动验证；真实取消/清理回归通过 |
| R7 / P2 JSON 截断 | 用 JSONDecoder.raw_decode 提取完整对象，保留右括号并正确处理字符串内括号和后缀说明 | 原 prose JSON probe 通过；新增围栏、嵌套对象、字符串右括号和角色计划带说明用例通过，未消耗重试 |

说明：原入口 probe 只注入代码输出，不能提供有效计划，所以修复后准确返回 multi-v1/generation_error，而不是伪造成功。新增成功入口用例分别注入合法计划、代码和审查，证明 Service 能完成新流程；另有机器失败而模型 approve 的用例证明实际入口仍拒绝通过。

### 本轮实际运行

解释器为新版 `.venv/bin/python`（Python 3.13），复用已校验真实词表缓存。复现脚本为 `docs/evidence/fix-s2s4-20261017/run_checks.py`，命令使用清空凭据、禁用 dotenv/追踪的环境及 DNS/TCP 网络守卫；实际网络守卫记录为 0。所有模型为固定输出，真实沙箱通过 Docker Unix socket 执行。

| 命令 / 类别 | 本次结果 | 证据 |
| --- | --- | --- |
| `run_checks.py probes-before` | 退出 1：8 项中 7 FAIL、1 ERROR，与审查一致 | `probes-before.txt` |
| `run_checks.py probes-after`（最终源码） | 退出 0：原 8 项全部通过；原断言未改 | `probes-after.txt` |
| `run_checks.py targeted` | 退出 0：58 passed、3 skipped、28 subtests passed | `targeted.txt`；为最终两处收尾改动前的中间检查，以后续全量结果为最终证据 |
| `run_checks.py all` | 退出 0：224 passed、25 skipped、138 subtests passed；3 条原有 jieba 警告 | `pytest-final.txt`、`pytest.xml`；25 个真实 Docker 开关项另行实际执行 |
| `run_checks.py docker` | 退出 0：65 passed、0 skipped、8 subtests passed | `docker-tests.txt`、`docker.xml`；包含原沙箱、组件闭环及新增实际 Service 两条 Docker 闭环，不能将 65 全部描述为容器用例 |
| `run_checks.py fixtures` | 退出 0：9 个固定输出场景全部最终通过；既定编译/行为错误首次拒绝后修复 | `go-fixtures.txt`、`go-fixtures.json`；实际 Docker，未请求模型 |
| `docker ps -a --filter name=airobot-go-` | Docker 测试后为空；固定评测结束后再检查 | `docker-containers.txt`、`docker-containers-final.txt` |
| `git diff --check` | 退出 0 | `diff-check.txt` |

各次运行的 argv、UTC 起始时间、退出码、耗时、输出 SHA256 见 commands.json。不同检查有重复覆盖，不能将通过数量相加称为独立用例总数；子测试与普通 pytest 项亦分开记录。

证据保留说明：中间一次 `probes-after` 输出被最终同名复验覆盖，其退出码和摘要仍保留，commands.json 将该条标为 output_retained=false；本轮结论仅引用最终保留的 probes 输出。复现脚本已改为重复运行生成编号文件，防止后续覆盖。其余表列输出均已校验文件 SHA256。

### 剩余工作与入口

此次补齐 T12 的实际入口并带入必要 Service 结果/快照处理，S5 的独立角色注入、报告存储及取消已有基础回归；**未据此勾选 T16–T19 全部完成**。下一步按 S5 对真实 HTTP JSON/SSE、并发会话、旧报告嵌套字段及所有中断阶段做完整验收，再推进 Dashboard。

Python 3.11、远程 CI、浏览器及真实模型效果本轮未验证。没有累计费用上限，不运行 live、RAGAS 或收费对照；固定输出与真实 Docker 只证明当前流程和执行检查，不证明多 Agent 质量提升。

## S5 / T16–T19：统一接口、持久化及中断验收

日期：2026-10-17，Asia/Shanghai。**状态：本步完成，未提交**。开始前读取实施计划、S5 提示词、适用说明、Git 状态及完整 S2–S4 修复记录；当前源码与上一步修复后指纹一致，未把此前审查失败的旧版本当作当前代码。未发现新增 AGENTS.md；保留先前全部本地实现、测试及执行记录。

目标：JSON 与 SSE 共用业务流，保存原需求计划、各轮源码/hash、机器验证、审查、角色用量与停止原因；中断后报告可查询、调用计数准确、会话和执行容量按正确次序释放。依赖：已修复的 S2–S4、S1 服务端判定与兼容字段、现有鉴权/会话占用、SQLite、独立 .venv 和固定 Docker 镜像。验收条件：真实 HTTP 两入口业务字段一致；9 个旧报告实际可读；生成/审查/沙箱及修复生成分别取消/超时；账户隔离、无证据通过拒绝；真实 Docker 中断后确认删除，不能将 HTTP 200 或断流当通过。

### 代码版本及本步改动

- 实际根目录 `/Users/xumanchun/Documents/agent项目/AI-Robot-latest`；`main`；HEAD `1ea7e6b7abbde3bd1a5963f03cd142fac553685a`，暂存区为空，没有新提交。
- 开始前源码清单 SHA256：`a9e9c74e238f1cad19353c96ddadf341b8618df568e82d3906f5587e9df0d4ef`；结束源码清单 SHA256：`d70a1763e1b34e4b0928c7c2365005eaecf1afa9db43989c6377095fa33f45af`。覆盖未跟踪实现，排除执行日志、evidence、忽略文件及凭据，逐文件摘要见本步 `source-before.json` / `source-after.json`。
- 最终相对 HEAD 的 tracked diff SHA256：`907d8a2c27b1e038db0eff4e85ec699ba0047e14256b0a4e674d7c47c57b5d90`。最终全量、Docker、原审查反例和静态复查绑定相同源码指纹。
- 相对本步开始前仅改动：`app/agents/go_workflow.py`、`app/go_validation/{service,store}.py`、`app/services/{concurrency,security}.py`、`docs/go-validation.md`；新增 `tests/test_multi_agent_http.py`。另追加本段和 `docs/evidence/s5-20261017/`；已有测试文件、既有执行日志前缀和旧目录保留。

| 编号 | 状态 | 实现与验收 |
| --- | --- | --- |
| T16 | 完成 | 延续上一步独立 supervisor_model/code_model/retrieve/runner 注入入口；JSON 的 run 仅消费 stream 的 go_done，SSE 消费同一个 stream 和 LangGraph；无第二套业务循环 |
| T17 | 完成 | 保留 go_start/go_stage/go_call/go_usage/go_attempt/go_done，增加完整 go_progress 快照、角色/轮次/终态字段；仅发送完整已知 go_usage，未知在报告中保留；最终 JSON/SSE 经相同 GoTaskResult 契约校验 |
| T18 | 完成 | go_start 前即保存 running；每个进度事件保存对应版本快照，不读取图已提前发布的未来版本；SQLite 保存全部计划、各轮完整文件/hash、验证、审查、调用/用量、停止原因。写入再次校验 gate、run_id 与 owner；9 个实际旧 JSON 行原样插入、关库重开，经真实 GET 读取默认字段，并验证其他账户 404 |
| T19 | 完成 | 保留任务本地工作流 Task，取消后等待角色与容器收尾，保存最终引用后继续传播取消。ASGI level cancellation、重复 asyncio cancel 和发送失败均保护关闭/提交；执行槽位保持到清理结束，会话保持到最终写入结束。验证器异常保存当前绑定的 sandbox 日志并 unavailable，不交给模型修环境 |

`main.py` 的既有两路入口、鉴权和 session claim/finally release，及 `contracts.py` 的 S1 默认字段已具备本步基础，不为制造差异重复改写；本步实际通过 HTTP 验证它们与新持久化路径的协作。`store.save()` 拒绝无当前证据的 multi-v1/passed，未放宽 hash、必要需求或阻断问题检查。

### 本次中间失败及自行修复

所有中间输出和 JUnit 保留，没有覆盖已有证据：

1. 首批 25 项新检查实际 **13 failed、12 passed**（`01-targeted.txt`）：复现缺少兼容 SSE 事件、首事件关闭无报告、HTTP 退出早于嵌套调用收尾等问题。首次实现后仍有 **10 failed、15 passed**（`02-targeted.txt`）；随后用任务句柄等待最后调用/清理、按事件自身快照保存、显式关闭 SSE iterator 后解决。
2. JSON/SSE 独立运行会生成不同 artifact_id，审查提示词的本地 input_estimate 因 UUID 分词而不同；该估计不是相同业务结果必须相等的真实用量。比较仅归一化 ID、耗时及这一本地估计；保留全部源码/hash、状态、报告、真实 Token、调用次数和停止原因，并新增逐调用断言，将每个估计与模型实际收到的完整消息精确比对。没有删除有效业务断言。
3. 25 项通过后，追加排队、重复取消、发送失败、存储越权/伪成功、验证器异常与进度写入异常检查，并相应补齐异常收尾和报告保留。两次中间全量/Docker结果仅对应各自源码，未计作最终版本证据。
4. 收尾容量探针实际 **1 failed**（`16-cleanup-capacity.txt`）：沙箱等待清理时执行槽位已从 1 恢复到 2。增加 `_execution_slot`，在同一容量占用范围内等待活动任务收尾；已进入 cancelling 的工作流不再重复 cancel 以免打断清理。原断言保留，最终全量及 Docker 复验通过。

### 最终版本实际运行

解释器 `.venv/bin/python`：Python 3.13.13、pytest 9.1.1、Pydantic 2.13.5；pip check 通过。禁用 dotenv/模型凭据/追踪，使用 S0.1 真词表及 DNS/TCP 网络守卫；审计无网络事件。Docker 使用本地 Unix socket、固定镜像和网络隔离，不 pull/build。引擎 29.7.2 linux/arm64；镜像 `sha256:381dd0955d9414dc0debedafb6201a28d4da15b32ce0883310a5e4430fa2d4af`。

完整实际 argv、时间、退出码、输出 SHA256、源码/差异指纹见 [commands.json](evidence/s5-20261017/commands.json)。复现入口 `.venv/bin/python docs/evidence/s5-20261017/run_checks.py <all|docker|review-regressions|targeted>`，脚本对每轮输出使用唯一文件名，锁定证据写入，保留旧输出。

| 检查 / 类别 | 实际结果 | 证据 |
| --- | --- | --- |
| 最终 `run_checks.py all` → `python -m pytest tests -q -ra --junitxml=.../all-3.xml` | **退出 0：257 passed、29 skipped、138 subtests passed**；3 条已有 jieba SyntaxWarning | `17-all.txt`、`all-3.xml` |
| 最终 `AIROBOT_TEST_DOCKER=1 run_checks.py docker` → 原 Go runner/acceptance/workflow + 多 Agent workflow/regressions/http | **退出 0：102 passed、0 skipped、8 subtests passed**；29 个开关项全部实际运行。其余项为替身/机制检查，不能将 102 全部称为容器用例 | `19-docker.txt`、`docker-3.xml` |
| 本步新增 S5 验收 | **37 项**：33 项离线机制/实际 HTTP 检查 + 4 项真实 Docker HTTP 中断检查，均在最终上述集合中通过；不与全量数量重复相加 | `tests/test_multi_agent_http.py`；JUnit |
| 生成/审查/沙箱/修复生成 × JSON/SSE × 取消/超时 | 16 条替身中断路径全部通过：已有 TaskSpec/产物/上一轮审查保留，计数等于实际模型输入数，未知用量保持未知，取消报告通过 GET 可读且另账户 404；同一会话可再次成功执行 | 最终离线 JUnit |
| 真实 Docker HTTP JSON/SSE × 取消/超时 | 4 条全部通过：先确认容器 Running，再中断；当前产物/hash 和验证次数 1 保留、container_removed=true，结束后再次查询零残留，无后续审查/修复 | 最终 Docker JUnit；`20-containers.txt` |
| JSON/SSE 正常与失败业务一致性 | 首次通过、修复通过、最终失败、unavailable、budget_exceeded、generation_error 六类完全核验；HTTP 200 下明确断言失败状态，发送失败无 go_done 且保存 cancelled | 最终离线 JUnit |
| 旧报告兼容 | **9 个已有实际样本**原始旧行经 SQLite 重开及 HTTP GET 通过，嵌套 hash/任务/审查默认字段正确；没有通过构造新对象再删字段冒充旧样本 | `docs/go-validation-fixture-report.json`；最终离线 JUnit |
| 原审查反例 `run_checks.py review-regressions` | **退出 0：8 项通过**，原 probes 和断言未改 | `18-review-regressions.txt` |
| 当前源码静态复查 | 本次实现代理自查未发现 S5 剩余阻断项；绑定最终指纹，不声称第三方独立审查 | [code-review.md](evidence/s5-20261017/code-review.md) |
| `git diff --check`、输出 SHA256、历史日志前缀/源码范围检查 | 通过；最终核验见 final-checks.json | `13-diff-check.txt`、`final-checks.json` |
| 真实模型 / Embedding / RAGAS / 收费评测 | **未运行**，无累计费用上限、无模型网络调用；固定输出和真实 Docker 不作为模型能力或效果提升证据 | 网络守卫与实际命令 |
| Python 3.11、远程 CI、浏览器与 S6 Dashboard | **本次未运行**；没有据此宣称 UI 或真实模型整体产品验收完成 | 后续步骤待验证 |
| 环境阻塞 | 必要检查无环境缺失阻塞；Docker 用已授权沙箱外执行；pip 缓存权限提示只禁用缓存，pip check 仍通过 | 环境及 Docker 输出 |

剩余边界：S5 范围无已知未修复阻断；仍沿用单进程会话/并发限制，进程崩溃后已保存记录可能停留 running，不支持重启续跑。S6 界面与后续真实模型对照评测未实施。默认多 Agent 开关保持关闭；本步没有启用生产流量、提交或发布。

## S6 / T20–T21：实际事件驱动控制台与浏览器验收

日期：2026-10-17，Asia/Shanghai。**状态：本步完成，未提交**。开始前读取计划、S6 提示词、适用仓库说明、当前 Git 状态及 S5 执行记录；实际起点与 S5 最终源码指纹一致。保留已有本地变更、旧测试断言和历史证据，没有 reset/stash/checkout 或旧目录写入。

目标与验收：依据实际事件展示需求分解、委派、生成、验证、审查、修复和终态；只在服务器最终 passed 时显示成功。run_id 与请求上下文共同隔离，旧流、旧查询及其 finally 不能覆盖新任务。代码、日志及模型文本安全按文本渲染；通过实际浏览器检查成功、修复、失败、断流、取消、超时、未知与旧报告，并逐项声明替换响应和真实后端边界。依赖为 S5 SSE/报告、现有固定 Docker 镜像、Chrome 与可用 Playwright；不做真实模型质量/费用评测。

### 版本、范围和实现

- 根目录 `/Users/xumanchun/Documents/agent项目/AI-Robot-latest`，`main`，HEAD `1ea7e6b7abbde3bd1a5963f03cd142fac553685a`，暂存区为空，无新提交。
- 起点源码清单 SHA256：`d70a1763e1b34e4b0928c7c2365005eaecf1afa9db43989c6377095fa33f45af`；最终完整源码清单 SHA256：`4b1162f00e22d138b525d0abfb546c6f4e639f4ae7e308505cb4fcf39365a429`。
- 最终相对 HEAD 的 tracked diff SHA256：`2be76607869053633d5a7ec7b8383b42d64137bf6724405001ee868836b93f1a`。清单覆盖未跟踪实现；排除 evidence/本日志/忽略文件及凭据以避免自引用。最终验证及静态复查均对应此指纹。
- 本步相对开始前修改：`app/static/dashboard.html`、`app/agents/go_workflow.py`、`app/go_validation/{contracts,service}.py`、`tests/test_multi_agent_http.py`、`scripts/test_go_dashboard.cjs`、`docs/go-validation.md`；新增 `scripts/{test_multi_agent_dashboard.cjs,multi_agent_dashboard_fixtures.py,multi_agent_dashboard_server.py}`。另追加本段与 `docs/evidence/s6-20261017/`。其余原有源码/测试及历史日志前缀保留。

| 任务 | 状态 | 改动及验收依据 |
| --- | --- | --- |
| T20 | 完成 | 实际阶段时间线、角色与轮次；主 Agent 计划、委派/审查与代码 Agent 生成/修复分别展示。旧单流程明确显示单流程，不虚构主 Agent。中间 passed/finish/approve 不使任务成功；只有匹配 go_done 或 GET 的服务器 passed 变绿 |
| T21 | 完成 | 原需求及必要需求、各轮源码与服务端 hash、机器日志、当前轮审查/需求证据、阻断与建议分区、问题 ID/修复要求、完整文件差异、预算/用量/停止原因/最终说明；旧报告缺失字段与额度明确显示未知 |
| 展示所需服务端补充 | 完成 | 所有 Go SSE 事件加当前 run_id；GoTaskResult 增加默认空 budget，内容为共享账本 limits/used 和时间快照，未改变判定或预占。修复阶段由服务端发下一轮 round；未给旧产物或报告换版本标签 |
| 请求隔离与文本安全 | 完成 | 请求上下文 + run_id 双重检查；旧 consume/catch/finally 和旧 GET 响应均不可修改新任务。新多 Agent 事件缺 ID 拒绝，旧无 ID 事件仅在其已绑定连接内兼容。Go 文本全部 textContent，差异/源码/日志完整保留，无模型 HTML 执行 |

界面区分 disconnected（断流未知终态）、cancel_requested（仅请求取消）、cancelled（服务器确认）、timeout 和 unknown；HTTP 200、阶段结束、流关闭均不是成功条件。历史 GET 不虚构新执行或实时阶段。剩余时间只显示服务器快照，预算上限缺失时不猜 3/8 次或重新计时；未知 Token/费用不补零。

### 本次浏览器环境与证据来源

Python 使用项目 `.venv`；Node v22.23.1、Playwright 1.62.1，实际 Chrome **155.0.8059.80**（headless）。普通 Node require 起初找不到 Playwright，随后通过已安装的 Codex bundled NODE_PATH 复用，未安装/下载新依赖。Chrome 与本机监听/Unix socket 在已授权沙箱外运行；无必需环境阻塞。

测试后端仅监听 `127.0.0.1:8766`，使用隔离 SQLite、固定模型、可选择的固定 Docker 验证器；uvicorn lifespan=off，未启动生产知识导入、Embedding 或 AMQP。测试结束后主动 SIGTERM，实际退出 -15，记录在 server-*.json；不是任务失败或未关闭的生产服务。浏览器和测试后端均已结束，容器检查为空。

| 来源类别 | 实际执行与限制 |
| --- | --- |
| 浏览器替换响应（18 项） | 通过/修复/失败/timeout/unavailable/未知状态/断流、错误 run_id、非终态 go_done、缺 ID、非法 JSON、建议不强制修复、旧单流程、旧流与旧查询竞态、旧报告、文本注入和移动端任务区换行；响应/ReadableStream 被明确替换。UI 数据由真实 Service 契约形状捕获，**模型与验证均为替身**，不算真实 Docker 或模型效果 |
| 真实后端 + 真实 Docker（3 项） | Chrome 对 FastAPI/LangGraph/SQLite 的请求与响应未替换，分别完成 passed、修复后 passed、机器失败且审查 approve 仍 failed；共 **6 次实际 Docker 验证**，源码/hash、机器日志、审查和预算保存在 browser-run-02/backend-results.json。模型全部固定替身 |
| 真实后端取消（1 项） | 浏览器真实 Abort 导致后端保存 cancelled，先显示 cancel_requested，再以实际 GET 确认 cancelled。取消发生在阻塞的模型生成替身阶段，未启动 Docker |
| 真实后端旧报告（1 项） | 原样历史 JSON 行经真实 GET 与浏览器显示。数据来自已有实际历史报告，未重新运行该报告的 Docker 验证 |
| 真实模型/Embedding/收费评测 | **未运行**；用户未给累计费用上限。禁止将固定模型字段中的用量或通过率称作真实模型能力、费用或改进结论 |

### 最终实际检查

复现入口 `.venv/bin/python docs/evidence/s6-20261017/run_checks.py <fixtures|all|integration-browser|legacy-browser>`。全部 argv、UTC 时间、退出码、输出摘要、源码/差异标识和浏览器环境见 [commands.json](evidence/s6-20261017/commands.json)。重复运行的输出、截图和报告另存；初版根目录证据及 browser-run-01 均保留，最终结论引用 browser-run-02。

| 检查 | 本次实际结果 | 证据 |
| --- | --- | --- |
| 最终 `run_checks.py all` → `python -m pytest tests -q -ra --junitxml=.../all-3.xml` | **退出 0：257 passed、29 skipped、138 subtests passed**；3 条原有 jieba SyntaxWarning。新增预算字段的动态 remaining_seconds 单独断言边界，其余业务预算比较保留；追加所有 SSE 同 run_id 和修复 round=1 的服务端断言 | `10-all.txt`、`all-3.xml` |
| 最终 `run_checks.py integration-browser` → `node scripts/test_multi_agent_dashboard.cjs` | **退出 0：23 项通过、0 页面脚本错误**，其中 18 项响应替换、5 项真实后端；没有把条件未启用的后端项计成通过 | `11-integration-browser.txt`、`browser-run-02/browser-results.json` |
| 旧浏览器回归 `run_checks.py legacy-browser` → `node scripts/test_go_dashboard.cjs` | **退出 0**：原失败/修复、日志、查询、文本隔离与提前断流断言全部保留通过。只增加截图路径配置以避免覆盖旧产物 | `13-legacy-browser.txt`、独立 legacy-*.png |
| 实际 Docker / 清理 | 固定引擎 29.7.2 linux/arm64；镜像 sha256:381dd0955d9414dc0debedafb6201a28d4da15b32ce0883310a5e4430fa2d4af；最后 docker ps 零残留 | `12-containers.txt`、`16-docker-version.txt`、`17-docker-image.txt` |
| 最终截图视觉检查 | 已实际查看真实修复现场（含展开的 diff）、红色断流界面和 390px 移动端文本注入页面。未见任务区横向溢出或可执行恶意 DOM，图片未编辑 | `browser-run-02/backend-repair-live.png`、`mock-drop.png`、`mock-mobile-viewport.png` |
| 当前源码自查 / git diff --check / 输出摘要与旧记录前缀 | 通过；不声称第三方独立审查 | [code-review.md](evidence/s6-20261017/code-review.md)、`15-diff-check.txt`、`final-checks.json` |
| 原 29 个 Docker 开关专项 | **本步未重新运行**；离线检查中保持 skipped，不能拿 S5 的通过数充当 S6。S6 实际 Docker 证据限于上述真实浏览器后端 6 次验证 | 明确未混算 |
| Python 3.11、远程 CI、S7 定向失效检查与 S8 真实模型效果 | **未运行**，不属于 S6 本次完成声明 | 后续步骤待验证 |

本步没有行为测试失败。静态和截图复查中发现的旧流程标签、缺失 ID/非终态处理和修复轮次语义已在本步自行补齐，并在最终版本重跑；先前 18/22 项浏览器与各轮离线通过只代表其记录的中间版本。一次补丁上下文匹配失败没有落盘，调整后正常实施；没有删除有效断言、忽略产品异常或跳过必需验收换通过。

S6 范围无已知剩余阻断项；默认多 Agent 开关仍关闭，没有修改真实模型凭据、启用生产流量、提交或发布。功能展示验收不代替后续机制失效检查或模型效果评测。


## S7 — A01～A18 机制与真实沙箱回归验收（2026-10-17，本次执行）

**任务：T22–T25；状态：本步完成。** 目标是把每项验收落到实际测试节点，验证错误批准、旧版本报告、可信测试弱化、预算和取消的反例，并用隔离定向失效证明测试能检出防线缺失。依赖已落地的 S1–S6 契约、闭环、预算、服务和界面；验收要求是完整映射、有效反例、有恢复证明、真实 Docker 和受影响原业务实际通过，最后实现修改后重跑且绑定相同源码。收费真实模型评测属 S8，未获累计费用上限，本步不执行。

开始前重新读取计划、分阶段提示词、S6 执行记录、现有测试与相关应用实现，检查 Git 和环境。实际根目录为 `/Users/xumanchun/Documents/agent项目/AI-Robot-latest`，分支 `main`，HEAD `1ea7e6b7abbde3bd1a5963f03cd142fac553685a`。适用说明是用户提供的 Postman CLI 说明；祖先、根及 app/tests/docs 下无额外 AGENTS.md。保留既有未提交改动，未 reset/stash/checkout/提交，也未写入旧项目。开始时源码清单 SHA256 `4b1162f00e22d138b525d0abfb546c6f4e639f4ae7e308505cb4fcf39365a429`；既有 tracked diff SHA256 `2be76607869053633d5a7ec7b8383b42d64137bf6724405001ee868836b93f1a`。

**改动范围与覆盖补齐**

| 文件 | 本次改动 |
| --- | --- |
| `tests/test_multi_agent_acceptance.py` | 新增 8 项：低总额独立拦截共享重试；捕获实际 8 次固定客户端调用（含 provider 失败）且禁止第 9 次预占；上一轮 approve 两次回到新版本仍不能通过；cannot_assess 有界终止；机器通过但必要需求 fail 仍修复/复审；恶意资料/日志及模型权限声明不改服务器；真实 Docker 编译失败→修复→新 hash 验证与审查 |
| `tests/test_multi_agent_early_interruptions.py` | 新增 8 项：计划、检索各阶段 × JSON/SSE × 取消/超时；验证首产物之前报告可查、1 次实际模型调用、0 验证、不多重试、检索计数、计划有无、角色取消完成、用量回收、容量/会话释放、他账户 404 和同会话再次运行 |
| `docs/multi-agent-acceptance-matrix.md` | A01–A18 逐项对应完整 pytest 选择器、通过状态及替身/真实执行边界；机器索引解析最终 JUnit，节点缺失/跳过/失败/错误不能算通过 |
| `docs/evidence/s7-20261017/` | 可重跑命令脚本、五处隔离失效及恢复、各次输出/JUnit、固定镜像身份、真实编译两轮完整报告、最终源码归档与差异、版本自查和证据校验 |
| 本执行记录 | 追加本段，原前缀逐字保留 |

本步未修改已有应用文件或已有测试断言。共新增 16 项测试；必要需求/注入测试证明服务器机制，不宣称真实模型具备相同判断能力。A03 的模型和验证器均为替身，不能把其修复结果视为真实模型的需求识别质量。

**定向失效：五项均被有效断言检出且恢复**

先将相关清单中的源码复制到 `/private/tmp/airobot-s7-mutations-*`（不含 .env、.venv、忽略文件或旧证据），确认原控制组通过，再逐个替换一处防线；只对副本操作。每次写入前 AST 解析，每次测试后 finally 逐字恢复，最后删除副本。没有改写原工作区，无“先破坏原代码再忘记恢复”的窗口。

| 隔离失效 | 对应反例及实际失败 | 恢复后 |
| --- | --- | --- |
| 去掉最终成功所需机器通过条件 | 错误 approve 将 failed 验证升级成 passed；`AssertionError`，退出 1 | 原测试退出 0 |
| 审查版本检查不比较 artifact_hash | 旧 hash 得到 completed，预期 review_error；`AssertionError`，退出 1 | 原测试含 8 子测试通过，退出 0 |
| 可信验收测试只检查存在，不检查原文 | 篡改可信测试后自行重算 hash 未被拒绝；`ValidationError not raised` 的断言失败，退出 1 | 原测试退出 0 |
| 去掉共享总模型调用额度检查 | 总额 2 用尽而重试名额仍在，额外请求预占未被拒绝；`BudgetExceededError not raised`，退出 1 | 固定客户端只收到 2 次输入，退出 0 |
| RoleRunner 吞掉 CancelledError | 本应传播的取消被转成普通输出；`CancelledError not raised`，退出 1 | 生成/审查取消均传播、无后续请求，退出 0 |

证据：`02-mutations-control.txt`、`03`～`12` 对应失效/恢复输出，各自 XML、五份 `.patch`、`mutations.json`、`mutation-preservation.json`。故意失败仅是 **5 项预期失效检出**，不并入最终正常版本失败数。均为断言失败，没有语法/导入错误或超时冒充检出。恢复目标文件 hash 与最终正常源码逐个相同；最终全套测试再次覆盖这些防线。

**本次实际运行结果（不复用 S5/S6 数字）**

所有 Python 行为检查使用仓库 `.venv/bin/python`，禁用 dotenv、清空模型/Embedding 凭据、禁用追踪并加载离线网络 guard（拒绝 AF_INET/AF_INET6 出站，允许 Docker Unix socket）。没有模型/Embedding 网络请求；guard 无阻断尝试记录。未下载镜像，没有调用收费评测。

| 命令/检查 | 实际结果 | 本次证据 |
| --- | --- | --- |
| `run_checks.py environment` → Python、pip check、docker version/image inspect/ps | 通过：Python 3.13.13；依赖无破损；Engine 29.7.2 linux/arm64；固定镜像 Go 1.26.2，ID `sha256:381dd0955d9414dc0debedafb6201a28d4da15b32ce0883310a5e4430fa2d4af`；开始零沙箱残留 | `13`～`17` 输出 |
| 首轮 `run_checks.py counterexamples` | **5 passed、1 skipped**，当时未启用 Docker 开关；这是中间版本，不能充作最终统计 | `01-counterexamples.txt`、`counterexamples.xml` |
| `run_mutations.py` | 原控制 5 passed/8 子测试；5 项预期断言失败；逐处恢复全部通过；副本已删除、原目录未变 | `mutations.json`、`mutation-preservation.json` |
| 首轮 `run_checks.py all-docker` | **294 passed、140 subtests passed，0 failed/0 skipped**；已执行真实 Docker。之后发现计划/检索 HTTP 生命周期覆盖缺口，补充 8 项并重新全跑，未拿旧通过数当最终版本 | `18-all-docker.txt`、`all-docker.xml`、`real-compile-result.json` |
| `run_checks.py early-interruptions` | **8 passed，0 failed/0 skipped** | `19-early-interruptions.txt`、`early-interruptions.xml` |
| **最终** `run_checks.py all-docker-final` → `AIROBOT_TEST_DOCKER=1 .venv/bin/python -m pytest tests -q -ra --junitxml=…/all-docker-final.xml` | **302 passed、140 subtests passed，0 failed/0 error/0 skipped**；83.34 秒 pytest 运行时间；JUnit 442 记录为测试+子测试，不能再算成 442 个独立用例 | `20-all-docker-final.txt`、`all-docker-final.xml` |
| 真实 Docker 子集 | **30 个显式 Docker 测试节点实际通过**（包含原 Go、弱模型测试、三个固定场景、panic/exit/死循环、策略/vet/截断/skip 拒绝、非特权/secret/资源/网络检查、新闭环和 HTTP 取消/超时）；模型仍为固定替身 | `real-docker-tests.json`，来自最终 JUnit；不包含 FakeRunner 项 |
| 新增真实编译修复证据 | 首轮 policy=0、compile=1，真实日志含 `undefined: MissingCompileSentinelS7`；即使 approve 仍修复，错误原文送入第二次生成；次轮 policy/compile/vet/test 全 0，两次容器均确认移除，5 次固定模型请求、2 次真实验证 | `all-docker-final-compile-result.json`；首轮 hash `65d130290a70fe26927d7dd8af6bcbdb46df8168d841f5c9cdbc3bc2741e0bf0`、次轮 `c9f2b8ce7d8bdedfae56131e58ddffc49faab4b08ea1946a6589d1bea0275533`，验证/审查各自匹配 |
| `run_checks.py business` → pytest agent/integration/stability/tracing/hardening | **52 passed，0 failed/0 skipped**；原问答工具循环、JSON/SSE、知识/文章查询、消费去重/恢复、缓存、身份及会话等实际应用代码回归；外部服务使用替身 | `21-business.txt`、`business.xml` |
| `run_checks.py agent-fixtures` → `eval/run_agent_eval.py` | **6/6**：知识、文章、组合、工具失败、预算、直接回答；执行真实 LangGraph，模型和外部工具为替身 | `22-agent-fixtures.txt` |
| `map_results.py` | **A01–A18 全部找到并通过**；只读取最终 `all-docker-final.xml`，逐个选择器核对参数/子测试记录 | `24-map-final.txt`、`acceptance-map.json`、`matrix-results.json` |
| `run_checks.py containers-after`、`git diff --check`、`verify_evidence.py` | 通过：最终零沙箱容器；无差异空白错误；最终源码/测试归档、命令摘要、旧文件/记录前缀、恢复 hash 均匹配 | `23`、`25`、`26` 输出及 `final-checks.json` |
| 真实收费模型评测、真实模型抗注入/需求识别质量 | **未运行**：没有用户给出的累计费用上限；不能用固定输出通过率代替模型能力 | 留待获预算后的 S8 |
| Python 3.11、远程 CI、本次浏览器重跑、真实外部 Go API/AMQP/Milvus 联机验证 | **未运行**；S7 没改前端，旧报告界面沿用 S6 已标注来源的历史浏览器证据。此处不计入本次通过 | 待验证项，非本机 Docker 缺失 |

没有非预期行为测试失败，也未删除有效断言、忽略产品异常或扩大容差。第三方 jieba 的三个 SyntaxWarning 原样保留。最初只读配置查找发现仓库无 pytest.ini/pyproject.toml/tests/conftest.py，检索命令因文件不存在退出非零；这是配置清点结果，不是 pytest 失败或环境阻塞。S7 所需本地依赖及 Docker 无环境阻塞。

**最终版本与证据绑定**

最后一次实现/测试修改完成后，最终全套、52 项原业务、6 场景 Agent、映射和容器检查均绑定同一版本：HEAD 如上，分支 `main`，完整相关源码清单 SHA256 **`a921ed45278e3ba7f998c83955be331a0d61afb1845210fc11168bfa1085b7dc`**；tracked diff SHA256 **`2be76607869053633d5a7ec7b8383b42d64137bf6724405001ee868836b93f1a`**；暂存区为空。tracked diff 未变并不代表 S7 无改动，两个新测试和矩阵均为未跟踪文件，已纳入 153 文件清单及归档。

证据根目录 [s7-20261017](evidence/s7-20261017/) 中：`source-before.json`、`source-final-validation.json`、`source-after.json` 保存逐文件 hash 与 Git 状态；`source-final.tar.gz` 保存对应 153 个相关源码/文档文件，排除 .env、.venv、忽略数据和证据目录；`tracked-working-tree.patch`、`staged-working-tree.patch` 保存差异字节；`commands.json` 保存 argv、工作目录、时间、退出码、输出 SHA256 和源码标识。自查 [code-review.md](evidence/s7-20261017/code-review.md) 绑定同一版本，不宣称第三方独立审查。`verify_evidence.py` 强制检查本步开始前已有源码文件逐字保留、旧证据摘要及旧执行记录前缀未变、新增文件集合准确、归档等于最终清单、最终验证命令等于当前源码、所有非预期失败为零。

A01–A18 的完整测试路径、范围和边界见 [验收映射](multi-agent-acceptance-matrix.md)；逐节点机器结果见 [matrix-results.json](evidence/s7-20261017/matrix-results.json)。本步无已知剩余阻断问题；模型效果、跨 Python/CI/外部服务环境的结论保留待验证。没有启用多 Agent 生产开关、修改模型凭据或发布。


## S8 — 冻结机制对照、独立评分与真实评测准备（2026-10-17，本次执行）

**任务：T26–T27；本次授权范围完成，效果结论不通过/证据不足。** 目标是先固定样本、开发/留出条件、独立评分、模型和预算，再跑原样与同预算对照，保存成功/失败/中断/未知、真实调用及耗时。依赖 S7 机制和真实 Docker 已具备。范围为新增评测代码、机制样本、离线试验、付费预检及执行证据，不修改已有产品实现。验收分开：采集/预算/回归检查必须通过；质量门槛可以失败，不能把程序退出 0 当成效果通过。用户没有给累计费用上限，因此仅执行固定模型和真实 Docker，不调用收费模型。

开始前读取适用说明、S7 记录、Git、计划及旧 eval/go_cases.json、go_fixtures.py、run_go_eval.py、预算/服务/验证器配置。根目录 `/Users/xumanchun/Documents/agent项目/AI-Robot-latest`，HEAD `1ea7e6b7abbde3bd1a5963f03cd142fac553685a`，分支 `main`，暂存区为空，既有大量本地改动保留。开始源码清单 SHA256 `a921ed45278e3ba7f998c83955be331a0d61afb1845210fc11168bfa1085b7dc`；tracked diff SHA256 `2be76607869053633d5a7ec7b8383b42d64137bf6724405001ee868836b93f1a`。适用 AGENTS 只有用户给出的 Postman CLI 说明，祖先/根/eval/tests 下无额外文件。旧目录和既有评测没有覆盖或执行 live。

**变更文件**

| 文件 | 本步内容 |
| --- | --- |
| `eval/multi_agent_cases.jsonl`、`multi_agent_protocol.json` | 30 个固定故障条件；每场景 6 dev/4 holdout，合计 18/12；固定四组预算、评分口径、未知规则、时间目标；真实费用目标为 null，不能据此执行收费请求 |
| `eval/multi_agent_protocol.py` | 冻结完整 app/eval/sandbox 源码、数据和镜像；校验不可变性；请求前持久化累计费用预占、跨进程锁、失败/未知不退款；严格费用和模型预检；分母、角色用量、P50/P95、Wilson 统计 |
| `eval/multi_agent_scoring.py` | 剥离模型测试，单独注入可信行为/需求探针；Go AST 检查所需函数注释；绑定原产物 hash 与 scorer_input_hash；不读取 approve；未知证据不能判通过 |
| `eval/multi_agent_fixtures.py` | 四组共用固定模型响应脚本，注入编译/行为/弱测试/遗漏要求/provider 失败/持续失败等条件；不编造 Token 使用量 |
| `eval/run_multi_agent_eval.py` | freeze、fixtures/live、dev/holdout、prepare-live；使用真实 Service/图/SQLite/Docker；每次请求和事件留档、保存部分进度、拒绝覆盖、重跑需 lineage/reason；缺预算在客户端构建前拒绝；同预算输入和输出限制、版本不符停止 |
| `eval/multi_agent_live_model.example.json`、`multi_agent_pricebook.example.json` | 无凭据的待核实模板；版本、窗口、价格、币种未知保持 null，不假造报价 |
| `tests/test_multi_agent_eval.py` | 新增 25 项参数化/行为检查，覆盖冻结改写、非法预算、并发/重启预占、低总额、发送前阻断、失败保留、未知 Token、独立评分、取消/超时、实际 Docker 三场景及遗漏文档反例 |
| `docs/multi-agent-evaluation.md`、`docs/evidence/s8-20261017/` | 可重算结果、全量原始 trial、模型输入输出、事件、SQLite、每轮源码及 hash、真实独立评分、数据效度/审查诊断/启用门槛、最终版本归档与校验 |
| 本执行记录 | 追加本段；原记录与旧证据逐字保留 |

**先冻结，后执行**

协议 `f60fe4f9fe10d781aa646268c468b983a975843da2b1043c744f6f804c64b333` 于本次 `05-freeze.txt` 创建，固定 30 条条件、评分源码、模型参数/预算及固定 Docker 镜像 `sha256:381dd0955d9414dc0debedafb6201a28d4da15b32ce0883310a5e4430fa2d4af`。随后 dev 72 次全部采集，才由代码检查完整开发报告并创建 holdout 标记，执行 holdout 48 次。开发/留出期间 app/eval/sandbox、数据、参数、规则和镜像均未变；没有根据留出调参、换样本、提升预算或重跑质量失败。随机种子固定并轮换组顺序。留出再次运行必须给 prior run/reason；原样输出目录不得覆盖。

| 组 | 模型调用总上限 | 角色、时间和输出 |
| --- | --- | --- |
| single_native | 原单流程最多 3 次，含解析失败与调用失败重试 | 保留最多两轮修复、120 秒单次生成、8192 输出；没有悄悄把旧流程增为 8 次 |
| multi_native | 正常 7 + 共享异常重试 1，共 8 次 | 主角色计划/审查 60 秒/4096 输出，子角色 120 秒/8192 输出；原样比较同时改变资源分配 |
| single_equal3 | 共同总额 3 次 | 60 秒、8192 输出、16000 输入估计上限 |
| multi_equal3 | 共同总额 3 次（正常 3、异常重试 0） | 与 single_equal3 相同限制；计划/生成/审查通常即用尽，不掩盖修复不足 |

共同任务时间 360 秒、最多 3 次业务验证/两轮修复/1 次检索，同一固定空检索、同一模型身份（本次为脚本）及镜像。输入计数未校准，不能称精确 Token 硬上限。相同上限不代表相同实际调用、Token、修复机会或延迟；单流程仍按原规则在 3 次内解析重试，新流程按角色预算分配。这是资源受控的产品策略对照，不能单独识别架构因果收益。

独立评分在业务结束后运行，不将其反馈给 Agent 修复：移除模型测试、注入服务器验收及独立 Go 测试，再计算 scorer_input_hash；原产物 hash 保留并与每轮源码关联。覆盖错误身份、等待/取消、部分和、输入/顺序、协程上限代表性观测及函数 AST 文档需求等。通过必须完整机器验证、必要检查全部明确 pass。宣称 passed 却缺必要事件、无产物或环境不可用为未知，未知不计成功；真正编译/测试失败为失败。不可完成约束只接受服务端 failed/clarification_needed 的明确拒绝。主 Agent approve 没有参与独立标签生成。

**本次实际结果**

以下全部是本次运行，模型/检索为替身，业务验证和评分是真实 Docker。程序退出 0 只表示采集完成，绝不表示样本或质量门槛通过。主试验共 **120 次任务、312 次实际固定客户端 ainvoke、165 次业务沙箱验证 + 144 次独立评分验证 = 309 次真实 Docker 验证**；309 份报告均为 Go 1.26.2、确认容器移除、无 unavailable。另有 8 次取消/超时冒烟，12 次固定客户端调用，单列且不混入主质量统计。收费 provider 请求 **0**。

| 分集/组 | 独立成功 | 未验证 | 实际客户端调用 | 业务误放行/业务 passed | 流程 P50/P95 秒 | 含独立评分 P50/P95 秒 | 模型费用 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| dev / single_native | 15/18，83.3% | 0 | 30 | 3/18 | 2.79/5.37 | 5.40/17.77 | 0，固定响应不计费 |
| dev / multi_native | 18/18，100% | 0 | 81 | 0/18 | 4.76/5.17 | 8.48/17.72 | 同上 |
| dev / single_equal3 | 15/18，83.3% | 0 | 30 | 3/18 | 2.91/4.99 | 5.79/17.74 | 同上 |
| dev / multi_equal3 | 3/18，16.7% | 3（无产物） | 51 | 0/3 | 2.31/2.76 | 4.79/12.84 | 同上 |
| holdout / single_native | 3/12，25% | 0 | 18 | 6/9 | 2.62/7.97 | 5.14/20.25 | 同上 |
| holdout / multi_native | 3/12，25% | 0 | 48 | 6/9 | 2.97/8.24 | 5.71/20.19 | 同上 |
| holdout / single_equal3 | 3/12，25% | 0 | 18 | 6/9 | 2.88/8.39 | 5.48/21.28 | 同上 |
| holdout / multi_equal3 | 3/12，25% | 0 | 36 | 6/9 | 2.71/3.68 | 5.28/10.73 | 同上 |

独立成功分母包含全部执行样本和未知，业务误放行分母为业务 passed；误拒绝分母为独立正确产物，本轮各组均 0。修复率分母为首产物独立失败（含没有真正进入修复的任务），未知不混算；具体分母及角色调用、需求满足率、停止原因、Wilson 区间在 summary.json。主数据 54 个独立失败、3 个未知全部保留。没有选择性丢弃失败或重新跑成成功。

原样组在开发条件中多 3 个独立成功，同时用 81 次而非 30 次请求，而且固定响应脚本预设了补充需求修复；不能归因为多 Agent 的真实能力。统一 3 次额度时开销/修复余量不足如实出现。**留出条件四组均 25%，没有改善**；均有 6/9 漏放行，不满足预设零误放行门槛。固定响应几乎无推理延迟，实测时间主要是容器与流程开销，不能外推真实模型时延。

本次所有 312 个固定响应都没有真实 provider Token 使用量，total_tokens 始终 null，unknown_usage_calls 分别正确计数；known_token_subtotal=0 仅表示没有已知项，绝非“实际用量为零”。本次费用 0 来自没有计费请求，而非把未知 Token 乘零价格。真实费用/币种/价格未核实，真实评测费用保持未知。

主 Agent 审查诊断另列 `review-audit.json`，标签只取已独立评分的首/末源码版本：dev multi_native 9/27 已知 approve 错误；dev multi_equal3 9/12；holdout multi_native 12/15，另 3 个中间版本 approve 未独立评分保持未知；holdout multi_equal3 9/12。业务门禁已拦住部分“机器失败但 approve”，因此这些审查错误不能与最终业务漏放行数混淆。诊断不改变冻结主评分或通过规则。

**数据效度、产品缺口与启用结论**

`data-audit.json` 证实 30 条是故障条件，只有 **12 条不同公开需求、3 组基础需求跨开发/留出**。因此本轮只支持固定脚本的机制检查，“留出”是条件留出而非独立任务泛化留出；不能宣称 30 个独立需求、真实模型质量或总体统计改善。区间仅描述相关模板上的计数。未来真实质量评测必须另建去重/按任务族分组的数据并重新冻结，不能把本轮重新命名成有效留出。发现这个限制后没有换数据重跑以制造提升。

源码复查发现 `clarification_needed` 目前只出现在 stop_reason 枚举，标准闭环没有可达返回路径；不可完成需求的正式拒绝能力尚有缺口，不能把本批该项失败全部归给模型。S8 不回改已冻结的被测产品来使试验变绿；该能力应在后续产品版本实现并用新冻结实验复验。`enablement-gate.json` 由实际指标/数据效度/真实预检计算 **passed=false**，不依据 approve 或 CLI 退出码。没有改变生产开关。

真实评测框架与预检已准备，**正式真实质量评测尚未就绪**：缺累计费用上限及币种、固定且核实的模型版本/窗口、含缓存/推理等计费上界的单价与核实日期、持久账本，还需新的独立任务数据/划分及拒绝路径处理。候选 qwen-plus 只是未固定的别名。`live-preflight.json` 与 `live-readiness.json` 明确 blocked、calls_sent=0；未知项没有填价格或伪造模型快照。未来 live 配置须在新冻结中固定金额目标；全四组每任务 3 次为 360 次运行，最坏 1530 次请求，金额不足会先停止，未运行项明示。不是本轮的收费执行授权。

**验证命令与分类**

统一使用仓库 Python 3.13.13，禁用 dotenv、清除模型/Embedding 凭据和追踪，加载离线 guard 拒绝 AF_INET/AF_INET6 出站，只允许 Unix Docker socket。本次无阻断出站尝试。Docker Engine 29.7.2 linux/arm64，固定镜像如上，无 pull/build。原有产品/业务源码未改写。

| 实际检查 | 结果 | 本次证据 |
| --- | --- | --- |
| 首轮/第二轮 `run_checks.py unit` | 18 passed/1 skipped，随后 20 passed/1 skipped；未启用真实 Docker 探针，是中间版本记录，不能冒充最终 | `01`、`02` 输出/XML |
| 初轮 `run_checks.py all-docker` | 326 passed、140 子测试，0 failed/0 skipped；后续在冻结前补输入/版本防线并重跑受影响检查 | `03-all-docker.txt/xml` |
| 冻结前最后 `eval-docker-final` | **25 passed、0 skipped**；包括真实 Docker 三场景及文档遗漏反例。解析缺证据的未知分类、统一输入限制/版本检查均在冻结前确定 | `04-eval-docker-final.txt/xml` |
| `freeze`、`dev`、`holdout` | 固定协议，72 + 48 完整主运行；退出 0 是采集完成，57 个非独立成功保留 | `05`～`07` 输出、freeze-v1、dev/holdout 全量目录 |
| `prepare-live` | 操作成功生成阻塞清单；**真实评测未运行**，缺预算等条件，calls_sent=0 | `08-prepare-live.txt`、live-preflight.json |
| `smoke-cancel`、`smoke-timeout` | 四组各一次，总计 **8 次按预期 cancelled/timeout**，已有模型调用和 SQLite 报告保留；不算成功，不纳入主质量统计 | `09`、`10` 输出及目录 |
| 数据/审查诊断、启用门槛、汇总 | 操作均退出 0；数据效度与启用门槛 **false**，原始主结果全量可重算。汇总只新增文档，没有修改评分源码 | `11`～`14` 输出、data-audit、review-audit、enablement-gate、summary |
| **最后实现修改后最终全套** `AIROBOT_TEST_DOCKER=1 .venv/bin/python -m pytest tests -q -ra --junitxml=…/15-all-docker.xml` | **327 passed、140 subtests passed，0 failed/0 error/0 skipped**；111.15s。包含全部原业务回归和 34 个显式真实 Docker 测试节点。JUnit 467 记录为测试+子测试，不是 467 个独立用例 | `15-all-docker.txt/xml` |
| 两个 OS 进程竞争一次合成费用额度，再启动新进程 | 一次预占成功、一次阻止，重启仍阻止；未知费用保留完整预占；**0 provider 请求，TEST 为合成预算单位，不是费用** | `16-cost-process-proof.txt`、cost-process-proof.json、synthetic-cost-ledger.json |
| 实际 `python -O … run --mode live` 不提供费用上限 | 内层 **预期退出 2/blocked**，没有创建输出或客户端请求；外层断言检查退出 0。证明费用门禁不依赖可被优化移除的 assert | `17-paid-guard-proof.txt`、paid-guard-proof.json |
| `git diff --check`、Docker version/ps、独立证据复算 | 通过；最终零沙箱容器；绑定源码/归档、旧文件/证据、逐条独立标签、主调用数、未知值均核对 | `18`～`21` 输出、final-checks.json |
| 真实收费模型、真实价格/Token/费用/模型推理延迟、正式质量推广条件 | **未运行/待条件，不能算通过**；没有用户累计费用上限及其他准备项，未用替身替代真实结果 | live-readiness.json 明确剩余项 |
| Python 3.11、远程 CI、浏览器、本次真实外部 Go API/AMQP/Milvus 联机回归 | **未运行**；本步未修改前端/外部业务代码，现有原业务测试使用外部服务替身且全部通过 | 不混入本次通过声明 |

没有非预期测试失败、删除有效断言或忽略异常换通过。基线检查的 skipped 是显式未启用 Docker，最终为 0 skipped。独立评分 channel 持续错误因不读取输入而触发容器内 go test 8s 超时，作为代码失败保留，不改成环境阻塞、跳过或成功。三个 jieba SyntaxWarning 原样保留。少量只读路径检索/文档补丁上下文未匹配已更正，未改变有效断言或冻结代码。

**最终代码与证据对应**

最后实现/测试修改先经 25 项受影响检查后冻结；主试验执行源码清单 SHA256 `e98c00fe48f80945419f9c34eb6c91705afbe17d51b5e3c107a5bf410366ea66`。只在执行完后新增结果文档，最终完整清单为 **`8ea7688736df7336ea7b96cce07224ea62a562a7073a78bc7cc3e11273c62e98`**；最终全套回归和自查绑定该同一版本，app/eval/sandbox 与冻结值始终相同。HEAD/分支/tracked diff 如上未变，暂存区空；新增评测/文档文件均纳入清单，不能以 HEAD 或 tracked diff 相同误判无变化。

`source-before.json`、`source-frozen.json`、`source-final-validation.json`、`source-after.json` 保存逐文件 hash 与状态；`source-final.tar.gz` 保存对应 163 个相关源码/文档文件（排除 .env、.venv、忽略数据、执行记录及证据目录）；tracked/staged-working-tree.patch 保存原始差异。`commands.json` 记录每次 argv、UTC、耗时、退出码、输出 SHA256 和源码标识，唯一 source_unchanged=false 是只新增结果文档的 summary 操作，明确列出其文件，不冒充代码修改。自查 code-review.md 不声称第三方独立审查。

`verify_evidence.py` 在最终版本重新解析真实报告和固定需求清单复算独立标签（不信 approve 或已保存 bool），检查 120 次完整配对、实际调用/服务器计数/上限、hash/清理、未知值、质量门槛 false、真实预检 blocked、327 项最终回归、归档与现源码相同；本步开始前所有已有源码文件、旧执行记录前缀与 S0–S7 证据 hash 均未改。

详见 [S8 报告](multi-agent-evaluation.md)、[汇总](evidence/s8-20261017/summary.json)、[正式评测剩余条件](evidence/s8-20261017/live-readiness.json)。本次离线/准备工作完成，**效果没有改善证据，正式真实质量评测与推广门槛仍待满足**；未启用生产流量、未修改凭据、未提交或发布。

## S8.1 — 继续真实评测数据准备与归档复现（2026-10-17，本次运行）

**任务 T26–T27，完成不依赖费用授权的准备；真实模型对照未运行。** 本步目标是在保留 S8 v1 的冻结协议与负面结果基础上，新增去重、按调用任务族分集的候选数据，并让数据条件成为实际 live 入口检查。依赖 S8 的独立评分、调用/费用账本、真实 Docker 与原源码归档。范围限于评测工具/候选数据/测试/文档；验收是重复/泄漏/缺探针反例被拒绝、候选 Go 探针可执行、新需求反例被拒绝、旧试验可在原版本复算、最终回归及证据保全通过。不以这些工具检查替代模型效果验收。

开始时复核仓库根 `/Users/xumanchun/Documents/agent项目/AI-Robot-latest`、分支 `main`、HEAD `1ea7e6b7abbde3bd1a5963f03cd142fac553685a`，未提交改动保留。开始源码清单 `8ea7688736df7336ea7b96cce07224ea62a562a7073a78bc7cc3e11273c62e98`，tracked diff `2be76607869053633d5a7ec7b8383b42d64137bf6724405001ee868836b93f1a`，暂存区为空。适用说明、计划 T26/T27、S8 执行记录和现有评测代码已读取；没有新增适用 AGENTS 指令。没有执行旧目录代码或改写既有产品实现。

**变更文件及契约**

| 文件 | 变更 |
| --- | --- |
| `eval/multi_agent_live_cases.jsonl`、`multi_agent_live_protocol.json`（新增） | 30 条不同公开需求、15 个调用模式族；同族两个边界值变体整体分集，9 族/18 条 dev、6 族/12 条 holdout，每场景 6/4。28 条可执行需求加事后独立 Go 探针；2 条政策冲突保留明确拒绝检查。候选协议不使用旧试验标签 |
| `eval/multi_agent_protocol.py` | 新增规范化公开需求去重、任务族不得跨集、分组说明、独立测试名映射检查；freeze/load 校验候选数据；live 前拒绝旧机制条件数据；显式异常在 `python -O` 下仍生效 |
| `eval/multi_agent_scoring.py` | 只在独立评分 bundle 注入候选 `eval_case_test.go`；原始 hash 与独立评分 hash 分开，approve 不参与标签 |
| `eval/run_multi_agent_eval.py` | freeze 新增 `--cases`/`--protocol`；默认机制数据路径保留；整个候选数据和协议进入冻结 digest，运行前仍绑定当前源码 |
| `tests/test_multi_agent_eval_candidates.py`（新增） | 37 项检查：冻结绑定、重复需求、跨集任务族、缺/错探针、缺分组说明、旧数据即使合成配置齐全也拒绝 live、评分注入与缺证据、28 项真实 Docker 参考探针、1 项真实 Docker 新需求反例 |
| `docs/multi-agent-evaluation.md`、本记录、`docs/evidence/s8.1-20261017/` | 追加候选数据边界及操作说明；保存本次完整评分报告/评分源码、版本、命令、归档复算、预检、付费阻断和自查 |

数据仍共享三个固定 API，是人工构造的相关任务；30 条规范化文本不同及任务族不跨集仅排除了可观测泄漏，不能证明语义独立或真实分布代表性。不是 30 个独立自然任务的统计证据。模型只接收公开 requirement，extra_probe 不发送给模型；检查运行路径为 GoTaskRequest(requirement=case["requirement"])，探针仅在事后 score 中注入。

**代码版本和本次验证**

最后实现/测试修改后完整源码清单为 **`e44ee304591ba18bd0ed44a7136ac56082c7a28b8a4bf29441f32d1bba481fd8`**，最终全套测试、源码自查、新冻结和证据校验绑定同一版本。新冻结 hash **`dc6d7fb7446004fd87c1dd3e862b3bad29a05e4a428c89b2b4044983144e514e`**；镜像仍为 `sha256:381dd0955d9414dc0debedafb6201a28d4da15b32ce0883310a5e4430fa2d4af`。HEAD/tracked diff/暂存区如开始时未变；不能以 tracked diff 没变忽略未跟踪评测文件变化，完整差异以逐文件清单为准。

统一命令入口为 `.venv/bin/python docs/evidence/s8.1-20261017/run_checks.py`，详细 argv/UTC/耗时/退出码/输出 hash/源码 hash 在 `commands.json`。Python 3.13.13；禁用 dotenv、移除模型和外部服务凭据、关闭追踪，加载既有离线 guard，仅允许 Unix Docker socket；无出站阻断事件、无收费请求。Docker Engine 29.7.2 linux/arm64，Go 检查镜像 1.26.2，没有拉取或安装依赖。

| 本次实际命令/检查 | 分类与实际结果 | 证据 |
| --- | --- | --- |
| `run_checks.py unit`（中间版本） | **29 passed、32 skipped**：显式未启用真实 Docker；不是最终通过记录 | `01-unit.txt/xml` |
| 最后实现修改后 `AIROBOT_TEST_DOCKER=1 S81_PROBE_EVIDENCE=… .venv/bin/python -m pytest tests -q -ra --junitxml=…/02-all-docker.xml` | **364 passed、140 subtests passed，0 failed/0 error/0 skipped**，pytest 221.75s。包含全部现有原业务回归及新增检查；3 个已有 jieba SyntaxWarning 原样保留 | `02-all-docker.txt/xml` |
| 新增候选参考探针 | **28/28 通过，真实 Docker**；每项保存独立评分输入源码/hash、原产物 hash、完整四阶段报告、需求检查、清理确认 | `probes/live2-*.json` |
| 新需求实际错误实现 | 将人工参考 WorkerPool 在非法 workers 检查前加入“空输入提前成功”；新增 r-case 明确 **fail**、独立正确性 false，反例拒绝检查通过，容器清理完成 | `probes/counterexample.json`；没有改产品源码/删断言 |
| `verify_archive.py` | 从旧归档核对 163 个文件并恢复到临时目录，以旧代码 load_freeze/audit_rows/aggregate 复算 dev 72 + holdout 48；与原 metrics 完全一致，调用 192 +120，留出四组仍各 3/12。不是重新调用模型 | `02-archive-proof.txt`、`archive-proof.json` |
| `freeze --cases …live_cases.jsonl --protocol …live_protocol.json` | 新候选协议冻结成功；没有借旧 holdout 结果给它贴标签 | `04-freeze.txt`、`freeze-v2/freeze.json` |
| `prepare-live` | 命令退出 0 是生成报告成功；**业务准备状态 blocked、calls_sent=0** | `05-prepare-live.txt`、`live-preflight.json` |
| `python -O eval/run_multi_agent_eval.py run --mode live …` 无费用上限 | 实际内层 **退出 2/blocked**，无输出目录、0 provider 请求；外层证据断言检查退出 0，证明不依赖 assert/提示词 | `06-paid-guard.txt`、`paid-guard-proof.json` |
| `git diff --check`、Docker version/ps | 通过；最终零 `airobot-go-` 容器 | `07`～`09`、`containers-after.txt` |
| `verify_final.py` | 通过：绑定最后源码/测试/冻结，29 份 Docker 评分报告、旧日志前缀和 **1476 个已有证据文件**逐字保留，原产品文件未变，无出站记录，归档和清单已保存 | `10-evidence-check.txt`、`final-checks.json`、`source-after.json`、`source-final.tar.gz` |
| 新数据上的固定模型四组质量对照 | **未运行**，候选评分工具检查不能作为模型成绩 | 无成功率/费用/推理延迟结论 |
| 真实收费模型评测、真实 Token/价格/费用/推理延迟 | **阻塞/未运行**；没有明确累计费用上限及币种、固定且核实的模型版本/窗口、冻结单价和持久账本；未知不填零 | live 预检列出各项，0 provider 请求 |
| 浏览器、外部 API/AMQP/Milvus 联机、Python 3.11/远程 CI | **未运行**；本轮没有改产品/前端/外部调用代码，原业务回归中的外部服务为替身 | 不作为真实联机通过 |

证据采集器曾在全套检查与归档复算并行时为两个不同输出分配同一数字前缀 `02`；两个命令输出均完整，原先 `commands-during-parallel.json` 保留归档记录，随后合并回 commands.json 并按实际开始时间排序。采集器已加文件锁，后续顺序记录；没有丢失失败或伪造重跑。该修复只在新证据目录，不影响已测源码。没有非预期行为测试失败、忽略异常或删改有效断言换通过。

**结论与剩余项**

本次实际使用模型替身/人工参考实现，不是收费模型；Docker 验证真实执行。新数据的准备与评分防线验证通过，模型效果仍未验证。旧 v1 的结论保留：四组留出条件独立成功率均 25%，没有改善证据；开发原样多 Agent 同时使用更多调用，收益不能直接归因于架构。未知 Token/真实费用不按零处理，本轮收费费用为零只因未发送任何计费请求。

现有产品 `clarification_needed` 没有可达标准闭环返回路径，候选中的两个冲突要求仍保留，缺口未修饰为模型问题；需要后续独立产品修复和新冻结复验。本次不改被测产品制造提升、不启用生产开关、不提交或发布。旧 S8 v1 当前目录 hash 不再匹配属于预期保护，必须从其已验证归档复现，不能绕过版本检查。

相关入口：[评测报告](multi-agent-evaluation.md)、[本次证据校验](evidence/s8.1-20261017/final-checks.json)、[真实评测阻塞项](evidence/s8.1-20261017/live-preflight.json)。

## S9 — T01～T28 / A01～A18 核对、回退与本地交付（2026-10-17，本次运行）

**S9 本地核对和交付工作完成；T28 整体仍待验证，推广门槛不通过。** 目标是逐项按代码/实际证据区分完成、待验证和阻塞，修正超过实现范围的文档，实际关闭开关检查原流程/旧报告，交付配置和可复现版本。依赖 S0～S8.1 的代码及证据。改动限于文档、CI 配置及新的固定模型回退演练脚本；没有为了完成全部状态而回改被测产品或改变效果评分规则。验收是逐项映射有依据、回退实际运行、最终受影响检查通过、报告/恢复和 Go/聊天边界写清，远程/真实模型缺证据不算通过。

开始前读取适用说明、计划、S7 验收矩阵、既有执行记录、服务/契约/配置/图/测试、README/Go 指南及 CI。实际根 `/Users/xumanchun/Documents/agent项目/AI-Robot-latest`，HEAD `1ea7e6b7abbde3bd1a5963f03cd142fac553685a`，分支 `main`，暂存区空；没有 reset/stash/checkout/提交/推送。适用 AGENTS 只有用户提供的 Postman CLI 可用说明，相关目录无额外 AGENTS。开始源码清单 `e44ee304591ba18bd0ed44a7136ac56082c7a28b8a4bf29441f32d1bba481fd8`，tracked diff `2be76607869053633d5a7ec7b8383b42d64137bf6724405001ee868836b93f1a`；所有原有本地改动保留。

**逐项核对结果**

- T01～T28：**24 完成、2 待验证（T05/T28）、2 阻塞（T26/T27）**。T05 的成功/修复/预算/异常路由已有防线，但 `clarification_needed` 仅有契约枚举，标准闭环缺可达返回路径，属于明确实现缺口，不能只补一次测试就视为完成。T28 本地文档/回退部分完成，远程 CI 及 T26/T27 前置门槛仍未完成。T26/T27 的固定模型、候选数据和工具准备已做，真实模型/金额目标等缺外部授权和配置。
- A01～A18：**18 项完成（本地机制范围）**，每个选择器解析最终 JUnit，所有匹配参数/节点都通过；缺失、跳过、错误不计通过。完整行、实际源码位置、精确选择器、匹配节点和限制见 `delivery-status.json`。A03 不证明任意需求语义识别，A10 不证明真实模型抗注入；T14 的 addressed_issue_ids 表示交给修复的阻断项，是否解决仍需新版本的验证/审查，不以该字段自证。
- 逐行人读说明见 `docs/multi-agent-delivery-audit.md`。S7 定向失效、S6 浏览器及 S8 对照均保留来源和日期，未伪称 S9 重跑。旧固定条件留出四组均 25%，无改善证据；v2 人工候选数据没有模型成绩。`enablement.passed=false`，默认仍关闭。

**变更文件**

| 文件 | 本次内容 |
| --- | --- |
| `docs/multi-agent.md`（新增） | 可运行位置、首次安装/配置、真实窗口约束、重启后回退、Go 专用入口和聊天边界、保存/恢复区别、费用/CI/真实评测和明确剩余问题 |
| `docs/multi-agent-delivery-audit.md`（新增） | T01～T28 与 A01～A18 逐行状态、代码和证据类型/边界；本地/固定模型/真实 Docker/浏览器历史/远程 CI/真实模型分列 |
| `scripts/check_multi_agent_rollback.py`（新增） | fresh process 要求 actual enabled=false；真实 ASGI/SQLite/Docker，固定生成模型和被调用即失败的多 Agent 角色；3 场景 JSON/SSE、编译修复、持续失败、旧原始报告/既有 multi 报告重开、账户 404、聊天六案例；直接核对 GET 前后实际客户端计数 |
| `.github/workflows/ci.yml` | 默认 false、清空模型凭据/关闭 dotenv 和追踪；真实 Docker job 扩大为完整 pytest、关闭开关演练、已有固定输出评测及 JUnit 上传；移除仅凭 Secrets 存在就执行无累计上限 RAGAS 的自动路径，真实评测保持不执行策略 |
| `README.md`、`docs/go-validation.md` | 链接新交付说明，明确能力边界、默认关闭和真实费用前提；移除将旧无累计费用账本 live 脚本作为当前推荐入口的示例 |
| `docs/multi-agent-implementation-plan.md`、`multi-agent-execution-prompts.md`、`multi-agent-acceptance-matrix.md` | 标明历史设计/历史证据和当前核对入口；显式标注澄清路径缺口，不改原任务标准，不将初始“待执行”当作当前进度 |
| `docs/evidence/s9-20261017/`、本执行记录 | 命令/输出/JUnit/逐项解析、独立回退 SQLite/完整源码和报告、环境/未提交 patch、源码清单/归档、自查/保全检查、异常与重跑原因 |

原有 `app/`、`tests/`、`eval/`、`sandbox/` 文件字节均与 S9 开始一致，生产 `.env`、生产 `data/go_tasks.sqlite3` 及运行中的服务未修改。演练在新进程和独立数据库执行；“实际关闭”指该进程从显式环境变量 false 读取的真实配置，不是声称已为现有生产进程在线热切换。文档要求修改实际服务配置后重启，没有热切换 API。

**实际关闭开关演练**

最终执行 `.venv/bin/python scripts/check_multi_agent_rollback.py --output …/rollback-final --multi-report docs/evidence/s8-20261017/dev/channel-05-multi_native-r1-19d2b0cb/result.json`，由离线采集器显式设置 `AIROBOT_GO_MULTI_AGENT_ENABLED=false`，禁用 dotenv。生成客户端全为人工 FixtureModel，多 Agent 主/子角色为被调用即异常的 ForbiddenRole。真实执行当前 FastAPI ASGI、LangGraph、SQLite 和 Docker，不访问供应商。三场景 JSON/SSE 共 6 次首次通过，均 single-v1、1 次调用/1 次验证；编译失败后 2 轮通过；持续错误 3 轮 failed（HTTP 200 也不算成功）。总计 **8 次任务、11 次实际固定生成请求、11 次真实 Docker 验证，多 Agent 角色调用 0**。

将 9 个现有历史原始 JSON 和 1 个既有 multi-v1 报告直接写独立库、关闭并重开，再经实际 HTTP handler GET：原始源码/日志、原状态及 multi 审查均保留，跨账户均 404。直接比较保留的 8 个客户端实际计数，**读取报告新增调用 0**。普通聊天现有图六个固定案例通过（knowledge/article/combined/failure/budget/direct，共17次固定调用），不触发 Go 自动委派。报告重开读取不是 Agent 任务恢复；未实现重启续跑/后台恢复，崩溃留下 running 报告仍可能维持原状态。

`rollback/` 是首次中间版本演练；**最终验收以 `rollback-final/summary.json`、`05-rollback-final.txt` 为准**，包括更强的真实客户端计数断言。最终报告与源码/hash/完整四阶段日志均落盘，容器清理全部确认，最终零遗留容器。

**验证命令、实际结果与分类**

统一入口 `.venv/bin/python docs/evidence/s9-20261017/run_checks.py`（通过 runpy 调用其 run），实际 argv/UTC/耗时/退出码/输出 hash/源码 hash 均在 `commands.json`。清除模型/Embedding/外部服务凭据及追踪，复用已验证 tiktoken 缓存，离线 guard 拒绝 AF_INET/AF_INET6，只放行 Unix Docker socket。未安装/下载依赖，未拉取镜像；本轮无出站阻断事件。

| 实际检查 | 实际结果 | 证据 |
| --- | --- | --- |
| 首次回退脚本 | 通过；后续自查补强 GET 计数，作为中间版本保留 | `01-rollback.txt`、`rollback/` |
| 首次映射脚本 | 退出1：映射误写不存在的 CodeRepairTests，按实际 RepairTests 更正，AST存在断言与精确JUnit要求保留；未伪称测试通过 | `incidents.json` 标明为工具输出转录，不冒充新执行 |
| 首次配置检查 | **退出1**：检查器将合法 UTF-8 BOM 交给 ast.parse，非产品语法错误；按 Python 源码语义用 utf-8-sig 解码并保留全量语法检查 | `02-configuration.txt` |
| 配置修正/最终复查 | 通过：YAML解析/关键结构、默认 false、没有自动收费步骤、源文件 Python3.11 语法、文档链接；不等于 Python3.11运行时或远程 CI | `03-configuration-final.txt`、`08-configuration-confirmed.txt`、configuration-check.json |
| 中间完整 Docker suite | **364 passed、140 subtests passed，0 failed/0 skipped**，187.55s。运行中补强回退脚本，因此 `source_unchanged=false`，不作最终同版本证据 | `04-all-docker-final.txt/xml` |
| **最终回退重跑** | 通过；11次真实Docker、Go客户端11次、主/子角色0、GET新增0；9旧+1multi重开、账户隔离、聊天6例通过 | `05-rollback-final.txt`、rollback-final 全量报告/事件/数据库 |
| **最后实现修改后最终全套** `AIROBOT_TEST_DOCKER=1 .venv/bin/python -m pytest tests -q -ra --junitxml=…/all-docker-confirmed.xml` | **364 passed、140 subtests passed，0 failed/0 error/0 skipped**，221.07s；原业务回归和所有显式 Docker 节点实际运行。3个已有 jieba SyntaxWarning 原样保留 | `06-all-docker-confirmed.txt`、`all-docker-confirmed.xml` |
| `build_audit.py …/all-docker-confirmed.xml` | 精确解析通过：T 24/2/2，A18项机制全部实际通过；状态不由模型 approve 或 HTTP200 推导 | `07-map-tasks-acceptance.txt`、task-map/delivery-status.json |
| `prepare-live --freeze …s8.1…/freeze-v2 --output …` | 退出0仅表示写出预检；**status=blocked、calls_sent=0**，缺金额授权/固定模型/价格/账本等 | `09-prepare-live.txt`、live-preflight.json |
| `git diff --check`、Docker环境/清理、`.venv/bin/python -m pip check` | 通过；Python3.13.13、pytest9.1.1、Pydantic2.13.5；固定Go镜像ID如既有，最终0容器，依赖无冲突 | `10`～`12`、environment.json、docker-version.txt、containers-after.txt |
| 交付证据自检 | 通过：最终源码/全套/回退版本相同，169源码文件归档、原日志前缀与1542个既有证据保全，原产品代码未变，逐项状态和剩余项一致 | `13-verify-delivery.txt`、final-checks.json、verify_delivery.py |
| 远程 GitHub Actions、Python3.11真实运行时 | **未运行**；只修改并本地校验CI配置，未推送/触发当前未提交版本，不能套用HEAD的旧远程结果 | delivery-status.json remote_ci=not_run |
| 真实收费模型/真实Token/价格/费用/推理延迟 | **阻塞/未运行，0 provider请求**；缺明确累计费用上限及模型/价格配置；未知不补零，不把固定模型成功当真实成绩 | live-preflight.json、delivery-status.json |
| 本次浏览器、真实外部Go API/AMQP/Milvus联机 | **未运行**；浏览器沿用S6历史23检查（18响应替换/5真实后端，固定模型，真实Docker分列），当前UI字节未变；业务回归外部服务为替身 | docs/evidence/s6-20261017/ 原证据，未改写 |

没有删除有效断言、扩大容差或忽略异常。两类检查器错误和中间版本/重跑原因完整保留，见 incidents.json；回退中的 failed 是预期业务结果，由有效断言确认，不是被跳过的测试。最终完整套件没有跳过项。真实 Docker 的通过不能替代真实模型质量或远程 CI。

**最终版本、配置与交付位置**

最后实现修改后的完整源码清单 **`b0a72a1788389b3c883e50a7fa42fe56c5e0be4e13a8bbd947834badb8d77709`**；最终全套、最终回退、逐项映射和自查绑定该相同版本，检查期间源码未变。tracked diff **`1c086f2c0ef87478694af8e184602f87122acc5239344bcf6c086cc48df5b89b`**，暂存差异SHA为空内容的 `e3b0c442…`；HEAD/分支未变。新增未跟踪文件已入逐文件清单，不能只凭HEAD/patch复现。

可运行工作区：`/Users/xumanchun/Documents/agent项目/AI-Robot-latest`，解释器 `.venv/bin/python`。启动方式：在该目录设置 `AIROBOT_GO_MULTI_AGENT_ENABLED=false` 后执行 `.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`；真实业务模型/管理员令牌等配置在本地.env，启用多Agent还需核实各角色窗口，见 `docs/multi-agent.md` 和 `.env.example`。未运行无预算的真实业务评测，未更改用户现有.env。新建机器需安装依赖、构建镜像，不能当作已在新机器验证。

`source-before.json`、`source-final-validation.json`、`source-after.json` 保存逐文件版本/状态；`source-final.tar.gz` 含169个相关源码/配置/文档文件（无.env/虚拟环境/忽略数据/证据/执行日志），tracked/staged-working-tree.patch保存未提交已跟踪差异；完整证据和执行记录另在当前目录保存，清单校验归档内容与当前测试版本完全相同。code-review.md 为源码/文档自查，非第三方独立审查。

剩余项明确保留：澄清/拒绝路径未实现；真实模型/金额配置不足、远程CI/外部联机未验证；没有任务执行恢复、普通聊天自动Go委派、多包/第三方依赖/任意仓库、race或跨进程协调。**本地可运行与效果推广分开：本地交付完成，T28整体待验证、推广门槛false，保持默认关闭。**


## S0–S9 完成后独立复验与隐藏缺陷审查（2026-10-17）

本次仅审查与复现，业务源码未修改、未调用收费模型。审查前后源码清单均为 `b0a72a1788389b3c883e50a7fa42fe56c5e0be4e13a8bbd947834badb8d77709`，与 S9 最终版本一致，HEAD/main 保持原值及未提交改动。

确认 **1 项 P1、4 项 P2**：R1 真实 Docker 测试筛选可绕过全部服务端验收，错误实现仍 multi-v1/passed；R2 JSON http.disconnect 未被监听，断线后继续生成/验证/审查；R3 已落库 passed 在流关闭时被改写 cancelled；R4 修复提示词遗漏 requirement_checks 的失败证据；R5 全局 enforce 预检拒绝发送却被记作两次模型失败并消耗重试。完整定位、复现、修复建议与已知交付缺口见 [审查报告](evidence/review-s0s9-20261017/review.md)。

本次完整离线 pytest：301 passed / 63 skipped / 138 subtests；开启真实 Docker 的完整 pytest：364 passed / 0 skipped / 140 subtests。新边界检查4项失败和1项真实Docker保障断言失败对应上述5个缺陷，均原样保留；只去掉测试筛选篡改的Docker对照正确检出错误代码。上述通过数不能覆盖新反例。git diff --check通过，最终沙箱标签容器零残留。Python3.11/远程CI/浏览器/收费模型本轮未执行。

结论：保持默认关闭；本次未修复这些缺陷，不宣称S0–S9整体验收通过。T05/T28待验证、T26/T27阻塞等S9原已知边界继续保留。
