# Go 文章社区 Agent（FastAPI + LangGraph + RAG）

这是一个面向 **Go 技术文章社区** 的 AI 助手服务。它帮助用户理解 Go 技术文章、发布规范、代码示例与社区讨论规则，并提供文章状态查询、多轮对话与 SSE 流式回答。

服务由 FastAPI、LangGraph Agent 和 LangChain RAG 构建。Agent 能规划并调用受限的只读工具；RAG 是其中的知识检索工具，而不是固定问答主流程。

![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688)
![LangGraph](https://img.shields.io/badge/LangGraph-1.0%2B-1C3C3C)
![License](https://img.shields.io/badge/License-MIT-green)

## 目录

- [核心能力](#核心能力)
- [与 Go 文章社区集成](#与-go-文章社区集成)
- [技术栈](#技术栈)
- [工作方式](#工作方式)
- [功能详解](#功能详解)
- [快速开始](#快速开始)
- [接口说明](#接口说明)
- [认证与安全](#认证与安全)
- [知识库与持久化](#知识库与持久化)
- [可视化控制台](#可视化控制台)
- [Docker 部署](#docker-部署)
- [测试与 CI](#测试与-ci)
- [设计决策](#设计决策)
- [环境变量说明](#环境变量说明)
- [项目结构](#项目结构)
- [常见问题](#常见问题)
- [相关文档](#相关文档)

## 核心能力

| 能力模块 | 说明 | 对应接口 |
|---|---|---|
| 社区 Agent | LangGraph 规划、工具调用循环、事实整合与多轮记忆 | `POST /api/v1/chat` |
| 流式 Agent | SSE 推送规划、工具调用、工具结果与最终答复 | `POST /api/v1/chat/stream` |
| Go 示例验证与修复 | context 取消、并发任务池、channel 三场景；隔离编译、静态检查、行为测试；最多两轮修复 | `POST /api/v1/go/tasks`、`POST /api/v1/go/tasks/stream` |
| 运行状态 | JSON 聊天响应包含 `run_id`、工具步骤和来源；SSE 逐事件输出；轨迹接口提供近期运行摘要 | 聊天接口、`GET /api/v1/traces` |
| Go 知识库 | 社区文章经 RabbitMQ 事件**自动入库**；也支持 PDF、DOCX、Markdown、TXT 手动上传 | `POST /api/v1/ingest` |
| 文章工具 | 查询文章**真实数据**（标题/作者/标签/点赞/评论，来自 Go 文章服务） | `app/agents/tools.py` |
| 可观测性 | 实时控制台、请求追踪、缓存与限流指标 | `/dashboard`、`/api/v1/traces`、`/api/v1/stats` |

## 与 Go 文章社区集成

新增的 Go 代码验证需要先构建独立验证镜像，并让本地 Python 服务能够调用 Docker。启动方法、固定接口、逐项验收和对比结果见 [Go 验证使用文档](docs/go-validation.md) 与 [完成清单](GO_VALIDATION_CHECKLIST.md)。固定输出评测验证了执行链路；真实模型质量需要本地配置密钥后运行 `--live` 评测。

本服务提供与 Go 文章社区后端（仓库 `Tfei-zhu/csdn_article_go`）的集成。配置 Go 服务与 RabbitMQ 后，新发布的文章可自动进入知识库，文章查询工具可读取实时详情；知识库也可以使用示例资料与手动上传文件。链路如下：

```text
① 自动学习：Go 发布文章 → RabbitMQ 发出事件
   → 本服务的消费者收到 → 调 Go 内部接口拿全文
   → 切块、向量化 → 存入知识库（后续提问可参与检索）

② 真实查询：用户问「文章 12 的数据」
   → query_article 工具 → 调 Go 内部接口 → 返回真实的标题/作者/标签/点赞/评论

③ 社区网页聊天：请求经过 Go 网关
   → Go 校验登录态和限流 → 转发本服务 → SSE 流回网页
```

**主要实现：**

| 文件 | 作用 |
|---|---|
| `app/services/article_consumer.py` | RabbitMQ 消费者：订阅文章发布事件并自动入库；断线自动重连、重复投递去重、坏消息 ack 丢弃不堵队列、可恢复失败有限次退避重投 |
| `app/services/go_client.py` | Go 服务客户端：查文章详情（异步 + 同步双通道），对部分连接/超时异常重试，404 友好提示 |
| `app/agents/tools.py` | JSON 与 SSE 共用异步文章查询工具；同步兼容入口供离线调用 |
| `app/rag/retriever.py` | 文章分块与入库，元数据带 `article_id`，可追溯到具体文章 |
| `app/rag/lexical.py` | 增量维护 BM25 索引，与向量侧文档保持对齐 |
| `app/main.py` | 应用启动时拉起消费者、关闭时释放资源；网关流量按账号限流 |
| `tests/test_integration.py` | 离线集成测试：Go 客户端、消费者去重与恢复、BM25 增量对齐 |

**启用方式：** 在 `.env` 中设置 `AIROBOT_GO_API_BASE_URL`（指向 Go 服务）与 `AIROBOT_AMQP_URL`（指向 RabbitMQ）。凭据是「一个共享密钥 + 一个独立管理密钥」：

| 变量 | 方向 | 取值 |
|---|---|---|
| `AIROBOT_GO_INTERNAL_TOKEN` | 出站：本服务调用 Go `/internal/ai` 时携带 | 必须等于 Go 侧的 `AI_INTERNAL_TOKEN` |
| `AIROBOT_AI_INTERNAL_TOKEN` | 入站：校验 Go 网关透传的 `X-Internal-Token` | 必须等于 Go 侧的 `AI_INTERNAL_TOKEN`（与上一行同值） |
| `AIROBOT_ADMIN_TOKEN` | 管理员凭据 | 独立随机长字符串，**必须与上面两个不同** |

Go 侧只用一个 `AI_INTERNAL_TOKEN` 同时承担收发两端（既校验入站请求，也签发出站请求），所以本服务必须把同一个值填进两个变量。管理员令牌与网关令牌相同时服务会在启动阶段直接报错退出。不配置 Go 集成时可独立使用知识问答；实时文章查询返回降级提示，自动文章入库需要 RabbitMQ 和 Go 服务均可用。

文章详情请求为 `POST /internal/ai/article/detail`，请求体为 `{"id": 12}`，携带 `X-Internal-Token`。自动入库只处理订阅队列收到的发布事件，不会主动回填社区历史文章，也不支持文章更新、删除同步。本仓库的 `/dashboard` 直接使用管理员凭据调用 Python API。配置示例见 [`.env.example`](.env.example)。

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
| 评测 | RAGAS + LLM-as-Judge | 检索增强问答的质量评估 |
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

**接口时序**：JSON 与 SSE 共用同一张 LangGraph 图。请求经过鉴权、限流、会话占用、首轮缓存检查、Agent 规划、工具循环、最终生成与记忆写入。JSON 响应包含 `run_id`、`steps`、`sources`、`engine`、`cache_hit` 与 `session_id`；SSE 将步骤拆成事件输出，`done` 的字段与 JSON 响应不同，详见[流式接口](#post-apiv1chatstream)。

## 功能详解

### 对话与 Agent

- **状态图编排**：LangGraph 按“规划 → 工具调用 → 重新规划 / 最终答复”运行。`AIROBOT_AGENT_MAX_TOOL_ROUNDS` 默认限制为 4 轮；一轮可以包含多个工具调用，当前逐个执行，因此该配置不是工具调用总次数上限。
- **受限工具**：`search_knowledge`、`query_article` 与 `community_guideline` 均为只读工具，结果会连同来源回填到状态图和客户端。
- **多轮会话**：按 `session_id` 隔离会话，保留最近 `AIROBOT_MEMORY_MAX_TURNS` 轮，并在生成时带入最近 `AIROBOT_MEMORY_RETRIEVE_TURNS` 轮。
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

## 快速开始

### 1. 安装依赖

以下命令在项目根目录执行，使用 Python 3.11+：

```bash
python -m venv .venv
source .venv/bin/activate
# Windows PowerShell 将上一行替换为：.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

# 可选：bge-reranker + Milvus 客户端（会安装体积较大的 torch 等依赖）
python -m pip install -r requirements-extra.txt

# 可选：RAGAS 评测
python -m pip install -r requirements-eval.txt
```

### 2. 配置模型

复制 `.env.example` 为 `.env`（已有文件时保留并编辑），配置支持工具调用的 OpenAI 兼容 LLM，以及可用的 Embedding 服务。`.env.example` 默认启用的是云端配置，里面的占位密钥不能直接使用。

本地 Ollama 模式：先启动 Ollama，在终端执行 `ollama pull qwen2.5:7b` 和 `ollama pull nomic-embed-text`，再将 `.env` 中对应配置替换为以下值，每个变量只保留一条有效赋值：

```ini
AIROBOT_LLM_BASE_URL=http://localhost:11434/v1
AIROBOT_LLM_API_KEY=ollama
AIROBOT_LLM_MODEL=qwen2.5:7b
AIROBOT_EMBEDDING_BASE_URL=http://localhost:11434/v1
AIROBOT_EMBEDDING_API_KEY=ollama
AIROBOT_EMBEDDING_MODEL=nomic-embed-text
# 独立使用时设置管理员令牌，以访问聊天、上传及控制台数据
AIROBOT_ADMIN_TOKEN=请替换为独立随机长令牌
# 暂不接入 Go / RabbitMQ 时，清空示例集成配置
AIROBOT_GO_API_BASE_URL=
AIROBOT_GO_INTERNAL_TOKEN=
AIROBOT_AI_INTERNAL_TOKEN=
AIROBOT_AMQP_URL=
# 首次运行可关闭可选重排
AIROBOT_RERANK_ENABLED=false
```

可用 `python -c "import secrets; print(secrets.token_urlsafe(32))"` 生成管理员令牌并填入 `.env`。云端模式则填写供应商地址、模型名和真实密钥，LLM 与 Embedding 可来自不同服务。

配置缺失时的行为：

- 两个入站令牌 `AIROBOT_ADMIN_TOKEN`、`AIROBOT_AI_INTERNAL_TOKEN` 都为空：所有 `/api/*` 返回 `503`，请求不会到达聊天逻辑。
- 身份校验通过，但 `AIROBOT_LLM_API_KEY` 为空：聊天返回缺少配置的提示；非流式响应的 `intent` 为 `null`。
- `AIROBOT_EMBEDDING_API_KEY` 为空：上传接口返回 `400`；向量化、向量检索和索引恢复仍需要可用的 Embedding 服务，不能视为离线可用。
- 首次空库启动时，示例导入失败会记录警告并继续；已有 `knowledge.sqlite3` 分块的启动恢复失败则会阻止启动。

### 3. 启动

```bash
python -m uvicorn app.main:app --reload --port 8000
```

启动先恢复已持久化的知识分块，仅在恢复后分块数为 0 时尝试导入 [Go 社区示例知识库](data/knowledge_base.md)，随后恢复文章状态并启动已配置的 MQ 消费者。服务不会扫描整个 `data/` 目录，也不会自动覆盖已有知识。

打开 [Dashboard](http://localhost:8000/dashboard)，在顶部输入管理员令牌后使用聊天和监控。接口结构可在 [OpenAPI 文档](http://localhost:8000/docs) 查看；当前鉴权由中间件实现，未声明 OpenAPI 安全方案，需用下面的命令显式携带请求头进行验证。生产运行去掉 `--reload`，保持单 worker。

**Windows 启动脚本**：完成上述 `.env` 配置后，可运行 `.\start.ps1` 或双击 `start.bat`。脚本创建虚拟环境、安装核心依赖、检查本机 Ollama、启动服务并打开 Dashboard；它只提示缺失的模型，不会自动拉取，也不会将云端配置切换为 Ollama。停止服务使用 `.\stop.ps1`。

### 4. 验证

应用读取 `.env` 不会把变量导出到你当前的终端。下面的令牌必须与 `.env` 中配置的管理员令牌一致。

macOS / Linux：

```bash
export AIROBOT_ADMIN_TOKEN='替换为你配置的管理员令牌'
curl http://localhost:8000/health
curl http://localhost:8000/api/v1/stats \
  -H "Authorization: Bearer $AIROBOT_ADMIN_TOKEN"
curl http://localhost:8000/api/v1/chat \
  -H "Authorization: Bearer $AIROBOT_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"message":"Go 并发示例需要说明哪些内容？","session_id":"go-reader-001"}'
```

Windows PowerShell：

```powershell
$env:AIROBOT_ADMIN_TOKEN = '替换为你配置的管理员令牌'
Invoke-RestMethod http://localhost:8000/health
$headers = @{ Authorization = "Bearer $env:AIROBOT_ADMIN_TOKEN" }
Invoke-RestMethod http://localhost:8000/api/v1/stats -Headers $headers

$body = @{ message = "Go 并发示例需要说明哪些内容？"; session_id = "go-reader-001" } | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:8000/api/v1/chat -Headers $headers -Method Post -Body ([System.Text.Encoding]::UTF8.GetBytes($body)) -ContentType "application/json; charset=utf-8"
```

## 接口说明

所有 `/api/*` 接口默认拒绝匿名访问，按凭据区分权限：

| 接口 | 需要的凭据 |
|---|---|
| `GET /health` | 公开 |
| `GET /dashboard` | 公开（仅页面外壳，数据来自下列受保护接口） |
| `GET /docs`、`/redoc`、`/openapi.json` | 公开的接口文档与结构 |
| `POST /api/v1/chat`、`/api/v1/chat/stream` | 管理员 Bearer，**或** Go 网关内部令牌 + `X-Account-Id` |
| `POST /api/v1/ingest` | 仅管理员 Bearer |
| `GET /api/v1/stats`、`/api/v1/traces` | 仅管理员 Bearer |
| 其他 `/api/*` 路径 | 先鉴权：无凭据为 401（两个入站令牌均未配置时为 503），网关身份为 403；管理员通过后由路由决定 404/405 等结果 |

### `GET /health`

进程存活检查，返回模型名称与登记的入库失败计数。此接口不会探测 LLM、Embedding、Go、RabbitMQ 或 Milvus 的连通性，`status=ok` 不代表完整业务链路就绪。

```json
{
  "status": "ok",
  "llm_model": "qwen2.5:7b",
  "embedding_model": "nomic-embed-text",
  "engine": "langgraph",
  "ingest_failed_events": 0
}
```

`ingest_failed_events > 0` 表示已有文章连续处理失败并停止本次投递的重试。只有已经保存正文的文章可以通过启动恢复重试；仅有失败记录的文章还需重新投递事件，详见[知识库与持久化](#知识库与持久化)。

### `POST /api/v1/chat`

社区助手对话。请求：

```json
{
  "message": "Go 并发示例需要说明哪些内容？",
  "session_id": "go-reader-001"
}
```

成功响应示例（`steps` 仅展示一条，实际还包含规划、工具结果、检索和最终完成步骤）：

```json
{
  "reply": "并发示例需说明 goroutine 的退出方式、context 的传播和错误处理。",
  "intent": "agent",
  "sources": ["knowledge_base.md#7"],
  "engine": "langgraph",
  "run_id": "c61f1c3e...",
  "steps": [{"type": "tool_call", "tool": "search_knowledge"}],
  "cache_hit": false,
  "session_id": "go-reader-001"
}
```

| 字段 | 说明 |
|---|---|
| `message` | 用户的 Go 技术或社区问题，最长 16000 字符 |
| `session_id` | 可选；只允许字母、数字、下划线和连字符，最长 128 字符。省略时随机生成并在响应中返回 |
| `reply` | 社区助手回答 |
| `intent` | 正常运行和缓存命中时为 `agent`；缺少 LLM Key 的提示响应为 `null` |
| `sources` | 工具返回的来源标识，去重并保留顺序；是检索来源记录，不是逐句引用或事实校验结果 |
| `engine` | 固定为 `langgraph` |
| `run_id` / `steps` | 本次运行标识和规划、工具调用轨迹 |
| `cache_hit` | 是否命中语义缓存；命中时 `steps` 只含一条 `cache` 记录 |

文章查询示例：

```json
{"message":"查询文章 12 的数据","session_id":"go-reader-001"}
```

`query_article` 只识别带「文章 / article」前缀的数字编号（如「文章 12」「article #3」），避免把普通数字误判成文章 ID。通过 Go 文章服务返回真实详情；服务未配置或查询失败时明确提示不可用。

### `POST /api/v1/chat/stream`

请求体与 `/api/v1/chat` 相同，响应为 `text/event-stream`。每个事件是 `data: <JSON>`，用空行分隔，事件类型位于 JSON 的 `type` 字段。正常未命中缓存的路径为：

```text
stage(rate_limit) → stage(cache) → intent(agent)
→ [stage(agent) + plan
   → stage(tool) + tool_call（每个工具一组）
   → stage(tool) + tool_result（每个工具一组）
   → stage(retrieval)（知识工具成功时）] 可重复多轮
→ stage(agent) + plan（结束规划）
→ stage(generate) → token* → stage(generate)
→ stage(write) → done
```

`token` 只转发最终生成节点的文本片段，片段不保证是单字或单个模型 token；规划状态通过 `plan` 发送，工具参数通过 `tool_call.args` 发送。图节点完成后才输出该节点的步骤，同一工具节点的结果在整轮工具执行完后输出。知识检索事件的 `detail` 包含向量、BM25、融合和重排耗时。

| 事件 | 主要字段 |
|---|---|
| `stage` | `stage`、`msg`、`ok`，按阶段附带 `ms`、`sources`、`detail` 等 |
| `intent` | `intent: "agent"` |
| `plan` | `status`、`msg`，为规划状态摘要 |
| `tool_call` | `tool`、`args` |
| `tool_result` | `tool`、`ok`、`msg`、`summary`，成功时附带 `sources` |
| `token` | `content`，应按到达顺序拼接 |
| `error` | `msg`、`run_id` |
| `done` | 正常完成含 `run_id`、`intent`、`sources`、`total_ms`、`first_token_ms`、`cache_hit`、`session_id`；不含 `reply`、`steps` 或 `engine` |

特殊路径：

- **缓存命中**：`stage(rate_limit) → stage(cache) → token → done`，整段返回缓存答案并写入记忆；不发送 `intent` 事件，`done` 不含 `first_token_ms`。
- **缺少 LLM Key**：`stage(rate_limit) → token（配置提示）→ done`，`done` 仅含 `run_id`、`session_id`。
- **Agent 执行失败**：发送 `error → done`，该 `done` 仅含 `run_id`、`session_id`；不提交部分回答到会话记忆。客户端须记录 `error`，不能仅凭 `done` 判定成功。
- **鉴权、限流、校验或会话冲突**：在流开始前返回普通 HTTP 错误响应；流建立后发生的执行错误通过事件表示，HTTP 状态通常已是 `200`。

典型事件节选（省略部分字段和步骤）：

```text
data: {"type":"stage","stage":"rate_limit","msg":"限流检查通过，请求进入 Agent"}

data: {"type":"stage","stage":"cache","msg":"语义缓存未命中"}

data: {"type":"intent","intent":"agent"}

data: {"type":"plan","status":"tool","msg":"已规划下一步，准备调用工具"}

data: {"type":"tool_call","tool":"search_knowledge","args":{"query":"Go 并发示例需要说明哪些内容？"}}

data: {"type":"tool_result","tool":"search_knowledge","ok":true,"sources":["knowledge_base.md#7"]}

data: {"type":"stage","stage":"retrieval","sources":["knowledge_base.md#7"]}

data: {"type":"token","content":"并发示例需说明..."}

data: {"type":"stage","stage":"write","msg":"写入会话记忆与执行轨迹"}

data: {"type":"done","run_id":"c61f1c3e...","intent":"agent","sources":["knowledge_base.md#7"],"cache_hit":false,"total_ms":1500.0,"first_token_ms":900.0,"session_id":"go-reader-001"}

```

命令行调试可将快速开始中的聊天地址换成 `/api/v1/chat/stream`，并给 `curl` 添加 `-N` 关闭输出缓冲。

### `POST /api/v1/ingest`

上传资料到知识库，使用 multipart 表单字段 `file`，支持 `.pdf`、`.docx`、`.md`、`.txt`、`.markdown`。

```bash
curl -X POST http://localhost:8000/api/v1/ingest -H "Authorization: Bearer $AIROBOT_ADMIN_TOKEN" -F "file=@data/knowledge_base.md"
```

### `GET /api/v1/stats` 与 `GET /api/v1/traces`

`stats` 返回知识库分块数、模型名称、检索开关、缓存与限流计数。`rerank_enabled` 表示配置开关，不保证重排模型加载成功。

`traces` 返回 `entries` 和 `summary`，`limit` 默认 50，允许 1–200。记录最多保留 300 条；汇总的总数、P95 和限流数均基于这个窗口，并非服务启动以来全部请求。当前主要记录聊天执行与限流拦截，不是所有 HTTP 请求的访问日志。SSE 的 `tokens` 统计输出文本块数，不是供应商计费 token 数；完整步骤和检索耗时请读取聊天响应或 SSE 事件。

`GET /dashboard` 返回自包含的可视化控制台；监控接口不参与业务限流，但需要管理员凭据。

### 错误码

| 状态码 | 含义 |
|---|---|
| `400` | 文件类型不支持、上传为空、`Content-Length` 无效，或上传时未配置 Embedding Key |
| `401` | 未提供或提供了错误的身份凭据 |
| `403` | 身份有效但无权访问该接口（网关身份只能调用两个聊天接口） |
| `409` | 同一会话正在处理上一条消息，并发请求被拒绝 |
| `413` | 请求体或上传文件超过上限 |
| `422` | FastAPI/Pydantic 校验失败，例如 `message` 为空、`session_id` 不合法、缺少上传字段 |
| `429` | 触发限流，请稍后再试 |
| `500` | 未处理异常，统一返回固定文案，不暴露内部堆栈 |
| `503` | 服务尚未配置任何访问凭据（`AIROBOT_ADMIN_TOKEN` 与 `AIROBOT_AI_INTERNAL_TOKEN` 均为空） |

## 认证与安全

- **两类凭据**：管理员用 `Authorization: Bearer <AIROBOT_ADMIN_TOKEN>`；Go 网关用 `X-Internal-Token: <AIROBOT_AI_INTERNAL_TOKEN>` 加可信的 `X-Account-Id`（须为正整数）。内部令牌不等同于管理员：网关身份只能调用两个聊天接口，不能读取全局轨迹或上传资料。两种令牌必须不同，否则服务启动即报错。令牌请使用随机长字符串，不要提交到 Git。
- **令牌拓扑**：Go 侧只有一个 `AI_INTERNAL_TOKEN`，同时用于校验入站与签发出站请求，因此本服务的 `AIROBOT_AI_INTERNAL_TOKEN`（入站）与 `AIROBOT_GO_INTERNAL_TOKEN`（出站）必须填成同一个值，即 Go 侧的 `AI_INTERNAL_TOKEN`。
- **会话隔离**：`session_id` 只在认证身份内有效——不同用户即使传相同值也不会共享历史，内部键是 `sha256(身份) + ":" + sha256(会话号)`。省略时服务生成随机编号并在 JSON / SSE `done` 返回，后续请求须带回。同一会话同时发起第二个请求返回 `409`。
- **管理员身份**：所有管理员请求属于同一个 `admin` 身份，共享限流与缓存命名空间；相同会话号也会共享历史。多用户隔离应通过可信 Go 网关的账户身份实现。
- **入口防护**：`SecurityMiddleware` 是最外层中间件，在限流、解析上传文件与业务路由之前完成身份校验；POST/PUT/PATCH 请求体会在解析前按上限拦截（上传接口按文件上限 + multipart 元数据余量，其余 JSON 接口按 `AIROBOT_MAX_REQUEST_BYTES`），无 `Content-Length` 的分块传输按实际字节数累计拦截。
- **生产部署**：跨主机访问需要 HTTPS，并在网关侧保证 `X-Account-Id` 不被客户端伪造；本服务只在内部令牌匹配后才采信该头。

## 知识库与持久化

| 数据 | 默认位置 | 重启行为 |
|---|---|---|
| 知识分块原文与元数据 | `data/knowledge.sqlite3` | 重放分块、调用 Embedding 恢复向量和 BM25；失败会阻止启动 |
| MQ 文章正文、处理状态、失败记录 | `data/airobot_state.sqlite3` | 重放已保存正文的文章；单篇失败记录日志后继续 |
| 向量索引 | 默认 InMemoryVectorStore；可选 Milvus | 默认重新构建；Milvus 使用稳定主键写入，但仍需恢复本地 BM25 |
| 对话历史、语义缓存、限流、轨迹、会话占用 | 当前 Python 进程内存 | 重启丢失，不跨 worker 或实例共享 |

两个 SQLite 文件默认都位于 `data/`，应一起持久挂载和备份。知识分块主键由**正文与元数据共同哈希**生成；重复导入相同文件名、内容与分块配置可去重，改变文件名或元数据会被视为新分块。上传只保留分块和原文件名，不保留原始 PDF/DOCX 文件。

导入目前是追加语义：重新上传修改后的文件不会删除旧分块，也没有知识删除 API。替换 `data/knowledge_base.md` 后重启不会覆盖已有索引；要替换整套知识，应停服、备份两个 SQLite 文件及向量数据，使用新的状态库路径（Milvus 同时用新集合名）重建后再切换。

### 文章自动入库与失败重投

文章发布事件由 RabbitMQ 投递到本服务：

- 无法解析的坏消息记录日志后确认（ack）丢弃，避免毒消息阻塞队列。
- 抓取文章、调用 Embedding 或写入知识库失败时抛出可恢复异常，消息重新入队，并按 `AIROBOT_AMQP_RETRY_BACKOFF_SECONDS` 做指数退避（默认 2s、4s、8s…封顶 `AIROBOT_AMQP_RETRY_MAX_BACKOFF_SECONDS`，默认 30s），避免下游故障期间高速重投把 Broker 打满。
- 同一文章失败达到 `AIROBOT_AMQP_MAX_RETRIES`（默认 5，含首次处理）次后确认该消息并停止重投，登记到 `ingest_failures` 表并计入 `/health` 的 `ingest_failed_events`；成功入库后清除失败记录与重试计数。尝试次数保存在内存中，重启会重置。
- 启动只重放 `ingested_articles` 中已保存正文的 `pending` / `ingested` 记录。若文章抓取一直失败，只有 `ingest_failures` 而没有正文，**重启不会重新抓取**；修复 Go 服务后需向已配置的交换机/路由键重新投递包含该 `article_id` 的发布事件。当前没有失败事件重放 API 或 CLI。
- 已持久化的正文可在 Embedding 和向量后端恢复可用后重建索引；若 `knowledge.sqlite3` 的恢复先失败，必须先解决该错误，应用才能继续启动。
- Docker Compose 已将 `./data` 挂载到容器 `/app/data`，请保留该目录或改用外部持久卷。

退避发生在串行消费者循环中，等待期间该循环不会处理下一条消息，prefetch 并不代表并行执行。需要更高吞吐时可扩展为死信队列 + TTL 重试队列。

### 向量库与索引约束

SQLite 是当前默认的知识源持久化方案；Milvus 可作为向量检索后端，生产集合名来自配置，评测与基准分别使用随机 `airobot_eval_*` / `airobot_bench_*`，不共享生产集合。实例化、导入模块和服务启动均无清库副作用。

- 旧 `AIROBOT_MILVUS_RESET_ON_START` 已废弃，无论取值是什么都不会清库。
- 旧 `auto_id=true` 集合会被拒绝写入（稳定主键是幂等入库与恢复的前提）：先备份旧集合和 SQLite，再配置全新集合名，重建验证后切换；不要直接删除旧集合。旧集合独有而 SQLite 没有的资料必须先导出或重新导入。
- 评测结束会在报告中记录集合名，可用 `python scripts/reset_collection.py --collection <评测集合名> --confirm <同名>` 显式清理。此脚本拒绝生产集合，不会自动清除评测报告或数据库。
- 现阶段是**单进程、单实例索引**：请使用一个 Uvicorn worker。线程锁保护两路索引的一致读写，入库移至工作线程；BM25 仅对新增文档分词并更新倒排统计。此实现采用正值 IDF，与原 rank_bm25 的分数不完全相同，需要比较质量报告。文章更新/删除同步不属于发布事件协议，不能把发布去重当作更新支持。
- CLI 导入与运行服务不是同一进程。生产在线导入使用带管理员凭据的 HTTP 上传；`scripts/ingest.py` 默认导入隔离的基准库，不更新生产库。离线维护生产数据需先停服，运行 `python scripts/ingest.py --production data/knowledge_base.md`，再重启以恢复两路索引。

### 评测数据集

- `data/knowledge_base.md`：发布文章、标签、Markdown、审核修订、版权引用、评论互动和 Go 示例质量规则。
- `eval/dataset/qa.jsonl`：52 条 Go 文章社区问答样本，覆盖发布、标签、Markdown、审核、版权、讨论、互动、并发示例与知识库未覆盖问题。
- `eval/run_eval.py`：RAGAS 四指标、LLM-as-Judge 与关键词命中评测。

## 可视化控制台

启动后打开 <http://localhost:8000/dashboard>，**在页面顶部填入管理员令牌**（`AIROBOT_ADMIN_TOKEN`）后才能拉取数据；令牌只保留在当前页面内存中，不会落盘。控制台不依赖外部 CDN，提供：

- 用户模拟对话：支持流式回答、切换 `session_id` 和 Go 社区快捷问题；
- 全链路可视化：实时显示限流、缓存、意图、混合检索、工具调用、生成与记忆写入；
- 状态卡片：监控接口连接状态、模型、知识库分块、缓存命中率、近期 P95、限流拦截与窗口内记录数；
- 实时监控：最近请求摘要、状态码与延迟趋势，每 3 秒刷新一次；尚未采集的阶段耗时可能为空。

监控数据来自 `GET /api/v1/stats` 和 `GET /api/v1/traces`；聊天面板直接调用 SSE 接口。目前页面主要处理 `stage`、`intent`、`token` 和 `done`，尚未单独处理 `error` 及结构化工具事件，排查流式失败时应结合原始 SSE 与服务日志。

## Docker 部署

### 内置 Ollama

先按[快速开始](#快速开始)准备 `.env`，将 LLM/Embedding 模型名分别设为 `qwen2.5:7b`、`nomic-embed-text`，两个模型 Key 均设为 `ollama`，并设置管理员令牌。直接复制默认云端 `.env.example` 会让 Ollama 尝试拉取云端模型名，不能直接运行。

```bash
docker compose up -d --build
docker compose logs -f ollama
```

Ollama 首次会下载配置的模型。当前 `depends_on` 仅保证启动顺序，不等待模型下载完成；确认两个模型都可用后，重启应用以重试空库导入或索引恢复：

```bash
docker compose exec ollama ollama list
docker compose restart airobot
docker compose logs -f airobot
```

- Compose 将容器的 LLM 与 Embedding 地址固定为 `http://ollama:11434/v1`，覆盖 `.env` 中的这两个地址，同时将重排开关覆盖为 `false`。
- Python API 默认只映射到宿主机 `127.0.0.1:8000`；同一容器网络内可通过 `http://airobot:8000` 访问。
- `./data:/app/data` 已覆盖两个默认 SQLite 文件。挂载文件变化不会自动更新已入库分块；新增资料使用 HTTP 上传，替换知识按[持久化说明](#知识库与持久化)操作。
- 镜像只安装 `requirements.txt`。启用 Milvus 需在构建镜像时额外安装 `langchain-milvus`；启用重排需安装 `sentence-transformers` 并修改 Compose 中的开关。仅在宿主机安装可选依赖不会改变容器。

### 云端模型

在 `.env` 填写云端模型、密钥和地址，并删除或修改 `docker-compose.yml` 中 `airobot.environment` 的两个 `AIROBOT_*_BASE_URL` 覆盖项。仅修改 `.env` 中的地址不会生效。可以保留 Ollama 定义而只启动应用：

```bash
docker compose up -d --build --no-deps airobot
```

若移除 `ollama` 服务，同时删除 `airobot.depends_on` 中的引用。

### Milvus 与 Go 联合部署

宿主机运行 Python 服务时，可执行 `docker compose -f docker-compose-milvus.yml up -d`，安装 `langchain-milvus`，并设置 `AIROBOT_VECTOR_STORE=milvus`、`AIROBOT_MILVUS_URI=http://localhost:19530`。

若 Python 也在容器内，先构建包含 Milvus 客户端的镜像，再将两个服务加入同一 Docker 网络。例如用 `docker compose -f docker-compose.yml -f docker-compose-milvus.yml up -d --build` 联合启动，并在 `.env` 设置 `AIROBOT_MILVUS_URI=http://milvus:19530`。服务首次启动前需确保 Milvus 就绪，必要时就绪后重启 `airobot`。

Go / RabbitMQ 地址同样必须能从 Python 容器访问；容器内 `localhost` 指向自身。当前 Compose 不包含 Go 或 RabbitMQ。默认路径下，现有 `./data` 挂载已足够保存两个 SQLite 文件，仅在自定义状态库路径移出 `/app/data` 时需要额外挂载。两侧使用一致的内部令牌，另配独立管理员令牌。

## 测试与 CI

`.github/workflows/ci.yml` 在推送到 `main` 和 Pull Request 时运行以下三个 Job（Python 3.11）：

| Job | 内容 |
|---|---|
| `build` | 安装核心依赖 + `compileall` 语法门禁（覆盖 `app`、`eval`、`scripts`、`tests`） |
| `test` | 稳定性、Go 集成、Agent、追踪与加固离线测试，外加 Agent 路径评测与「服务可导入」冒烟；项目无需 pytest 即可运行这些入口 |
| `eval` | 配置模型 Secrets 后运行前 5 条 RAGAS + Judge 评测，门禁为 `--min-baseline-hit-rate 0.85 --min-judge-score 3.5`，报告作为 artifact 上传 |

安装核心依赖后，可在项目根目录运行对应的离线检查（服务导入冒烟不会执行启动恢复）：

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

## 环境变量说明

变量从进程环境和项目根目录 `.env` 读取，已存在的进程环境变量优先；修改配置后需重启进程。下表为主要配置，代码默认值以 [`app/config.py`](app/config.py) 为准，示例文件和 Docker Compose 可能覆盖默认值。

| 变量 | 说明 |
|---|---|
| `AIROBOT_LLM_BASE_URL` / `AIROBOT_LLM_API_KEY` / `AIROBOT_LLM_MODEL` | 支持工具调用的 OpenAI 兼容 LLM 配置 |
| `AIROBOT_EMBEDDING_BASE_URL` / `AIROBOT_EMBEDDING_API_KEY` / `AIROBOT_EMBEDDING_MODEL` | Embedding 服务配置 |
| `AIROBOT_ADMIN_TOKEN` | 管理员令牌；留空时无管理员入口，但已配置网关令牌的账户仍可聊天；两个入站令牌均为空才返回 503 |
| `AIROBOT_AI_INTERNAL_TOKEN` | 校验 Go 网关入站身份；留空则网关流量不被信任 |
| `AIROBOT_GO_API_BASE_URL` / `AIROBOT_GO_INTERNAL_TOKEN` / `AIROBOT_GO_API_TIMEOUT` | Go 文章服务地址、出站令牌与超时（默认 5 秒） |
| `AIROBOT_AMQP_URL` / `AIROBOT_AMQP_EXCHANGE` / `AIROBOT_AMQP_QUEUE` / `AIROBOT_AMQP_ROUTING_KEY` / `AIROBOT_AMQP_PREFETCH` | RabbitMQ 连接与订阅拓扑；URL 留空则不启动消费者，prefetch 默认 5 |
| `AIROBOT_AMQP_MAX_RETRIES` / `AIROBOT_AMQP_RETRY_BACKOFF_SECONDS` / `AIROBOT_AMQP_RETRY_MAX_BACKOFF_SECONDS` | 单篇失败处理次数上限（默认 5，含首次），退避起始 2 秒、封顶 30 秒 |
| `AIROBOT_INGEST_STATE_DB` / `AIROBOT_KNOWLEDGE_STATE_DB` | 文章状态库与分块原文库路径，默认位于 `data/` |
| `AIROBOT_AGENT_MAX_TOOL_ROUNDS` | 单次 Agent Run 的最大工具调用轮次，默认 4；每轮可包含多个工具 |
| `AIROBOT_TOP_K` / `AIROBOT_CHUNK_SIZE` / `AIROBOT_CHUNK_OVERLAP` | 最终召回默认 5 块，递归分块默认 400 字符、重叠 80；Markdown 先按标题切分 |
| `AIROBOT_HYBRID_*` / `AIROBOT_RERANK_*` | 混合检索和重排开关、参数 |
| `AIROBOT_RATELIMIT_*` / `AIROBOT_CACHE_*` | 限流和语义缓存配置 |
| `AIROBOT_MEMORY_MAX_TURNS` / `AIROBOT_MEMORY_RETRIEVE_TURNS` | 进程内会话默认保存最近 20 轮，生成时读取最近 6 轮 |
| `AIROBOT_VECTOR_STORE` / `AIROBOT_MILVUS_*` | 向量库后端与 Milvus 连接参数 |
| `AIROBOT_MAX_UPLOAD_BYTES` / `AIROBOT_MAX_REQUEST_BYTES` | 上传文件上限（默认 10 MiB）与 JSON 请求体上限（默认 256 KiB） |
| `AIROBOT_RETRY_ATTEMPTS` / `AIROBOT_RETRY_MAX_WAIT` | 最多尝试次数（默认 3，含首次）与最大退避（默认 8 秒） |

完整变量见 [`.env.example`](.env.example) 和 [`app/config.py`](app/config.py)；鉴权、限流、恢复与部署行为以本 README 对应章节和源码为准。

## 项目结构

```text
app/
  agents/       LangGraph 状态图与 Go 社区工具
  rag/          文档解析、向量/BM25 检索、RRF、重排与 RAG
  services/     对话、记忆、语义缓存、限流、重试、鉴权、追踪、Go 客户端与 MQ 消费者
  static/       Go 文章社区助手 Dashboard
  config.py     全部配置项与环境变量
  main.py       路由、生命周期与中间件装配
data/           示例 Go 社区知识库与 SQLite 状态库
eval/           评测集、RAGAS 评测与离线 Agent 路径评测
scripts/        入库、检索/分块基准与评测集合清理脚本
tests/          稳定性、集成、Agent、追踪与加固回归测试
```

## 常见问题

**未配置 API Key 能启动吗？** 首次空库可能带示例导入警告启动，但不能保证知识检索可用；已有分块的索引恢复需要可用 Embedding 服务，失败会阻止启动。身份校验通过后，缺少 LLM Key 的聊天请求返回配置提示。使用本地 Ollama 时两个 Key 都填 `ollama`，并确保对应模型已经下载。

**为什么所有 `/api/*` 都返回 503？** 说明 `AIROBOT_ADMIN_TOKEN` 与 `AIROBOT_AI_INTERNAL_TOKEN` 都为空，服务没有可用的身份凭据，因此按默认拒绝处理。设置管理员令牌后重启即可。

**如何确认 Go 联合部署的令牌对不对？** Go 侧只配置一个 `AI_INTERNAL_TOKEN`；本服务的 `AIROBOT_AI_INTERNAL_TOKEN` 与 `AIROBOT_GO_INTERNAL_TOKEN` 填同一个值（即 Go 侧那个），再另外设置一个不同的 `AIROBOT_ADMIN_TOKEN`。启动时若管理员令牌与网关令牌相同会直接报错。

**同一 `session_id` 请求返回 409？** 该会话正在处理上一条消息。服务拒绝同会话并发，避免多轮上下文交叉；等待完成或换一个会话编号。

**未安装 RAGAS 或重排模型怎么办？** 普通聊天不依赖 RAGAS；运行评测时需安装评测依赖，或显式传 `--no-ragas`。重排模型不可用时保留原排序。LangGraph 是核心依赖，会随 `requirements.txt` 安装。

**重排模型下载慢怎么办？** 可设置 `AIROBOT_RERANK_ENABLED=false` 关闭重排；系统会自动保留混合检索结果。

**`/health` 里 `ingest_failed_events` 大于 0 怎么办？** 先排查 Go、Embedding、向量库和 MQ 日志。已保存正文的文章可通过重启恢复重试；仅有失败记录、没有正文的文章需重新投递发布事件，单纯重启不会重新抓取。失败记录保存在 `AIROBOT_INGEST_STATE_DB` 指向的 SQLite 中。

**修改知识文件或执行 CLI 后，为什么聊天仍用旧资料？** 启动只在知识库为空时导入示例文件，不扫描目录或替换旧分块。CLI 默认使用隔离基准库，生产离线维护须加 `--production` 并在停服时执行；在线新增资料使用 HTTP 上传。已有资料的替换需按[知识库与持久化](#知识库与持久化)重建。

## 相关文档

- [`AUDIT.md`](AUDIT.md)：代码审计与修复记录——发现的问题、修改前后对比、修法与遗留限制。
- [`REVIEW.md`](REVIEW.md)：各轮改造范围与验收结论。
- [`.env.example`](.env.example)：全部环境变量的取值与注释。

## License

MIT
