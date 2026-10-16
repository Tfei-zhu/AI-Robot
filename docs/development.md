# 开发与评测

[返回项目首页](../README.md) · [使用与部署](usage.md)

所有命令均在项目根目录执行。

- [技术栈](#技术栈)
- [工作方式](#工作方式)
- [功能详解](#功能详解)
- [测试与 CI](#测试与-ci)
- [设计决策](#设计决策)
- [项目结构](#项目结构)

## 技术栈

| 层 | 组件 | 作用 |
|---|---|---|
| 服务框架 | FastAPI + Uvicorn + Pydantic | 异步 API、OpenAPI 文档、SSE |
| LLM 编排 | LangGraph + LangChain | 状态图、工具调用循环、提示词与流式状态更新 |
| Agent 工具 | LangChain Tools | 知识检索、文章查询、社区规范（全部只读） |
| 检索 | InMemoryVectorStore / Milvus、jieba、BM25、RRF | 向量、词面召回与融合 |
| 重排 | sentence-transformers `bge-reranker-base` | 候选内容相关性重排 |
| 稳定性 | tenacity、进程内滑动窗口限流、语义缓存 | 指数退避重试、限流与首轮答案复用 |
| 持久化与消息 | SQLite（WAL）、RabbitMQ（aio-pika） | 分块原文与文章状态持久化、发布事件订阅 |
| 安全 | 默认拒绝中间件、`secrets.compare_digest` | 管理员 / 网关双身份隔离与会话命名空间 |
| 评测 | pytest、固定场景回归、RAGAS + LLM-as-Judge | 机制测试、Go沙箱验收、检索质量及长对话四组对照 |
| 交付 | Docker、docker compose、GitHub Actions | 容器化与持续集成 |

## 工作方式

```text
客户端（浏览器经 Go 网关，或直接调用）
  │  POST /api/v1/chat 或 /api/v1/chat/stream
  ▼
SecurityMiddleware（默认拒绝：校验管理员 Bearer，或 Go 网关内部令牌 + 账号头）
  │
  ▼
FastAPI（限流、日志、异常处理）
  │
  └─ LangGraph Agent Run（run_id）
         规划 → 受限工具调用循环（最多 N 轮）→ 事实整合 → 最终答复
              ├─ search_knowledge → 向量 + BM25 → RRF → 可选重排 → 原文与来源
              ├─ query_article → Go 文章服务实时数据
              └─ community_guideline → 发布与讨论规范
```

`search_knowledge` 只返回检索原文与来源，工具内部不调用生成模型。Agent 按需选择一个或多个只读工具，并由独立的 `finalize` 节点统一生成最终回答；目前不具备发布、评论、修改文章等写入能力。

**接口时序**：JSON 与 SSE 共用同一张 LangGraph 图。请求经过鉴权、限流、会话占用、首轮缓存检查、Agent 规划、工具循环、最终生成与记忆写入。JSON 响应包含 `run_id`、`steps`、`sources`、`engine`、`cache_hit` 与 `session_id`；SSE 将步骤拆成事件输出，`done` 的字段与 JSON 响应不同，详见[流式接口](usage.md#post-apiv1chatstream)。

## 功能详解

### 对话与 Agent

- **状态图编排**：LangGraph 按“规划 → 工具调用 → 重新规划 / 最终答复”运行。`AIROBOT_AGENT_MAX_TOOL_ROUNDS` 默认限制为 4 轮；一轮可以包含多个工具调用，当前逐个执行，因此该配置不是工具调用总次数上限。
- **受限工具**：`search_knowledge`、`query_article` 与 `community_guideline` 均为只读工具，结果会连同来源回填到状态图和客户端。
- **多轮会话**：按 `session_id` 隔离会话，默认在内存保留最近`AIROBOT_MEMORY_MAX_TURNS`轮、取最近`AIROBOT_MEMORY_RETRIEVE_TURNS`轮；上下文模块启用后保存原始历史，并在强制模式按Token预算及摘要构造输入，见 [上下文管理](context-management.md)。
- **双通道输出**：非流式 JSON 与 SSE 流式接口均为异步执行，共用 Agent 图。SSE 会发送 `plan`、`tool_call`、`tool_result`、`token` 与 `done` 等事件。

### Go 知识库与检索

- **文档解析**：支持 PDF、Word、Markdown 与纯文本；Markdown 会按 H1-H4 标题优先分块，超长内容再递归切分。
- **混合检索**：先执行向量召回，再执行 jieba + BM25 词面召回，使用 RRF（倒数排名融合）合并两路结果；当前实现为顺序执行。Go 包名、模块路径、版本号与精确 API 名称可从词面检索获益。
- **语义重排**：可选 `BAAI/bge-reranker-base` 对候选片段重排；模型不可用时自动保留融合排序。
- **受约束生成**：Agent 提示词要求根据工具结果回答，对工具结果之外的信息说明不确定性，并将工具原文视为不可信资料；这些是提示词约束，不是答案真实性的自动校验。

### 稳定性与可观测性

| 组件 | 机制 | 相关配置 |
|---|---|---|
| 重试 | tenacity 为模型非流式调用与向量调用提供重试，识别 OpenAI 429/5xx 及部分连接、超时异常；最终 SSE 生成不在应用层重试 | `AIROBOT_RETRY_ATTEMPTS`、`AIROBOT_RETRY_MAX_WAIT` |
| 限流 | 进程内 60 秒滑动窗口，网关身份按 `account/<账号>` 计数，管理员共用 `admin` 额度；`stats`、`traces` 豁免 | `AIROBOT_RATELIMIT_PER_MINUTE` |
| 答案缓存 | 同一认证身份、语义相近的问题、相同知识库版本的首轮纯知识回答可复用；动态文章与失败结果不缓存 | `AIROBOT_CACHE_*` |
| 入库重投 | 可恢复失败有限次指数退避重投，超限登记失败表并停止重投 | `AIROBOT_AMQP_MAX_RETRIES`、`AIROBOT_AMQP_RETRY_*` |
| 链路追踪 | 近期请求摘要包含缓存检查耗时、总耗时、工具调用数等；正常 SSE 生成另记首 token 耗时与输出块数。聚合最近最多 300 条记录的 P95 与缓存命中率 | `/api/v1/traces` |

检索分阶段耗时位于 JSON 的 `steps` 中，或 SSE 的 `stage=retrieval` 事件中；当前不会完整写入 `/api/v1/traces`。Go HTTP 客户端仅对重试分类器识别的网络异常重试，HTTP 429/5xx 会转为 `GoServiceError`，不在 HTTP 层自动重试；MQ 入库失败另有消息重投机制。

## 测试与 CI

`.github/workflows/ci.yml` 在推送到 `main` 和 Pull Request 时运行以下四个Job（Python 3.11）：

| Job | 内容 |
|---|---|
| `build` | 安装核心依赖 + `compileall` 语法门禁（覆盖 `app`、`eval`、`scripts`、`tests`） |
| `test` | 稳定性、Go 集成、Agent、追踪与加固离线测试，外加 Agent 路径评测与「服务可导入」冒烟；原有脚本可单独运行，Go及上下文回归需要pytest |
| `go-validation` | 构建固定Go镜像，运行真实Docker沙箱、工作流测试与固定输出评测 |
| `eval` | 配置模型 Secrets 后运行前 5 条 RAGAS + Judge 评测，门禁为 `--min-baseline-hit-rate 0.85 --min-judge-score 3.5`，报告作为 artifact 上传 |

CI配置见 [工作流](../.github/workflows/ci.yml)。安装核心依赖后，可在项目根目录运行对应的离线检查（服务导入冒烟不会执行启动恢复）：

```bash
python -m compileall -q app eval scripts tests
python tests/test_stability.py
python tests/test_integration.py
python tests/test_agent.py
python tests/test_tracing.py
python -m unittest discover -s tests -p "test_hardening.py" -v
python eval/run_agent_eval.py
python -c "from app.main import app; print('import OK, routes:', len(app.routes))"
```

`eval/run_agent_eval.py` 运行真实 LangGraph 但替换模型与外部服务，验证**路径**而非自然语言质量：知识、文章、组合工具、工具失败、轮次上限、直接回答 6 类。

完整离线回归先安装`requirements-dev.txt`，再运行`python -m pytest tests -q`。Go沙箱验收及真实模型评测分别见 [Go验证指南](go-validation.md#测试与可复现演示) 和 [上下文评测说明](context-management.md#评测与金额)。

上下文四组对照覆盖30条脚本、各重复3次；质量与效率结论见 [完整验收报告](context-management-final-results.md)，综合门槛未通过，默认关闭。

以下质量评测需要可用的 LLM 与 Embedding 配置，会调用模型。`--agent` 执行 Agent 工具链并记录实际召回上下文；省略该参数时运行直接 RAG 路径。`--no-ragas` 只跳过 RAGAS，仍调用 LLM-as-Judge，不是离线模式：

```bash
python eval/run_eval.py --agent --limit 5 --top-k 3 --no-ragas
python eval/run_eval.py --agent         # 完整 Agent + RAGAS + Judge + 关键词基线
python eval/run_eval.py                 # 直接 RAG 路径的完整评测
python scripts/bench_retrieval.py --top-k 5
python scripts/bench_splitter.py --top-k 3
```

启用 RAGAS 前须安装 `requirements-eval.txt`，脚本不会在缺少依赖时自动跳过。CI 仅在 LLM 和 Embedding 两个 Secrets 均非空时安装并执行 RAGAS；当前门禁检查关键词命中率与 Judge 均分，RAGAS 四指标用于报告，没有设置通过阈值。报告默认写入 `eval/reports/`，检索与分块基准也需要 Embedding 服务。

离线导入入口与生产导入请区分：

```bash
# 隔离基准库：默认内存后端下，脚本退出后不保留索引
python scripts/ingest.py data/knowledge_base.md

# 生产库离线维护：先停服，执行后再启动服务
python scripts/ingest.py --production data/knowledge_base.md
```

知识工具本身不再生成答案，只返回原文；规划仍可多轮调用工具，JSON 和 SSE 共用独立的最终生成节点。因此常规单工具路径包含「首次规划、停止规划、最终生成」三次模型调用，不能把“去除工具内生成”理解为所有请求固定只调用两次。SSE 的首字时间仍包含规划和检索耗时，但不再等待最终答案生成完毕。

可使用 `Dockerfile` 与 `docker-compose.yml` 容器化部署。生产环境应为模型密钥、限流、追踪与凭据接入相应的基础设施。

## 设计决策

- **为什么使用 LangGraph 而非 CrewAI？** 本项目需要把规划、工具调用、来源和流式事件统一到同一状态图；LangGraph 直接提供该编排模型，避免 JSON 与 SSE 使用两条不同的执行路径。
- **为什么使用混合检索？** Go 模块路径、包名、版本和 API 名称需要精确词面命中；语义检索则更适合概念性问题，两者融合更稳健。
- **为什么只缓存首轮纯知识回答？** 避免复用依赖会话历史或实时文章数据的答案。缓存按认证身份与知识库版本隔离，向量余弦相似度（`AIROBOT_CACHE_THRESHOLD`）和 jieba 词面重叠率（`AIROBOT_CACHE_LEXICAL_THRESHOLD`）必须同时达标；两个阈值都可调高以收紧匹配。只有「全部工具调用均为成功知识检索且存在来源」的首轮回答才写缓存；若知识库在生成期间变化，本次结果不写缓存。查询缓存发生在规划之前，双门限是相似度筛选，不保证问题语义完全等价；可用 `AIROBOT_CACHE_ENABLED=false` 关闭。
- **为什么保留文章查询的真实 HTTP 调用？** `query_article` 已替换为对 Go 文章服务的调用，带超时、重试、鉴权与降级；Go 服务不可用时明确提示而不是编造内容，现有 API 和对话编排无需改变。

## 项目结构

```text
app/
  agents/       LangGraph 状态图与Go社区工具
  context/      输入预算、摘要、证据、工具原文与持久化
  go_validation/ Go示例契约、沙箱执行与任务报告
  rag/          文档解析、向量/BM25 检索、RRF、重排与 RAG
  services/     对话、记忆、语义缓存、限流、重试、鉴权、追踪、Go 客户端与 MQ 消费者
  static/       Go 文章社区助手 Dashboard
  config.py     全部配置项与环境变量
  main.py       路由、生命周期与中间件装配
data/           示例 Go 社区知识库与 SQLite 状态库
eval/           评测集、RAGAS 评测与离线 Agent 路径评测
scripts/        入库、检索/分块基准与评测集合清理脚本
tests/          稳定性、集成、Agent、上下文与Go验证回归
sandbox/go/     固定Go验证镜像
docs/           使用、开发及专项验收文档
```
