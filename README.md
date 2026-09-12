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
| 运行状态 | 每次请求拥有 `run_id`、工具步骤、来源与可观测轨迹 | `GET /api/v1/traces` |
| Go 知识库 | 社区文章经 RabbitMQ 事件**自动入库**；也支持 PDF、DOCX、Markdown、TXT 手动上传 | `POST /api/v1/ingest` |
| 文章工具 | 查询文章**真实数据**（标题/作者/标签/点赞/评论，来自 Go 文章服务） | `app/agents/tools.py` |
| 可观测性 | 实时控制台、请求追踪、缓存与限流指标 | `/dashboard`、`/api/v1/traces`、`/api/v1/stats` |

## 与 Go 文章社区集成

本服务已与 Go 文章社区后端（仓库 `Tfei-zhu/csdn_article_go`）完成服务级集成——**AI 的知识来源就是社区里的真实文章，文章查询工具读的也是真实数据**。整条链路分三步：

```text
① 自动学习：Go 发布文章 → RabbitMQ 发出事件
   → 本服务的消费者收到 → 调 Go 内部接口拿全文
   → 切块、向量化 → 存入知识库（下次提问即可命中）

② 真实查询：用户问「文章 12 的数据」
   → query_article 工具 → 调 Go 内部接口 → 返回真实的标题/作者/标签/点赞/评论

③ 网关代理：网页端的所有 AI 请求都先经过 Go 网关
   → Go 校验登录态和限流 → 转发本服务 → SSE 逐字流回网页
```

**涉及本仓库的改动：**

| 文件 | 作用 |
|---|---|
| `app/services/article_consumer.py` | RabbitMQ 消费者：订阅文章发布事件并自动入库；断线自动重连、重复投递去重、坏消息 ack 丢弃不堵队列、可恢复失败有限次退避重投 |
| `app/services/go_client.py` | Go 服务客户端：查文章详情（异步 + 同步双通道），网络错误自动重试，404 友好提示 |
| `app/agents/tools.py` | `query_article` 从 Mock 升级为真实数据（保留原有中文回答风格）；新增异步版供流式接口使用 |
| `app/rag/retriever.py` | 新增文章入库方法（元数据带 `article_id`，可追溯到具体文章） |
| `app/rag/lexical.py` | 修复 BM25 词面索引的增量更新缺陷（多次入库后检索错位的问题） |
| `app/main.py` | 应用启动时拉起消费者、关闭时释放资源；网关流量按账号限流 |
| `tests/test_integration.py` | 集成测试：Go 客户端、消费者去重与恢复、BM25 增量对齐等 12 项 |

**启用方式：** 在 `.env` 中设置 `AIROBOT_GO_API_BASE_URL`（指向 Go 服务）与 `AIROBOT_AMQP_URL`（指向 RabbitMQ）。凭据是「一个共享密钥 + 一个独立管理密钥」：

| 变量 | 方向 | 取值 |
|---|---|---|
| `AIROBOT_GO_INTERNAL_TOKEN` | 出站：本服务调用 Go `/internal/ai` 时携带 | 必须等于 Go 侧的 `AI_INTERNAL_TOKEN` |
| `AIROBOT_AI_INTERNAL_TOKEN` | 入站：校验 Go 网关透传的 `X-Internal-Token` | 必须等于 Go 侧的 `AI_INTERNAL_TOKEN`（与上一行同值） |
| `AIROBOT_ADMIN_TOKEN` | 管理员凭据 | 独立随机长字符串，**必须与上面两个不同** |

Go 侧只用一个 `AI_INTERNAL_TOKEN` 同时承担收发两端（既校验入站请求，也签发出站请求），所以本服务必须把同一个值填进两个变量。管理员令牌与网关令牌相同时服务会在启动阶段直接报错退出，避免网关流量等价于管理员权限。不配置 Go 集成则本服务独立运行，所有功能照常（文章工具返回降级提示）。详见 `.env.example` 中「Go 文章服务集成」一节。

## 技术栈

