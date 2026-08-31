# Go 文章社区助手（FastAPI + LangChain RAG + CrewAI 多 Agent）

这是一个面向 **Go 技术文章社区** 的 AI 助手服务。它帮助用户理解 Go 技术文章、发布规范、代码示例与社区讨论规则，并提供文章状态查询、多轮对话与 SSE 流式回答。

服务由 FastAPI、LangChain RAG 和可选的 CrewAI 多智能体构建，内置混合检索、重试、限流、语义缓存、链路追踪和评测集。

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688)
![License](https://img.shields.io/badge/License-MIT-green)

## 目录

- [核心能力](#核心能力)
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
| 社区对话 | 意图路由（`knowledge/article/chat`）、RAG 问答、文章查询与多轮记忆 | `POST /api/v1/chat` |
| 流式对话 | SSE 逐 token 推送；缓存或文章查询会整段快速返回 | `POST /api/v1/chat/stream` |
| 多智能体 | CrewAI：意图识别官 → 社区助手；不可用时自动降级 | `app/agents/crew.py` |
| Go 知识库 | 自动导入 Go 社区示例库；支持 PDF、DOCX、Markdown、TXT 上传 | `POST /api/v1/ingest` |
| 文章工具 | Mock 文章状态/互动数据查询；生产环境可接入文章服务 | `app/agents/tools.py` |
| 可观测性 | 实时控制台、请求追踪、缓存与限流指标 | `/dashboard`、`/api/v1/traces`、`/api/v1/stats` |

## 技术栈

| 层 | 组件 | 作用 |
|---|---|---|
| 服务框架 | FastAPI + Uvicorn + Pydantic | 异步 API、OpenAPI 文档、SSE |
| LLM 编排 | LangChain LCEL | 意图路由、提示词、流式生成 |
| 多智能体 | CrewAI | 可选的 Agent、Task、Crew 顺序编排 |
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
  ├─ CrewAI：意图识别官 → 社区助手
  │      ├─ search_knowledge：Go 社区知识库 RAG
  │      ├─ query_article：文章状态查询（Mock）
  │      └─ community_guideline：发布与讨论规范
  │
  └─ 降级：LangChain 意图路由
         knowledge → 混合检索（向量 + BM25 → RRF → 重排）→ RAG 回答
         article   → 文章查询工具
         chat      → 社区助手闲聊
```

`knowledge` 用于 Go 技术、发文、Markdown、版权、评论与示例质量等问题；`article` 用于查询指定文章的状态或互动数据；`chat` 用于普通交流。

**非流式时序**：客户端请求依次经过限流、首轮缓存检查、意图识别和对应的 RAG/文章工具/闲聊分支；完成后写入会话记忆、必要时写入语义缓存，并记录链路追踪数据。响应统一包含 `reply`、`intent`、`sources`、`engine` 与 `cache_hit`。

## 功能详解

### 对话与多智能体

- **意图路由**：LLM 将消息归类为 `knowledge`（Go 技术与社区知识）、`article`（指定文章查询）或 `chat`（普通交流）。解析异常会兜底到 `chat`，避免中断服务。
- **双 Agent 协作**：CrewAI 使用“意图识别官 → 社区助手”的顺序编排。社区助手可调用 `search_knowledge`、`query_article`、`community_guideline` 三个工具；未安装或调用 CrewAI 失败时，自动降级到等价的 LangChain 路由。
- **多轮会话**：按 `session_id` 隔离会话，保留最近 `AIROBOT_MEMORY_MAX_TURNS` 轮，并在生成时带入最近 `AIROBOT_MEMORY_RETRIEVE_TURNS` 轮。
- **双通道输出**：同步 JSON 与 SSE 流式接口共用路由逻辑。SSE 会依次发送限流、缓存、意图、检索或工具、生成、写入等阶段事件。

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
| 语义缓存 | 首轮无上下文问题通过余弦相似度和词面重叠双门限复用答案；动态文章数据不缓存 | `AIROBOT_CACHE_*` |
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

# 可选：CrewAI 多智能体和 bge-reranker
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
```

### 3. 启动

```bash
uvicorn app.main:app --reload --port 8000
```

启动时会自动导入 [Go 社区示例知识库](data/knowledge_base.md)。打开 `http://localhost:8000/dashboard` 可查看控制台；交互式 API 文档在 `http://localhost:8000/docs`。

### 4. 验证

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/api/v1/stats

$body = @{ message = "Go 并发示例需要说明哪些内容？"; session_id = "go-reader-001" } | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:8000/api/v1/chat -Method Post -Body $body -ContentType "application/json"
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
  "intent": "knowledge",
  "sources": ["knowledge_base.md#7"],
  "engine": "langchain",
  "used_crew": false,
  "cache_hit": false
}
```

| 字段 | 说明 |
|---|---|
| `message` | 用户的 Go 技术或社区问题 |
| `session_id` | 可选；会话标识，默认 `default`，同一 ID 保留多轮上下文 |
| `reply` | 社区助手回答 |
| `intent` | `knowledge`（知识库问答）、`article`（文章查询）、`chat`（普通交流）或 `crew`（多智能体） |
| `sources` | RAG 来源列表（`文件#分块号`）；非知识库问答为空 |
| `engine` | `langchain`（内置路由）或 `crew`（多智能体） |
| `used_crew` / `cache_hit` | 是否走 CrewAI / 是否命中语义缓存 |

错误响应：`429` 表示请求过于频繁；未处理异常统一返回 `500`，避免向调用端暴露内部堆栈。

文章查询示例：

```json
{"message":"查询文章 20260831 的状态","session_id":"go-reader-001"}
```

会返回 Mock 文章的发布状态、标签、阅读数和评论数。生产环境可将 `query_article` 改为调用真实 article-server。

### `POST /api/v1/chat/stream`

请求体与 `/api/v1/chat` 相同，响应为 `text/event-stream`。事件顺序为：

```text
stage（限流 / 缓存 / 意图 / 检索或工具 / 生成 / 写入）
→ intent
→ token*
→ done
```

`intent=article` 时会发送 `tool=query_article` 的 `stage` 事件和一个完整回答 token；`intent=knowledge` 时会发送检索来源和逐 token 的 RAG 回答。缓存只复用无上下文的首轮非动态问答。

典型事件如下：

```text
data: {"type":"stage","stage":"rate_limit","msg":"限流检查通过"}
data: {"type":"stage","stage":"cache","msg":"语义缓存未命中"}
data: {"type":"intent","intent":"knowledge"}
data: {"type":"stage","stage":"retrieval","sources":["knowledge_base.md#7"]}
data: {"type":"token","content":"并发示例需说明..."}
data: {"type":"done","intent":"knowledge","sources":["knowledge_base.md#7"]}
```

### `POST /api/v1/ingest`

上传资料到知识库，使用 multipart 表单字段 `file`，支持 `.pdf`、`.docx`、`.md`、`.txt`、`.markdown`。

```bash
curl -X POST http://localhost:8000/api/v1/ingest -F "file=@data/knowledge_base.md"
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

- **为什么保留 CrewAI 与内置路由两条路径？** 多智能体提升工具编排表现，但框架缺失或运行出错时仍需以等价路由保障服务可用。
- **为什么使用混合检索？** Go 模块路径、包名、版本和 API 名称需要精确词面命中；语义检索则更适合概念性问题，两者融合更稳健。
- **为什么只缓存首轮非动态问题？** 这样既避免会话上下文错配，也不会将文章阅读、评论等会变化的数据长期复用。
- **如何接入真实文章服务？** 将 `query_article` 替换为对 article-server 的 HTTP 调用，增加超时、重试、鉴权与降级；现有 API 和对话编排无需改变。

## 环境变量说明

| 变量 | 说明 |
|---|---|
| `AIROBOT_LLM_BASE_URL` / `API_KEY` / `MODEL` | OpenAI 兼容 LLM 配置 |
| `AIROBOT_EMBEDDING_BASE_URL` / `API_KEY` / `MODEL` | Embedding 服务配置 |
| `AIROBOT_USE_CREW` | 是否优先使用 CrewAI，多智能体不可用时自动降级 |
| `AIROBOT_TOP_K` / `CHUNK_SIZE` / `CHUNK_OVERLAP` | 召回与分块参数 |
| `AIROBOT_HYBRID_*` / `AIROBOT_RERANK_*` | 混合检索和重排开关、参数 |
| `AIROBOT_RATELIMIT_*` / `AIROBOT_CACHE_*` | 限流和语义缓存配置 |
| `AIROBOT_MEMORY_*` | 会话记忆保留与检索轮次 |
| `AIROBOT_VECTOR_STORE` / `AIROBOT_MILVUS_*` | 向量库后端与 Milvus 连接参数 |

## 常见问题

**未配置 API Key 能启动吗？** 可以。健康检查、文档解析和检索相关能力可启动；对话接口会提示缺少 `AIROBOT_LLM_API_KEY`。本地可用 Ollama 跑通完整链路。

**未安装 CrewAI、RAGAS 或重排模型怎么办？** 服务会分别降级到内置路由、跳过评测或保留 RRF 排序；核心问答不受影响。

**重排模型下载慢怎么办？** 可设置 `AIROBOT_RERANK_ENABLED=false` 关闭重排；系统会自动保留混合检索结果。

## 项目结构

```text
app/
  agents/       多智能体角色与 Go 社区工具
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
