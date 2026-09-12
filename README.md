# Go 文章社区 Agent（FastAPI + LangGraph + RAG）

这是一个面向 **Go 技术文章社区** 的 AI 助手服务。它帮助用户理解 Go 技术文章、发布规范、代码示例与社区讨论规则，并提供文章状态查询、多轮对话与 SSE 流式回答。

服务由 FastAPI、LangGraph Agent 和 LangChain RAG 构建。Agent 能规划并调用受限的只读工具；RAG 是其中的知识检索工具，而不是固定问答主流程。

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688)
![License](https://img.shields.io/badge/License-MIT-green)

## 目录

- [核心能力](#核心能力)
- [与 Go 文章社区集成](#与-go-文章社区集成)
- [功能详解](#功能详解)
- [快速开始](#快速开始)
- [接口说明](#接口说明)
- [知识库与评测](#知识库与评测)
- [可视化控制台](#可视化控制台)
- [Docker 部署](#docker-部署)
- [CI 与评测](#ci-与评测)
- [设计决策](#设计决策)
- [环境变量说明](#环境变量说明)
- [项目结构](#项目结构)
- [常见问题](#常见问题)

## 核心能力

| 能力模块 | 说明 | 对应接口 |
|---|---|---|
| 社区 Agent | LangGraph 规划、工具调用循环、事实整合与多轮记忆 | `POST /api/v1/chat` |
| 流式 Agent | SSE 推送规划、工具调用、工具结果与最终答复 | `POST /api/v1/chat/stream` |
| 运行状态 | 每次请求拥有 `run_id`、工具步骤、来源与可观测轨迹 | `app/agents/graph.py` |
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
| `app/services/article_consumer.py` | RabbitMQ 消费者：订阅文章发布事件并自动入库；断线自动重连、重复投递去重、坏消息跳过不堵队列 |
| `app/services/go_client.py` | Go 服务客户端：查文章详情（异步 + 同步双通道），网络错误自动重试，404 友好提示 |
| `app/agents/tools.py` | `query_article` 从 Mock 升级为真实数据（保留原有中文回答风格）；新增异步版供流式接口使用 |
| `app/rag/retriever.py` | 新增文章入库方法（元数据带 `article_id`，可追溯到具体文章） |
| `app/rag/lexical.py` | 修复 BM25 词面索引的增量更新缺陷（多次入库后检索错位的问题） |
| `app/main.py` | 应用启动时拉起消费者、关闭时释放资源；网关流量按账号限流 |
| `tests/test_integration.py` | 集成测试：Go 客户端、消费者去重、BM25 回归等 10 项 |

**启用方式（两行配置）：** 在 `.env` 中设置 `AIROBOT_GO_API_BASE_URL`（指向 Go 服务）与 `AIROBOT_AMQP_URL`（指向 RabbitMQ），两侧共用 `AIROBOT_GO_INTERNAL_TOKEN` 口令。不配置则本服务独立运行，所有功能照常（文章工具返回降级提示）。详见 `.env.example` 中「Go 文章服务集成」一节。

## 技术栈

| 层 | 组件 | 作用 |
|---|---|---|
| 服务框架 | FastAPI + Uvicorn + Pydantic | 异步 API、OpenAPI 文档、SSE |
| LLM 编排 | LangGraph + LangChain | 状态图、工具调用循环、提示词与流式状态更新 |
| Agent 工具 | LangChain Tools | 知识检索、文章查询、社区规范（全部只读） |
| 检索 | InMemoryVectorStore / Milvus、jieba、BM25、RRF | 向量、词面召回与融合 |
| 重排 | sentence-transformers `bge-reranker-base` | 候选内容相关性重排 |
| 稳定性 | tenacity | 可恢复错误的指数退避重试 |
| 评测 | RAGAS + LLM-as-Judge | 检索增强问答的质量评估 |
| 交付 | Docker、docker compose、GitHub Actions | 容器化与持续集成 |

## 工作方式

```text
客户端
  │  POST /api/v1/chat 或 /api/v1/chat/stream
  ▼
FastAPI（限流、日志、异常处理）
  │
  │
  └─ LangGraph Agent Run（run_id）
         规划 → 受限工具调用循环（最多 N 轮）→ 事实整合 → 最终答复
              ├─ search_knowledge → 混合检索（向量 + BM25 → RRF → 重排）→ RAG
              ├─ query_article → Go 文章服务实时数据
              └─ community_guideline → 发布与讨论规范
```

RAG 被收敛为 `search_knowledge` 工具；Agent 会根据目标自主选择一个或多个只读工具。写入型操作暂不开放，后续必须增加用户确认节点。

**接口时序**：JSON 与 SSE 共用同一张 LangGraph 图。请求经过限流、首轮缓存检查、Agent 规划、工具循环、结果整合与记忆写入；响应包含 `run_id`、`steps`、`sources`、`engine` 与 `cache_hit`。

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
| 限流 | 按 IP 的进程内滑动窗口，监控接口豁免 | `AIROBOT_RATELIMIT_PER_MINUTE` |
| 答案缓存 | 同一认证身份、相同问题、相同知识版本的首轮纯知识回答可复用；动态文章与失败结果不缓存 | `AIROBOT_CACHE_*` |
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
AIROBOT_LLM_MODEL=qwen2.5:1.5b
AIROBOT_EMBEDDING_BASE_URL=http://localhost:11434/v1
AIROBOT_EMBEDDING_API_KEY=ollama
AIROBOT_EMBEDDING_MODEL=nomic-embed-text
AIROBOT_ADMIN_TOKEN=请替换为独立随机长令牌
```

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

### `GET /health`

健康检查，返回当前模型配置。

```json
{"status":"ok","llm_model":"qwen2.5:1.5b","embedding_model":"nomic-embed-text"}
```

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
  "cache_hit": false
}
```

| 字段 | 说明 |
|---|---|
| `message` | 用户的 Go 技术或社区问题 |
| `session_id` | 可选；省略时随机生成并返回，同一认证身份下的同一编号保留多轮上下文 |
| `reply` | 社区助手回答 |
| `intent` | 固定为 `agent`，表示由 LangGraph Agent 完成 |
| `sources` | Agent 工具收集的来源列表 |
| `engine` | 固定为 `langgraph` |
| `run_id` / `steps` | 本次运行标识和规划、工具调用轨迹 |
| `cache_hit` | 是否命中语义缓存 |

错误响应：`429` 表示请求过于频繁；未处理异常统一返回 `500`，避免向调用端暴露内部堆栈。

文章查询示例：

```json
{"message":"查询文章 20260831 的状态","session_id":"go-reader-001"}
```

通过 Go 文章服务返回真实详情；服务未配置或查询失败时明确提示不可用。

### `POST /api/v1/chat/stream`

请求体与 `/api/v1/chat` 相同，响应为 `text/event-stream`。事件顺序为：

```text
stage（限流 / 缓存 / 意图 / 检索或工具 / 生成 / 写入）
→ intent
→ token*
→ done
```

意图统一为 `agent`。工具执行后发送结构化步骤，知识检索另发 `stage=retrieval`（含来源和耗时）。最终生成节点实时转发模型 token，不转发规划文本或工具参数。缓存命中仍整段返回，并写入会话记忆。

典型事件如下：

```text
data: {"type":"stage","stage":"rate_limit","msg":"限流检查通过"}
data: {"type":"stage","stage":"cache","msg":"语义缓存未命中"}
data: {"type":"intent","intent":"agent"}
data: {"type":"stage","stage":"retrieval","sources":["knowledge_base.md#7"]}
data: {"type":"token","content":"并发示例需说明..."}
data: {"type":"done","intent":"agent","sources":["knowledge_base.md#7"]}
```

### `POST /api/v1/ingest`

上传资料到知识库，使用 multipart 表单字段 `file`，支持 `.pdf`、`.docx`、`.md`、`.txt`、`.markdown`。

```bash
curl -X POST http://localhost:8000/api/v1/ingest -H "Authorization: Bearer $AIROBOT_ADMIN_TOKEN" -F "file=@data/knowledge_base.md"
```

### `GET /api/v1/stats` 与 `GET /api/v1/traces`

分别返回知识库分块、缓存、限流等运行指标，以及最近请求的阶段耗时和聚合延迟数据。`/dashboard` 使用这两个接口展示实时监控。

`GET /dashboard` 返回自包含的可视化控制台；监控接口不参与业务限流。

## 知识库与评测

- `data/knowledge_base.md`：发布文章、标签、Markdown、审核修订、版权引用、评论互动和 Go 示例质量规则。
- `eval/dataset/qa.jsonl`：52 条 Go 文章社区问答样本，覆盖知识库未覆盖场景。
- `eval/run_eval.py`：RAGAS 四指标、LLM-as-Judge 与关键词命中评测。

## 可视化控制台

启动后打开 <http://localhost:8000/dashboard>。控制台不依赖外部 CDN，提供：

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
- 云端模型场景可将 `docker-compose.yml` 中的两个 `AIROBOT_*_BASE_URL` 改为供应商地址，并在 `.env` 填写密钥。

## CI 与评测

`.github/workflows/ci.yml` 在 push 与 PR 时执行：

| Job | 内容 |
|---|---|
| `build` | 安装依赖与语法检查 |
| `test` | 稳定性离线测试与服务导入冒烟 |
| `eval` | 配置模型 Secrets 后运行前 5 条 RAGAS 冒烟评测 |

完整评测与检索实验：

```bash
python eval/run_eval.py
python scripts/bench_retrieval.py --top-k 5
python scripts/bench_splitter.py --top-k 3
python scripts/ingest.py data/knowledge_base.md
```

评测集包含 52 条 Go 文章社区问答，覆盖发布、标签、Markdown、审核、版权、讨论、互动、并发示例与知识库未覆盖问题。

## 设计决策

- **为什么使用 LangGraph 而非 CrewAI？** 本项目需要把规划、工具调用、来源和流式事件统一到同一状态图；LangGraph 直接提供该编排模型，避免 JSON 与 SSE 使用两条不同的执行路径。
- **为什么使用混合检索？** Go 模块路径、包名、版本和 API 名称需要精确词面命中；语义检索则更适合概念性问题，两者融合更稳健。
- **为什么只缓存首轮非动态问题？** 这样既避免会话上下文错配，也不会将文章阅读、评论等会变化的数据长期复用。
- **如何接入真实文章服务？** 将 `query_article` 替换为对 article-server 的 HTTP 调用，增加超时、重试、鉴权与降级；现有 API 和对话编排无需改变。

## 环境变量说明

| 变量 | 说明 |
|---|---|
| `AIROBOT_LLM_BASE_URL` / `API_KEY` / `MODEL` | OpenAI 兼容 LLM 配置 |
| `AIROBOT_EMBEDDING_BASE_URL` / `API_KEY` / `MODEL` | Embedding 服务配置 |
| `AIROBOT_AGENT_MAX_TOOL_ROUNDS` | 单次 Agent Run 的最大工具调用轮次 |
| `AIROBOT_TOP_K` / `CHUNK_SIZE` / `CHUNK_OVERLAP` | 召回与分块参数 |
| `AIROBOT_HYBRID_*` / `AIROBOT_RERANK_*` | 混合检索和重排开关、参数 |
| `AIROBOT_RATELIMIT_*` / `AIROBOT_CACHE_*` | 限流和语义缓存配置 |
| `AIROBOT_MEMORY_*` | 会话记忆保留与检索轮次 |
| `AIROBOT_VECTOR_STORE` / `AIROBOT_MILVUS_*` | 向量库后端与 Milvus 连接参数 |

## 常见问题

**未配置 API Key 能启动吗？** 可以。健康检查、文档解析和检索相关能力可启动；对话接口会提示缺少 `AIROBOT_LLM_API_KEY`。本地可用 Ollama 跑通完整链路。

**未安装 RAGAS 或重排模型怎么办？** 服务会跳过评测或保留 RRF 排序；LangGraph Agent 是核心依赖，会随 `requirements.txt` 一起安装。

**重排模型下载慢怎么办？** 可设置 `AIROBOT_RERANK_ENABLED=false` 关闭重排；系统会自动保留混合检索结果。

## 项目结构

```text
app/
  agents/       LangGraph 状态图与 Go 社区工具
  rag/          文档解析、向量/BM25 检索、RRF、重排与 RAG
  services/     对话、记忆、缓存、限流、重试与追踪
  static/       Go 文章社区助手 Dashboard
data/           示例 Go 社区知识库
eval/           评测集和评测脚本
tests/          稳定性与追踪测试
```

## 验证与部署

```bash
python tests/test_stability.py
python tests/test_tracing.py
```

可使用 `Dockerfile` 与 `docker-compose.yml` 容器化部署。生产中建议将 Mock 的文章查询替换为真实文章服务，并为模型密钥、速率限制和追踪接入相应的基础设施。

## License

MIT

## 文章入库与知识库持久化

文章发布事件由 RabbitMQ 投递到 AI-Robot：

- 无法解析的坏消息会记录日志并确认（ack）丢弃，避免毒消息阻塞队列。
- 抓取文章、调用 Embedding 或写入知识库失败时会抛出异常，消息通过 `requeue=true` 重新入队，等待后续重试。
- 成功入库的文章正文、标题、标签和状态写入 `AIROBOT_INGEST_STATE_DB` 指定的 SQLite 文件；默认是 `data/airobot_state.sqlite3`。
- 服务启动时会重放 SQLite 中的文章，重新建立向量和 BM25 索引，因此默认的 InMemoryVectorStore 也不会因进程重启丢失文章数据。
- Docker Compose 已将 `./data` 挂载到容器 `/app/data`，请保留该目录或改用外部持久卷。

SQLite 是当前默认的知识源持久化方案；Milvus 可作为向量检索后端。旧 `AIROBOT_MILVUS_RESET_ON_START` 已废弃，无论取值是什么都不会清库。

## 安全与存储升级

- API 默认拒绝匿名访问。控制台输入独立的 `AIROBOT_ADMIN_TOKEN`，仅保留在当前页面；脚本从同名环境变量读取，HTTP 使用 `Authorization: Bearer <令牌>`。令牌请使用随机长字符串，不要提交到 Git。
- Go 网关继续使用 `X-Internal-Token` + `X-Account-Id`，对应 `AIROBOT_AI_INTERNAL_TOKEN`，只能调用两个聊天接口，不能读取全局轨迹或上传资料。两种令牌必须不同。生产跨主机访问需要 HTTPS。
- `session_id` 只在认证身份内有效：不同用户即使传相同值也不会共享历史。省略时服务生成随机编号并在 JSON / SSE done 返回；后续请求须带回。仅支持字母、数字、下划线和连字符，最长 128 字符。同一会话同时发起第二个请求返回 409。
- stats/traces 需要管理员身份，保留轮询限流豁免；健康检查与不含数据的控制台外壳公开。
- `data/knowledge.sqlite3` 保存所有上传文件和文章的分块原文及元数据，`data/airobot_state.sqlite3` 保留 MQ 正文与状态。两者都应持久挂载和备份；启动从原文恢复向量和 BM25，失败会明确报错。相同内容以稳定主键幂等写入。上传文件以原文件名溯源。
- 现阶段是单进程、单实例索引：请使用一个 Uvicorn worker。线程锁保护两路索引的一致读写，入库移至工作线程；BM25 仅对新增文档分词并更新倒排统计。此实现采用正值 IDF，与原 rank_bm25 的分数不完全相同，需要比较质量报告。文章更新/删除同步不属于发布事件协议，不能把发布去重当作更新支持。
- 生产 Milvus 集合名来自配置；评测与基准分别使用随机 `airobot_eval_*` / `airobot_bench_*`，不共享生产集合。实例化、导入模块和服务启动均无清库副作用。旧自动主键集合会被拒绝写入：先备份旧集合和 SQLite，再配置全新集合名，重建验证后切换；不要直接删除旧集合。旧集合独有而 SQLite 没有的资料必须先导出或重新导入。
- 评测结束会在报告中记录集合名。可用 `python scripts/reset_collection.py --collection <评测集合名> --confirm <同名>` 显式清理。此脚本拒绝生产集合，不会自动清除评测报告或数据库。
- CLI 导入与运行服务不是同一进程。生产在线导入统一使用带管理员凭据的 HTTP 上传；离线维护前停服，导入后重启，以恢复两路索引。

## Agent 回归验证

```bash
python eval/run_agent_eval.py
python -m unittest discover -s tests -p "test_hardening.py" -v
python eval/run_eval.py --agent --limit 5 --top-k 3 --no-ragas
```

离线门禁运行真实 LangGraph，但替换模型与外部服务，验证路径而非自然语言质量。真实模型评测通过 `--agent` 执行工具链，并记录工具实际召回的上下文；CI 配置模型密钥后执行质量门禁。知识工具本身不再生成答案，只返回原文。规划仍可多轮调用工具，JSON 和 SSE 共用独立最终生成节点；常规单工具路径包含首次规划、停止规划、最终生成三次模型调用，不能把“去除工具内生成”理解为所有请求固定只调用两次。SSE 的首字时间仍包含规划和检索耗时，但不再等待最终答案生成完毕。

答案缓存保守地增加“问题完全一致”的限制，避免动态问题通过语义相似度命中静态答案。只有全部工具调用均为成功知识检索且存在来源的首轮回答可写缓存；缓存还按认证身份和索引版本隔离。若知识库在生成期间变化，本次结果不写缓存。