| 层 | 组件 | 作用 |
|---|---|---|
| 服务框架 | FastAPI + Uvicorn + Pydantic | 异步 API、OpenAPI 文档、SSE |
| LLM 编排 | LangGraph + LangChain | 状态图、工具调用循环、提示词与流式状态更新 |
| Agent 工具 | LangChain Tools | 知识检索、文章查询、社区规范（全部只读） |
| 检索 | InMemoryVectorStore / Milvus、jieba、BM25、RRF | 向量、词面召回与融合 |
| 重排 | sentence-transformers `bge-reranker-base` | 候选内容相关性重排 |
| 稳定性 | tenacity、进程内滑动窗口限流、语义缓存 | 指数退避重试、限流与首轮答案复用 |
| 持久化 | SQLite（WAL）、RabbitMQ（aio-pika） | 分块原文与文章状态、发布事件订阅 |
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
              ├─ search_knowledge → 混合检索（向量 + BM25 → RRF → 重排）→ RAG
              ├─ query_article → Go 文章服务实时数据
              └─ community_guideline → 发布与讨论规范
```

RAG 被收敛为 `search_knowledge` 工具；Agent 会根据目标自主选择一个或多个只读工具。写入型操作暂不开放，后续必须增加用户确认节点。

**接口时序**：JSON 与 SSE 共用同一张 LangGraph 图。请求经过鉴权、限流、首轮缓存检查、Agent 规划、工具循环、结果整合与记忆写入；响应包含 `run_id`、`steps`、`sources`、`engine`、`cache_hit` 与 `session_id`。

## 功能详解

### 对话与 Agent

- **状态图编排**：LangGraph 按“规划 → 工具调用 → 重新规划 / 最终答复”运行，且用 `AIROBOT_AGENT_MAX_TOOL_ROUNDS` 限制工具调用轮次。
- **受限工具**：`search_knowledge`、`query_article` 与 `community_guideline` 均为只读工具，结果会连同来源回填到状态图和客户端。
- **多轮会话**：按 `session_id` 隔离会话，保留最近 `AIROBOT_MEMORY_MAX_TURNS` 轮，并在生成时带入最近 `AIROBOT_MEMORY_RETRIEVE_TURNS` 轮。
- **双通道输出**：同步 JSON 与 SSE 流式接口共用 Agent 图。SSE 会发送 `plan`、`tool_call`、`tool_result`、`token` 与 `done` 事件。

### Go 知识库与检索

- **文档解析**：支持 PDF、Word、Markdown 与纯文本；Markdown 会按 H1-H4 标题优先分块，超长内容再递归切分。
- **混合检索**：向量检索与 jieba + BM25 词面检索并行召回，再使用 RRF 融合；Go 包名、模块路径、版本号与精确 API 名称可从词面检索获益。
- **语义重排**：可选 `BAAI/bge-reranker-base` 对候选片段重排；模型不可用时自动保留融合排序。
- **受约束生成**：RAG 提示词要求助手仅依据资料回答；资料没有的信息要明确说明未知，不能编造。

### 稳定性与可观测性

| 组件 | 机制 | 相关配置 |
|---|---|---|
| 重试 | tenacity 指数退避；仅重试 429、5xx、网络和超时等可恢复错误 | `AIROBOT_RETRY_ATTEMPTS`、`AIROBOT_RETRY_MAX_WAIT` |
| 限流 | 进程内滑动窗口，按认证身份计数（Go 网关流量按账号，其余按客户端 IP）；监控接口豁免 | `AIROBOT_RATELIMIT_PER_MINUTE` |
| 答案缓存 | 同一认证身份、语义相近的问题、相同知识库版本的首轮纯知识回答可复用；动态文章与失败结果不缓存 | `AIROBOT_CACHE_*` |
| 入库重投 | 可恢复失败有限次指数退避重投，超限登记失败表并停止重投 | `AIROBOT_AMQP_MAX_RETRIES`、`AIROBOT_AMQP_RETRY_*` |
| 链路追踪 | 记录缓存、意图、检索、首 token、生成与总耗时，聚合 P95 与命中率 | `/api/v1/traces` |

## 快速开始

### 0. 一键启动（Windows）

```powershell
.\start.ps1        # 或直接双击 start.bat
```

脚本会检查 `.env`、创建虚拟环境、安装核心依赖、检查 Ollama 模型、启动服务并打开 Dashboard。停止服务使用 `.\stop.ps1`。

### 1. 安装依赖

```bash
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# 可选：bge-reranker
pip install -r requirements-extra.txt

# 可选：RAGAS 评测
pip install -r requirements-eval.txt
```

### 2. 配置模型

复制 `.env.example` 为 `.env`，填写一个 OpenAI 兼容的 LLM 和 Embedding 服务。本地 Ollama 示例：

```ini
AIROBOT_LLM_BASE_URL=http://localhost:11434/v1
AIROBOT_LLM_API_KEY=ollama
AIROBOT_LLM_MODEL=qwen2.5:7b
AIROBOT_EMBEDDING_BASE_URL=http://localhost:11434/v1
AIROBOT_EMBEDDING_API_KEY=ollama
AIROBOT_EMBEDDING_MODEL=nomic-embed-text
# 管理员令牌：必须设置，否则所有 /api/* 返回 503；请用随机长字符串
AIROBOT_ADMIN_TOKEN=请替换为独立随机长令牌
```

模型和令牌都留空时服务仍可启动（健康检查、文档解析、检索可用），但对话接口会提示缺少 `AIROBOT_LLM_API_KEY`，`/api/*` 会因未配置访问凭据返回 `503`。

### 3. 启动

```bash
uvicorn app.main:app --reload --port 8000
```

启动时会自动导入 [Go 社区示例知识库](data/knowledge_base.md)。打开 `http://localhost:8000/dashboard` 可查看控制台；交互式 API 文档在 `http://localhost:8000/docs`。

### 4. 验证

```powershell
Invoke-RestMethod http://localhost:8000/health
$headers = @{ Authorization = "Bearer $env:AIROBOT_ADMIN_TOKEN" }
Invoke-RestMethod http://localhost:8000/api/v1/stats -Headers $headers

$body = @{ message = "Go 并发示例需要说明哪些内容？"; session_id = "go-reader-001" } | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:8000/api/v1/chat -Headers $headers -Method Post -Body $body -ContentType "application/json"
```

## 接口说明

所有 `/api/*` 接口默认拒绝匿名访问，按凭据区分权限：

| 接口 | 需要的凭据 |
|---|---|
| `GET /health` | 公开 |
| `GET /dashboard` | 公开（仅页面外壳，数据来自下列受保护接口） |
| `POST /api/v1/chat`、`/api/v1/chat/stream` | 管理员 Bearer，**或** Go 网关内部令牌 + `X-Account-Id` |
| `POST /api/v1/ingest` | 仅管理员 Bearer |
| `GET /api/v1/stats`、`/api/v1/traces` | 仅管理员 Bearer |
| 其他 `/api/*` 路径 | 默认拒绝（匿名 401，非管理员身份 403） |

### `GET /health`

健康检查，返回当前模型配置与入库失败计数。

```json
{
  "status": "ok",
  "llm_model": "qwen2.5:7b",
  "embedding_model": "nomic-embed-text",
  "engine": "langgraph",
  "ingest_failed_events": 0
}
```

`ingest_failed_events > 0` 表示已有文章连续重投失败并停止重试，需要人工排查或重启重放（详见[知识库与持久化](#知识库与持久化)）。

### `POST /api/v1/chat`

社区助手对话。请求：

```json
{
  "message": "Go 并发示例需要说明哪些内容？",
  "session_id": "go-reader-001"
}
```

示例响应：

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
| `intent` | 固定为 `agent`，表示由 LangGraph Agent 完成 |
| `sources` | Agent 工具收集的来源列表（去重并保持召回顺序） |
| `engine` | 固定为 `langgraph` |
| `run_id` / `steps` | 本次运行标识和规划、工具调用轨迹 |
| `cache_hit` | 是否命中语义缓存；命中时 `steps` 只含一条 `cache` 记录 |

文章查询示例：

```json
{"message":"查询文章 12 的数据","session_id":"go-reader-001"}
```

`query_article` 只识别带「文章 / article」前缀的数字编号（如「文章 12」「article #3」），避免把普通数字误判成文章 ID。通过 Go 文章服务返回真实详情；服务未配置或查询失败时明确提示不可用。

### `POST /api/v1/chat/stream`

请求体与 `/api/v1/chat` 相同，响应为 `text/event-stream`。事件顺序为：

```text
stage（限流 / 缓存 / 意图 / 工具 / 检索 / 生成 / 写入）
→ intent
→ token*
→ done（含 session_id）
```

意图统一为 `agent`。工具执行后发送结构化步骤，知识检索另发 `stage=retrieval`（含来源和耗时）。最终生成节点实时转发模型 token，不转发规划文本或工具参数。缓存命中仍整段返回，并写入会话记忆。执行失败时先发 `error` 再发 `done`。

典型事件如下：

```text
data: {"type":"stage","stage":"rate_limit","msg":"限流检查通过，请求进入 Agent"}
data: {"type":"stage","stage":"cache","msg":"语义缓存未命中"}
data: {"type":"intent","intent":"agent"}
data: {"type":"stage","stage":"retrieval","sources":["knowledge_base.md#7"]}
data: {"type":"token","content":"并发示例需说明..."}
data: {"type":"stage","stage":"write","msg":"写入会话记忆与执行轨迹"}
data: {"type":"done","intent":"agent","sources":["knowledge_base.md#7"],"session_id":"go-reader-001"}
```

### `POST /api/v1/ingest`

上传资料到知识库，使用 multipart 表单字段 `file`，支持 `.pdf`、`.docx`、`.md`、`.txt`、`.markdown`。

```bash
curl -X POST http://localhost:8000/api/v1/ingest -H "Authorization: Bearer $AIROBOT_ADMIN_TOKEN" -F "file=@data/knowledge_base.md"
```

### `GET /api/v1/stats` 与 `GET /api/v1/traces`

分别返回知识库分块、混合检索开关、缓存、限流等运行指标，以及最近请求的阶段耗时和聚合延迟数据。`/dashboard` 使用这两个接口展示实时监控。

`GET /dashboard` 返回自包含的可视化控制台；监控接口不参与业务限流，但需要管理员凭据。

### 错误码

| 状态码 | 含义 |
|---|---|
| `400` | 参数非法：文件类型不支持、上传为空、`Content-Length` 无效 |
| `401` | 未提供或提供了错误的身份凭据 |
| `403` | 身份有效但无权访问该接口（网关身份只能调用两个聊天接口） |
| `409` | 同一会话正在处理上一条消息，并发请求被拒绝 |
| `413` | 请求体或上传文件超过上限 |
| `429` | 触发限流，请稍后再试 |
| `500` | 未处理异常，统一返回固定文案，不暴露内部堆栈 |
| `503` | 服务尚未配置任何访问凭据（`AIROBOT_ADMIN_TOKEN` 与 `AIROBOT_AI_INTERNAL_TOKEN` 均为空） |

## 认证与安全

- **两类凭据**：管理员用 `Authorization: Bearer <AIROBOT_ADMIN_TOKEN>`；Go 网关用 `X-Internal-Token: <AIROBOT_AI_INTERNAL_TOKEN>` 加可信的 `X-Account-Id`（须为正整数）。内部令牌不等同于管理员：网关身份只能调用两个聊天接口，不能读取全局轨迹或上传资料。两种令牌必须不同，否则服务启动即报错。令牌请使用随机长字符串，不要提交到 Git。
- **令牌拓扑**：Go 侧只有一个 `AI_INTERNAL_TOKEN`，同时用于校验入站与签发出站请求，因此本服务的 `AIROBOT_AI_INTERNAL_TOKEN`（入站）与 `AIROBOT_GO_INTERNAL_TOKEN`（出站）必须填成同一个值，即 Go 侧的 `AI_INTERNAL_TOKEN`。
- **会话隔离**：`session_id` 只在认证身份内有效——不同用户即使传相同值也不会共享历史，内部键是 `sha256(身份) + ":" + sha256(会话号)`。省略时服务生成随机编号并在 JSON / SSE `done` 返回，后续请求须带回。同一会话同时发起第二个请求返回 `409`。
- **入口防护**：`SecurityMiddleware` 是最外层中间件，在限流、解析上传文件与业务路由之前完成身份校验；POST/PUT/PATCH 请求体会在解析前按上限拦截（上传接口按文件上限 + multipart 元数据余量，其余 JSON 接口按 `AIROBOT_MAX_REQUEST_BYTES`），无 `Content-Length` 的分块传输按实际字节数累计拦截。
- **生产部署**：跨主机访问需要 HTTPS，并在网关侧保证 `X-Account-Id` 不被客户端伪造；本服务只在内部令牌匹配后才采信该头。

## 知识库与持久化

`data/knowledge.sqlite3` 保存所有上传文件与文章的分块原文及元数据，`data/airobot_state.sqlite3` 保留 MQ 正文、入库状态与去重记录。两者都应持久挂载和备份；启动时从 SQLite 原文恢复向量与 BM25 索引，失败会明确报错。相同内容以稳定主键幂等写入，上传文件以原文件名溯源。

### 文章自动入库与失败重投

文章发布事件由 RabbitMQ 投递到本服务：

- 无法解析的坏消息记录日志后确认（ack）丢弃，避免毒消息阻塞队列。
- 抓取文章、调用 Embedding 或写入知识库失败时抛出可恢复异常，消息重新入队，并按 `AIROBOT_AMQP_RETRY_BACKOFF_SECONDS` 做指数退避（默认 2s、4s、8s…封顶 `AIROBOT_AMQP_RETRY_MAX_BACKOFF_SECONDS`，默认 30s），避免下游故障期间高速重投把 Broker 打满。
- 同一文章连续失败达到 `AIROBOT_AMQP_MAX_RETRIES`（默认 5）次后不再重投，登记到 `ingest_failures` 表并计入 `/health` 的 `ingest_failed_events`，等待人工处理或重启重放；成功后自动清除失败记录与重试计数。
- 服务启动时会重放 SQLite 中的文章，重新建立向量和 BM25 索引，因此默认的 InMemoryVectorStore 也不会因进程重启丢失文章数据。
- Docker Compose 已将 `./data` 挂载到容器 `/app/data`，请保留该目录或改用外部持久卷。

退避发生在消费者投递循环中，单条毒消息在退避期间会占用一个消费位（prefetch 内已投递的消息排队等待）。需要更高吞吐时应改为死信队列 + TTL 重试队列。

### 向量库与索引约束

SQLite 是当前默认的知识源持久化方案；Milvus 可作为向量检索后端，生产集合名来自配置，评测与基准分别使用随机 `airobot_eval_*` / `airobot_bench_*`，不共享生产集合。实例化、导入模块和服务启动均无清库副作用。

- 旧 `AIROBOT_MILVUS_RESET_ON_START` 已废弃，无论取值是什么都不会清库。
- 旧 `auto_id=true` 集合会被拒绝写入（稳定主键是幂等入库与恢复的前提）：先备份旧集合和 SQLite，再配置全新集合名，重建验证后切换；不要直接删除旧集合。旧集合独有而 SQLite 没有的资料必须先导出或重新导入。
- 评测结束会在报告中记录集合名，可用 `python scripts/reset_collection.py --collection <评测集合名> --confirm <同名>` 显式清理。此脚本拒绝生产集合，不会自动清除评测报告或数据库。
- 现阶段是**单进程、单实例索引**：请使用一个 Uvicorn worker。线程锁保护两路索引的一致读写，入库移至工作线程；BM25 仅对新增文档分词并更新倒排统计。此实现采用正值 IDF，与原 rank_bm25 的分数不完全相同，需要比较质量报告。文章更新/删除同步不属于发布事件协议，不能把发布去重当作更新支持。
- CLI 导入与运行服务不是同一进程。生产在线导入统一使用带管理员凭据的 HTTP 上传；离线维护前停服，导入后重启，以恢复两路索引。

### 评测数据集

- `data/knowledge_base.md`：发布文章、标签、Markdown、审核修订、版权引用、评论互动和 Go 示例质量规则。
- `eval/dataset/qa.jsonl`：52 条 Go 文章社区问答样本，覆盖发布、标签、Markdown、审核、版权、讨论、互动、并发示例与知识库未覆盖问题。
- `eval/run_eval.py`：RAGAS 四指标、LLM-as-Judge 与关键词命中评测。

## 可视化控制台

启动后打开 <http://localhost:8000/dashboard>，**在页面顶部填入管理员令牌**（`AIROBOT_ADMIN_TOKEN`）后才能拉取数据；令牌只保留在当前页面内存中，不会落盘。控制台不依赖外部 CDN，提供：

- 用户模拟对话：支持流式回答、切换 `session_id` 和 Go 社区快捷问题；
- 全链路可视化：实时显示限流、缓存、意图、混合检索、工具调用、生成与记忆写入；
- 状态卡片：服务健康、模型、知识库分块、缓存命中率、P95、限流拦截与请求总数；
- 实时监控：最近请求的阶段耗时、状态码与延迟趋势，每 3 秒刷新一次。

数据来自 `GET /api/v1/stats` 和 `GET /api/v1/traces`。

## Docker 部署

本地 Ollama 模式：

```bash
docker compose up -d --build
docker compose logs -f airobot
```

- compose 内置 `ollama` 服务，首次启动会自动拉取与 `.env` 匹配的模型；
- 容器内的 LLM 与 Embedding 自动指向 `http://ollama:11434/v1`；
- `./data` 作为卷挂载，替换知识库文件后重启服务即可重新导入；
- 云端模型场景可将 `docker-compose.yml` 中的两个 `AIROBOT_*_BASE_URL` 改为供应商地址，并在 `.env` 填写密钥；
- 需要 Milvus 时另起 `docker compose -f docker-compose-milvus.yml up -d`，并安装 `langchain-milvus`（含在 `requirements-extra.txt` 中）。

与 Go 文章社区联合部署时，除 `./data` 外还需为知识库状态库准备独立持久卷，并在两侧填入一致的 `AI_INTERNAL_TOKEN` 和独立的管理员令牌。

## 测试与 CI

`.github/workflows/ci.yml` 在 push 与 PR 时执行三个 Job（Python 3.11）：

| Job | 内容 |
|---|---|
| `build` | 安装核心依赖 + `compileall` 语法门禁（覆盖 `app`、`eval`、`scripts`、`tests`） |
| `test` | 全量离线单测：稳定性 6 项、集成 12 项、Agent 5 项、追踪 3 项、加固 26 项，外加离线 Agent 路径评测与「服务可导入」冒烟 |
| `eval` | 配置模型 Secrets 后运行前 5 条 RAGAS + Judge 评测，门禁为 `--min-baseline-hit-rate 0.85 --min-judge-score 3.5`，报告作为 artifact 上传 |

本地运行同一套门禁：

```bash
python tests/test_stability.py
python tests/test_integration.py
python tests/test_agent.py
python tests/test_tracing.py
python -m unittest discover -s tests -p "test_hardening.py" -v
python eval/run_agent_eval.py
```

`eval/run_agent_eval.py` 运行真实 LangGraph 但替换模型与外部服务，验证**路径**而非自然语言质量：知识、文章、组合工具、工具失败、轮次上限、直接回答 6 类。真实模型评测通过 `--agent` 执行工具链并记录工具实际召回的上下文：

```bash
python eval/run_eval.py --agent --limit 5 --top-k 3 --no-ragas
python eval/run_eval.py                 # 完整 RAGAS + Judge + 关键词基线
python scripts/bench_retrieval.py --top-k 5
python scripts/bench_splitter.py --top-k 3
python scripts/ingest.py data/knowledge_base.md
```

知识工具本身不再生成答案，只返回原文；规划仍可多轮调用工具，JSON 和 SSE 共用独立的最终生成节点。因此常规单工具路径包含「首次规划、停止规划、最终生成」三次模型调用，不能把“去除工具内生成”理解为所有请求固定只调用两次。SSE 的首字时间仍包含规划和检索耗时，但不再等待最终答案生成完毕。

可使用 `Dockerfile` 与 `docker-compose.yml` 容器化部署。生产环境应为模型密钥、限流、追踪与凭据接入相应的基础设施。

## 设计决策

- **为什么使用 LangGraph 而非 CrewAI？** 本项目需要把规划、工具调用、来源和流式事件统一到同一状态图；LangGraph 直接提供该编排模型，避免 JSON 与 SSE 使用两条不同的执行路径。
- **为什么使用混合检索？** Go 模块路径、包名、版本和 API 名称需要精确词面命中；语义检索则更适合概念性问题，两者融合更稳健。
- **为什么只缓存首轮非动态问题？** 这样既避免会话上下文错配，也不会将文章阅读、评论等会变化的数据长期复用。缓存按认证身份（账户哈希）与知识库版本隔离，并要求向量余弦相似度与 jieba 词面重叠率**双门限**同时通过——词面门限是唯一的松紧旋钮（`AIROBOT_CACHE_LEXICAL_THRESHOLD`，调高更保守）。只有「全部工具调用均为成功知识检索且存在来源」的首轮回答才写缓存；若知识库在生成期间变化，本次结果不写缓存。
- **为什么保留文章查询的真实 HTTP 调用？** `query_article` 已替换为对 Go 文章服务的调用，带超时、重试、鉴权与降级；Go 服务不可用时明确提示而不是编造内容，现有 API 和对话编排无需改变。

## 环境变量说明

| 变量 | 说明 |
|---|---|
| `AIROBOT_LLM_BASE_URL` / `API_KEY` / `MODEL` | OpenAI 兼容 LLM 配置 |
| `AIROBOT_EMBEDDING_BASE_URL` / `API_KEY` / `MODEL` | Embedding 服务配置 |
| `AIROBOT_ADMIN_TOKEN` | 管理员令牌；留空则 `/api/*` 全部不可访问（返回 503） |
| `AIROBOT_AI_INTERNAL_TOKEN` | 校验 Go 网关入站身份；留空则网关流量不被信任 |
| `AIROBOT_GO_API_BASE_URL` / `GO_INTERNAL_TOKEN` / `GO_API_TIMEOUT` | Go 文章服务地址、出站令牌与超时 |
| `AIROBOT_AMQP_URL` / `_EXCHANGE` / `_QUEUE` / `_ROUTING_KEY` / `_PREFETCH` | RabbitMQ 连接与订阅拓扑；`URL` 留空则不启动消费者 |
| `AIROBOT_AMQP_MAX_RETRIES` / `_RETRY_BACKOFF_SECONDS` / `_RETRY_MAX_BACKOFF_SECONDS` | 文章入库失败的重投次数上限与指数退避 |
| `AIROBOT_INGEST_STATE_DB` / `KNOWLEDGE_STATE_DB` | 文章状态库与分块原文库路径 |
| `AIROBOT_AGENT_MAX_TOOL_ROUNDS` | 单次 Agent Run 的最大工具调用轮次 |
| `AIROBOT_TOP_K` / `CHUNK_SIZE` / `CHUNK_OVERLAP` | 召回与分块参数 |
| `AIROBOT_HYBRID_*` / `AIROBOT_RERANK_*` | 混合检索和重排开关、参数 |
| `AIROBOT_RATELIMIT_*` / `AIROBOT_CACHE_*` | 限流和语义缓存配置 |
| `AIROBOT_MEMORY_*` | 会话记忆保留与检索轮次 |
| `AIROBOT_VECTOR_STORE` / `AIROBOT_MILVUS_*` | 向量库后端与 Milvus 连接参数 |
| `AIROBOT_MAX_UPLOAD_BYTES` / `MAX_REQUEST_BYTES` | 上传文件上限（默认 10 MiB）与 JSON 请求体上限（默认 256 KiB） |
| `AIROBOT_RETRY_ATTEMPTS` / `RETRY_MAX_WAIT` | 模型调用的重试次数与最大退避 |

完整取值与注释见 [`.env.example`](.env.example)。

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

**未配置 API Key 能启动吗？** 可以。健康检查、文档解析和检索相关能力可启动；对话接口会提示缺少 `AIROBOT_LLM_API_KEY`。本地可用 Ollama 跑通完整链路。

**为什么所有 `/api/*` 都返回 503？** 说明 `AIROBOT_ADMIN_TOKEN` 与 `AIROBOT_AI_INTERNAL_TOKEN` 都为空，服务没有可用的身份凭据，因此按默认拒绝处理。设置管理员令牌后重启即可。

**如何确认 Go 联合部署的令牌对不对？** Go 侧只配置一个 `AI_INTERNAL_TOKEN`；本服务的 `AIROBOT_AI_INTERNAL_TOKEN` 与 `AIROBOT_GO_INTERNAL_TOKEN` 填同一个值（即 Go 侧那个），再另外设置一个不同的 `AIROBOT_ADMIN_TOKEN`。启动时若管理员令牌与网关令牌相同会直接报错。

**同一 `session_id` 请求返回 409？** 该会话正在处理上一条消息。服务拒绝同会话并发，避免多轮上下文交叉；等待完成或换一个会话编号。

**未安装 RAGAS 或重排模型怎么办？** 服务会跳过评测或保留 RRF 排序；LangGraph Agent 是核心依赖，会随 `requirements.txt` 一起安装。

**重排模型下载慢怎么办？** 可设置 `AIROBOT_RERANK_ENABLED=false` 关闭重排；系统会自动保留混合检索结果。

**`/health` 里 `ingest_failed_events` 大于 0 怎么办？** 表示有文章连续重投失败已被停止重试。排查 Go 服务与 RabbitMQ 后重启服务即可重放；失败记录保存在 `AIROBOT_INGEST_STATE_DB` 指向的 SQLite 中。

## 相关文档

- [`AUDIT.md`](AUDIT.md)：代码审计与修复记录——发现的问题、修改前后对比、修法与遗留限制。
- [`REVIEW.md`](REVIEW.md)：各轮改造范围与验收结论。
- [`.env.example`](.env.example)：全部环境变量的取值与注释。

## License

MIT
