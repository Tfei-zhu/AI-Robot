# AI Robot 智能客服服务（FastAPI + LangChain RAG + CrewAI 多 Agent）

一个开箱即用的**完整智能客服服务**：基于 **FastAPI + LangChain RAG + CrewAI 多 Agent** 构建，
提供意图识别路由、知识库问答、多智能体协作、SSE 流式对话等核心客服能力，并内置
检索工程（BM25+RRF+reranker）、稳定性工程（重试/限流/语义缓存）、可观测性（实时监控控制台）
与效果评估体系（RAGAS 评测闭环），可直接部署上线，也可作为独立 AI 服务被现有业务系统（如
Spring Cloud / Node.js 后端）通过 HTTP/SSE 集成调用。

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688)
![License](https://img.shields.io/badge/License-MIT-green)
[![CI](https://github.com/liubaijiangde-bot/AI-Robot-FastAPI-LangChain-RAG-CrewAI-Agent-/actions/workflows/ci.yml/badge.svg)](https://github.com/liubaijiangde-bot/AI-Robot-FastAPI-LangChain-RAG-CrewAI-Agent-/actions/workflows/ci.yml)


## 目录

- [项目定位](#项目定位)
- [核心能力总览](#核心能力总览)
- [功能详解](#功能详解)
- [技术栈](#技术栈)
- [系统架构](#系统架构)
- [快速开始（从拉取到运行）](#快速开始从拉取到运行)
- [接口文档](#接口文档)
- [可视化控制台](#可视化控制台)
- [Docker 部署](#docker-部署)
- [CI 门禁](#ci-门禁)
- [效果评测（RAGAS）](#效果评测ragas)
- [检索与分块实验](#检索与分块实验)
- [设计决策](#设计决策)
- [项目结构](#项目结构)
- [环境变量说明](#环境变量说明)
- [常见问题](#常见问题)
- [License](#license)

## 项目定位

本服务把"意图识别 → 工具/RAG 执行 → 流式答复"的客服链路做成**生产可用的完整程序**，而非玩具 Demo：

1. **多智能体编排**：CrewAI 双 Agent（意图识别官 → 客服执行员）顺序协作，多工具编排；
   未安装或调用失败时自动降级到等价的内置 LangChain 路由，保证服务可用性。
2. **RAG 检索链路**：PDF/Word/Markdown 解析 → 分块 → 向量 + BM25 双路索引 → RRF 融合 →
   bge-reranker 重排 → 检索增强生成；内置对照实验证明混合检索收益（vector 67% → hybrid 98% 命中）。
3. **工程化配套**：会话记忆、SSE 流式、tenacity 重试、滑动窗口限流、语义缓存、链路追踪、
   RAGAS 评测集、Docker 一键部署与 CI 门禁——每一层都可观测、可评估、可替换。

## 核心能力总览

| 能力模块 | 提供什么 | 对应接口 |
|---|---|---|
| 智能对话 | 意图路由（knowledge/order/chat）+ RAG 问答 + 工具调用 + 多轮记忆 | `POST /api/v1/chat` |
| 流式对话 | SSE 逐 token 输出，缓存命中整段秒回 | `POST /api/v1/chat/stream` |
| 多智能体 | CrewAI 意图识别官 → 客服执行员，失败自动降级 | `app/agents/crew.py` |
| 知识库问答 | 启动自动导入示例库，支持 PDF/DOCX/MD/TXT 上传入库 | `POST /api/v1/ingest` |
| 工具集成 | 订单查询（Mock，可对接真实系统）、售后规则 | `app/agents/tools.py` |
| 稳定性 | 重试 / 限流 / 语义缓存三重保障 | `app/services/*` |
| 可观测性 | 实时监控控制台（含用户模拟对话与全链路可视化）、请求链路追踪、运行指标 | `/dashboard`、`/api/v1/traces`、`/api/v1/stats` |
| 效果评估 | RAGAS 四指标 + LLM-as-Judge + 52 条评测集 | `eval/run_eval.py` |
| 部署交付 | Docker / docker-compose / GitHub Actions 门禁 | 仓库根目录 |

## 功能详解

### 1. 智能对话服务（app/services/chat.py）

- **意图路由**：LLM 将用户消息分类为 `knowledge`（知识问答）/ `order`（订单查询）/ `chat`（闲聊），
  分类结果 JSON 解析失败时兜底为 `chat`，保证不中断服务。
- **多轮会话记忆**：`session_id` 维度隔离（`InMemoryChatMessageHistory`），
  每个会话保留最近 `AIROBOT_MEMORY_MAX_TURNS` 轮、生成时带入最近 `AIROBOT_MEMORY_RETRIEVE_TURNS` 轮，
  支持"追问"类上下文问题。
- **双通道输出**：同步 JSON（`/api/v1/chat`）与 SSE 流式（`/api/v1/chat/stream`），
  流式按 `stage（限流/缓存/意图/检索/生成等）→ intent → token* → done` 事件推送，控制台可实时还原全链路。
- **降级链**：CrewAI 可用优先（独立线程执行）→ 异常自动降级内置 LangChain 路由 →
  未配置 API Key 时返回明确提示（服务本身不宕机）。

### 2. 多智能体编排（app/agents/crew.py）

- **双 Agent 协作**：`意图识别官`（输出意图 JSON）→ `客服执行员`（携带 3 个工具执行），
  `Process.sequential` 顺序执行，结构为 `Agent(角色/目标/背景/工具/LLM) + Task + Crew`。
- **工具集**（app/agents/tools.py，同时提供原始函数与 CrewAI `@tool` 包装）：
  - `search_knowledge`：RAG 检索增强生成（调知识库）
  - `query_order`：订单/物流查询（当前 Mock，生产通过 HTTP 对接 order-server，见"设计决策"）
  - `after_sale_rule`：售后与退货规则
- **可用性保障**：`crewai` 未安装时 `CREW_TOOLS_READY=false`，自动切换内置路由；
  运行时异常同样降级，`/api/v1/stats` 的 `crew_available` 可观测状态。

### 3. RAG 知识库（app/rag/）

- **文档解析**（loader.py）：`pypdf` 解析 PDF、`python-docx` 解析 Word、文本直接读取。
- **分块策略**（retriever.py）：
  - Markdown 文件先按标题层级切分（`MarkdownHeaderTextSplitter`，H1-H4，标题保留在正文中），
    超长章节再二次切分；
  - 其他文件用 `RecursiveCharacterTextSplitter`（默认 400 字/重叠 80，中文标点优先断句）。
- **双路索引 + 融合**：
  - 向量路：OpenAI 兼容 Embedding（DashScope `text-embedding-v4` / Ollama `nomic-embed-text`），
    `InMemoryVectorStore`（生产可无痛替换 Chroma/FAISS/Milvus）；
  - 词面路：jieba 中文分词 + `rank_bm25`（BM25Okapi），解决向量模型对专有名词不敏感的问题；
  - 融合：`reciprocal_rank_fusion`（RRF）合并两路排名（`app/rag/fusion.py`）。
- **语义重排**（reranker.py）：`BAAI/bge-reranker-base` CrossEncoder 对候选打分重排；
  懒加载 + 本地缓存优先（`HF_ENDPOINT` 镜像）+ 异常自动降级为融合顺序。
- **检索增强生成**：`RAG_PROMPT` 约束模型"只能依据给定资料回答，资料没有的如实说明"，
  回答附带来源（`文件#分块号`），支持追溯。

### 4. 稳定性工程（app/services/）

| 组件 | 机制 | 配置 |
|---|---|---|
| 重试 resilience.py | tenacity 指数退避（0.5s 起，最大 8s），只重试可恢复错误（429/5xx/网络/超时），校验错误直接失败；同步/异步两版 + `safe_call` 兜底非关键路径 | `AIROBOT_RETRY_ATTEMPTS`、`AIROBOT_RETRY_MAX_WAIT` |
| 限流 ratelimit.py | 进程内滑动窗口（按 IP，60 秒），超限返回 JSON 429；监控接口（stats/traces）白名单豁免 | `AIROBOT_RATELIMIT_PER_MINUTE` |
| 语义缓存 semantic_cache.py | 首轮无上下文问题按 **余弦≥0.75 且 jieba 词面重叠≥0.5** 双门限命中复用答案；候选集内取双门限均通过的最高余弦；动态数据（订单）不缓存 | `AIROBOT_CACHE_ENABLED` / `CACHE_THRESHOLD` / `CACHE_LEXICAL_THRESHOLD` |

### 5. 可观测性（app/main.py + app/services/tracing.py）

- 请求日志中间件：方法/路径/状态码/耗时（`X-Process-Time-Ms` 响应头）。
- 链路追踪：每次请求记录 `cache_lookup / intent / retrieval / llm / first_token / total` 各阶段耗时
  （内存环形缓冲 300 条），并聚合 P95、平均延迟、缓存命中率、限流拦截、意图分布。
- 可视化控制台：`/dashboard` 自包含单页，内置“用户模拟对话 + 全链路可视化”面板（流式提问并实时展示各阶段耗时），并 3 秒轮询状态卡片、功能导览与实时请求明细。

### 6. 效果评估体系（eval/）

- 评测集 `eval/dataset/qa.jsonl`：52 条、8 个主题（含"知识库未覆盖"反例）。
- 指标：RAGAS Faithfulness / AnswerRelevancy / ContextPrecision / ContextRecall +
  LLM-as-Judge(1-5) + 关键词命中基线。
- 报告：控制台表格 + `eval/reports/report_<时间>.json` / `.md`（分档统计 + 低分样本）。
- 接入 CI：`eval` job 配置 Secrets 后自动运行（详见 [CI 门禁](#ci-门禁)）。

## 技术栈

| 层 | 组件 | 说明 |
|---|---|---|
| 服务框架 | FastAPI + uvicorn + Pydantic | 异步接口、自动 OpenAPI 文档（`/docs`）、SSE 支持 |
| LLM 编排 | LangChain（LCEL / ChatPromptTemplate / InMemoryVectorStore） | 意图路由、RAG 链路、流式生成 |
| 多智能体 | CrewAI（Agent/Task/Crew） | 可选；未安装自动降级 |
| 模型接入 | OpenAI 兼容协议 | DashScope（qwen-plus / text-embedding-v4）、DeepSeek、Ollama（qwen2.5 / nomic-embed-text） |
| 检索 | jieba + rank_bm25（BM25Okapi）、RRF 融合 | 词面召回与多路融合 |
| 重排 | sentence-transformers `bge-reranker-base` | 可选；懒加载 + 降级 |
| 稳定性 | tenacity | 指数退避重试 |
| 评测 | ragas 0.3.9 + langchain-community 0.3.31 | RAGAS 四指标 + LLM-as-Judge |
| 部署 | Docker / docker-compose / GitHub Actions | 容器化 + CI 门禁 |

## 系统架构

```
客户端（小程序 / Web / 后端服务）
  │  POST /api/v1/chat | /chat/stream | /ingest
  ▼
FastAPI (app/main.py)
  │  ── 请求日志中间件（耗时统计） / 滑动窗口限流中间件 / 统一异常兜底
  │
  ├─ CrewAI 可用 → 多 Agent（意图识别官 → 客服执行员，独立线程）
  │                  ├─ search_knowledge（RAG 检索增强生成）
  │                  ├─ query_order（Mock，生产 HTTP 对接 order-server）
  │                  └─ after_sale_rule（售后规则）
  │
  └─ 降级 → 内置 LangChain 路由（意图分类 + RAG/闲聊，逻辑与 Crew 一致）
        │
  └─ 稳定性层：语义缓存（首轮双门限）→ 重试（LLM/Embedding）→ 限流（入口）
        │
  └─ RAG 链路：
      文档解析(pypdf/python-docx) → 分块(Recursive / Markdown 标题)
        → Embedding(OpenAI 兼容) → 向量检索
        → 混合：jieba+BM25 词面检索 → RRF 融合 → bge-reranker 重排
        → RAG 生成（带会话记忆）
        │
  └─ 可观测：traces 链路追踪 → /dashboard 控制台 / /api/v1/traces / /api/v1/stats
```

**一次对话的完整时序（非流式）**

```
客户端 ──POST /api/v1/chat──▶ 限流中间件（放行/429）
      ──▶ 语义缓存检查（仅首轮无上下文：embedding → 双门限；命中直接返回）
      ──▶ 意图分类（LLM：knowledge/order/chat）
      ──▶ 执行：knowledge → 混合检索(向量+BM25→RRF→重排) → RAG 生成
              order     → 订单工具（Mock/HTTP）
              chat      → LLM 闲聊
      ──▶ 写会话记忆 + 写语义缓存（知识类） + 记录链路追踪
      ──▶ 200 JSON {reply, intent, sources, engine, cache_hit}
```

## 快速开始（从拉取到运行）

### 前置条件

- Windows / macOS / Linux；Windows 用 PowerShell
- Python 3.10 - 3.13（推荐 3.11）：<https://www.python.org/downloads/>
- 一个 OpenAI 兼容的 LLM/Embedding 服务，三选一：
  - **本地 Ollama（推荐，免费离线）**：<https://ollama.com/>，装好后执行
    `ollama pull qwen2.5:1.5b && ollama pull nomic-embed-text`
  - **阿里云 DashScope**（qwen-plus / text-embedding-v4，需 API Key）
  - **DeepSeek**（注意：无 Embedding 接口，向量模型需另配 DashScope/Ollama）

### 0. 一键启动（推荐，跳过下面 1-4 步）

```powershell
cd E:\develop\airobot
.\start.ps1        # 或直接双击 start.bat
```

`start.ps1` 自动完成：检查 `.env`（缺失自动生成）→ 创建虚拟环境 → 安装核心依赖 →
检查 Ollama 与模型是否就绪 → 启动服务并等待健康检查 → 浏览器自动打开控制台
`http://localhost:8000/dashboard`。停止服务：`.\stop.ps1`（日志在 `.logs/`）。

### 1. 创建虚拟环境并安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # macOS/Linux: source .venv/bin/activate

# 核心依赖（服务 + RAG + 稳定性，必须）
pip install -r requirements.txt

# 可选能力按需安装（未装则自动降级，不影响基础问答）
pip install -r requirements-extra.txt    # crewai 多智能体 + bge-reranker 重排（含 torch，体积大）
pip install -r requirements-eval.txt     # RAGAS 评测
```

### 2. 配置环境变量

```powershell
Copy-Item .env.example .env     # macOS/Linux: cp .env.example .env
```

按你的 LLM 服务编辑 `.env`（见 [环境变量说明](#环境变量说明)），本地 Ollama 示例：

```ini
AIROBOT_LLM_BASE_URL=http://localhost:11434/v1
AIROBOT_LLM_API_KEY=ollama
AIROBOT_LLM_MODEL=qwen2.5:1.5b
AIROBOT_EMBEDDING_BASE_URL=http://localhost:11434/v1
AIROBOT_EMBEDDING_API_KEY=ollama
AIROBOT_EMBEDDING_MODEL=nomic-embed-text
```

### 3. 启动服务

```powershell
uvicorn app.main:app --reload --port 8000
```

启动时自动导入 `data/knowledge_base.md`（示例知识库，7 个分块）。

### 4. 验证

```powershell
# 健康检查
Invoke-RestMethod http://localhost:8000/health

# 运行指标（知识库块数 / 缓存 / 限流等）
Invoke-RestMethod http://localhost:8000/api/v1/stats

# 知识问答（RAG）
$body = @{ message = "怎么申请退款？"; session_id = "user-001" } | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:8000/api/v1/chat -Method Post -Body $body -ContentType "application/json"
```

## 接口文档

> 交互式 API 文档：启动后访问 <http://localhost:8000/docs>（Swagger UI，自动生成）。

### GET /health

健康检查，返回当前模型配置。无参数。

```json
{"status": "ok", "llm_model": "qwen2.5:1.5b", "embedding_model": "nomic-embed-text"}
```

### POST /api/v1/chat

智能对话（意图路由 + RAG + 工具）。请求体：

```json
{
  "message": "退货运费谁承担？",
  "session_id": "user-001"
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| message | string | 是 | 用户消息 |
| session_id | string | 否 | 会话标识，默认 `default`；同一 id 自动带多轮上下文 |

响应 200：

```json
{
  "reply": "根据平台规则，因商品质量问题或与描述不符导致的退货，运费由卖家承担；买家个人原因退货则由买家承担。",
  "intent": "knowledge",
  "sources": ["knowledge_base.md#4", "knowledge_base.md#3"],
  "engine": "langchain",
  "used_crew": false,
  "cache_hit": false
}
```

| 字段 | 说明 |
|---|---|
| reply | 客服回答 |
| intent | `knowledge`（知识问答）/ `order`（订单）/ `chat`（闲聊）/ `crew`（多智能体） |
| sources | RAG 来源列表（`文件#分块号`），非知识问答为空 |
| engine | `langchain`（内置路由）/ `crew`（多智能体） |
| used_crew | 本次是否实际走 CrewAI |
| cache_hit | 是否命中语义缓存（命中时整段复用，毫秒级返回） |

错误响应：`429`（限流，`{"detail":"请求过于频繁，请稍后再试。"}`）、`500`（统一异常兜底）。

### POST /api/v1/chat/stream

SSE 流式对话。请求体同 `/api/v1/chat`。响应为 `text/event-stream`，事件序列：

```
data: {"type":"stage","stage":"rate_limit","msg":"限流检查通过，请求进入服务","ms":0,"ok":true}
data: {"type":"stage","stage":"cache","msg":"语义缓存未命中","ms":21.4,"ok":true}
data: {"type":"intent","intent":"knowledge"}
data: {"type":"stage","stage":"intent","msg":"意图识别为 knowledge","ms":547.2,"ok":true}
data: {"type":"stage","stage":"retrieval","msg":"混合检索完成","ms":2138.1,
       "detail":{"vector_ms":22.2,"vector_hits":7,"bm25_ms":0.1,"bm25_hits":6,
                 "fusion_ms":0.0,"fused":7,"rerank_ms":2115.4,"rerank_enabled":true},
       "sources":["knowledge_base.md#0"],"ok":true}
data: {"type":"token","content":"根据平台规则，"}
data: {"type":"token","content":"因商品质量问题..."}
...
data: {"type":"stage","stage":"generate","msg":"RAG 生成完成（53 tokens）","ms":517.4,"ok":true}
data: {"type":"done","intent":"knowledge","sources":["knowledge_base.md#4"],"total_ms":3225.6}
```

- `stage` 事件携带各阶段状态 / 耗时 / 明细：检索阶段细分向量 / BM25 / RRF / 重排耗时与命中数，供控制台全链路可视化
- 命中语义缓存时：`intent` 前 `cache` 阶段 `hit: true`，随后单个 `token`（整段答案）+ `done` 携带 `cache_hit: true`
- `intent=order` 时：`tool` 阶段标识工具调用，单 `token` 整段返回工具结果
- 异常时：`stage.error` + `token` 携带错误信息 + `done`

### POST /api/v1/ingest

上传文档入库（multipart 表单，字段名 `file`）。支持 `.pdf / .docx / .md / .txt / .markdown`。

```powershell
curl.exe -X POST http://localhost:8000/api/v1/ingest -F "file=@data/knowledge_base.md"
```

```json
{"file_name": "knowledge_base.md", "chunks": 7, "total_chunks": 14}
```

### GET /api/v1/stats

运行指标：知识库分块数、LLM/Embedding 模型、多智能体可用性、混合检索/重排开关、
缓存启用状态与命中统计、限流配置与拦截数。控制台数据源之一。

### GET /api/v1/traces

链路追踪：最近 N 条请求（默认 50）的各阶段耗时（缓存/意图/检索/生成）+ 聚合统计
（P95、平均延迟、缓存命中率、限流拦截、意图分布）。

### GET /dashboard

可视化控制台（浏览器访问），详见下节。

## 可视化控制台

启动服务后打开 <http://localhost:8000/dashboard>（自包含单页、无外部 CDN 依赖）：

- **用户模拟对话**：在控制台直接模拟用户提问（SSE 流式输出，支持切换 `session_id` 模拟多用户，内置快捷问题）
- **全链路可视化**：随对话实时展示 `限流检查 → 语义缓存 → 意图识别 → 混合检索 → 工具/生成 → 记忆/缓存写入` 各阶段状态与耗时；检索阶段细分向量 / BM25 / RRF / 重排
- **状态卡片**：服务健康 / LLM / Embedding / 知识库分块 / 缓存命中率 / P95 延迟 / 限流拦截 / 请求总数
- **功能导览**：16 项能力一句话说明，快速了解"这个服务能做什么"
- **实时执行监控**：每次对话请求的阶段耗时分解（缓存查询 / 检索 / 意图 / 生成）与状态码；
  最近 20 条请求总耗时柱状趋势（每 3 秒自动刷新）
- 数据来源：`GET /api/v1/traces` + `GET /api/v1/stats`；监控接口已从业务限流中豁免

## Docker 部署

> 需要 Docker Desktop（Windows/macOS）或 Docker Engine（Linux）。

### 本地 Ollama 模式（默认，免费离线）

```powershell
docker compose up -d --build
docker compose logs -f airobot
Invoke-RestMethod http://localhost:8000/api/v1/stats
```

- compose 内置 `ollama` 服务，entrypoint 自动 `ollama pull` 与 `.env` 一致的模型，首次启动较慢
- 容器内 LLM/Embedding 自动指向 `http://ollama:11434/v1`（服务名解析，无需改 `.env`）
- `./data` 挂载为卷（知识库热更新），`hf-cache` 卷复用重排模型下载缓存

### 云端 API 模式

编辑 `docker-compose.yml`，把 `airobot` 的两个 `AIROBOT_*_BASE_URL` 改为 DashScope 地址，
`.env` 填 API Key，可同时删掉 `ollama` 服务，重新 `docker compose up -d --build`。

### 构建加速

- pip 默认清华镜像源（`ARG PIP_INDEX_URL` 可覆盖为阿里云等）
- `--mount=type=cache` 复用 pip 下载缓存：只改代码重建秒级；改依赖也只下载新增包
- 拉基础镜像慢：Docker Desktop → Settings → Docker Engine 配置 `registry-mirrors`
  （如 `["https://docker.m.daocloud.io", "https://dockerproxy.com"]`），基础镜像只需拉一次

## CI 门禁

`.github/workflows/ci.yml`：push / PR 自动执行三个串行 job。

| Job | 内容 | 说明 |
|---|---|---|
| `build` | `pip install` + `py_compile` 语法检查 | 必过 |
| `test` | 稳定性工程离线单测 + 服务导入冒烟 | 必过 |
| `eval` | RAGAS 前 5 条冒烟评测 | 配置 Secrets 后启用 |

配置仓库 Secrets（Settings → Secrets and variables → Actions）：`AIROBOT_LLM_API_KEY`、
`AIROBOT_EMBEDDING_API_KEY`。未配置时 `eval` 自动跳过，build/test 门禁仍生效；
评测报告上传为 workflow artifact。

## 效果评测（RAGAS）

```powershell
# 冒烟：前 5 条
$env:AIROBOT_RERANK_ENABLED="false"; python eval\run_eval.py --limit 5
# 全量 52 条（RAGAS 四指标 + Judge + 基线）
python eval\run_eval.py
```

- 评测集：`eval/dataset/qa.jsonl`（52 条，8 个主题，含"知识库未覆盖"反例）
- 指标：RAGAS Faithfulness / AnswerRelevancy / ContextPrecision / ContextRecall +
  LLM-as-Judge(1-5) + 关键词命中基线
- 输出：控制台表格 + `eval/reports/report_<时间>.json` / `.md`（分档统计 + 低分样本）
- 注意：ragas 0.3.9 需搭配 `langchain-community==0.3.31`（见 `requirements-eval.txt`）

## 检索与分块实验

```powershell
python scripts\bench_retrieval.py --top-k 5     # vector / bm25 / hybrid_rrf / hybrid_rerank 命中率与耗时
python scripts\bench_splitter.py --top-k 3      # 不同分块参数的检索命中率
python scripts\ingest.py data\knowledge_base.md # CLI 导入知识文件（独立进程）
```

参考实测（52 条评测集，top-k=2）：vector 67% → bm25 98% / hybrid_rrf 98%，证明混合检索必要性。

## 设计决策

- **为什么两套实现（CrewAI + 内置路由）？** 多 Agent 框架是编排层，业务工具是执行层；
  框架不可用/版本差异时降级到等价路由，保证服务可用性——对应"稳定性保障"。
- **RAG 效果怎么保证？** 分块参数、TopK、提示词约束 + RAGAS 评测闭环 + 混合检索/重排对比实验数据。
- **语义缓存怎么防误命中？** 余弦相似度 + jieba 词面重叠双门限，只缓存"首轮无上下文"问题，
  动态数据（订单）不缓存；命中可观测（`cache_hit` 字段）。
- **订单查询如何接真实数据？** 当前为 Mock，生产两种方案：
  方案 A（Java 侧分流）——后端识别 `intent=order` 后由业务服务查订单；
  方案 B（AI 侧调用）——airobot 订单工具改为 HTTP 调用 order-server（配置 `AIROBOT_ORDER_API_URL` + 超时降级）。
- **内存态组件如何生产化？** 向量库/会话记忆/语义缓存/限流当前为进程内实现，接口与
  Chroma/FAISS/Milvus、Redis 一致，可无痛替换（见下表）。

| 当前实现 | 生产替换 |
|---|---|
| InMemoryVectorStore | Chroma / FAISS / Milvus（持久化 + ANN 索引） |
| 进程内会话记忆 | Redis / SQLite 持久化 |
| 进程内语义缓存 / 限流 | Redis（分布式缓存与计数），网关层限流 |
| 无鉴权 | 网关统一鉴权 + `X-API-Key` 头校验 |
| query_order Mock | HTTP 对接 order-server（幂等 + 超时降级） |

## 项目结构

```
airobot/
├── app/
│   ├── main.py            FastAPI 入口：接口 / 中间件 / SSE / 异常兜底 / 控制台
│   ├── config.py          环境变量配置（dotenv）
│   ├── schemas.py         请求/响应模型
│   ├── agents/            CrewAI 编排（crew.py）与工具集（tools.py）
│   ├── rag/               loader(解析) / retriever(检索+生成) / lexical(BM25) / fusion(RRF) / reranker
│   ├── services/          chat(编排) / memory(会话) / resilience(重试) / ratelimit(限流)
│   │                      / semantic_cache(缓存) / tracing(链路追踪)
│   └── static/            dashboard.html 可视化控制台
├── data/                  知识库文件（启动自动导入）与实验输出 CSV
├── eval/                  run_eval.py + dataset/qa.jsonl（52 条）+ reports/
├── scripts/               检索/分块对比实验、CLI 导入
├── tests/                 test_stability.py / test_tracing.py 离线单测
├── .github/workflows/     ci.yml（build → test → eval 门禁）
├── Dockerfile / docker-compose.yml / .dockerignore   容器化部署
├── start.ps1 / stop.ps1 / start.bat   一键启动/停止（Windows）
├── requirements.txt       核心运行时依赖
├── requirements-eval.txt  RAGAS 评测依赖
├── requirements-extra.txt 可选：crewai 多智能体 + bge-reranker 重排
└── .env.example           环境变量模板（复制为 .env 使用）
```

## 环境变量说明

| 变量 | 说明 |
|---|---|
| AIROBOT_LLM_BASE_URL / API_KEY / MODEL | 大模型（OpenAI 兼容：DashScope / DeepSeek / Ollama） |
| AIROBOT_EMBEDDING_BASE_URL / API_KEY / MODEL | 向量模型（DashScope text-embedding-v4 或 Ollama nomic-embed-text） |
| AIROBOT_USE_CREW | 是否优先走 CrewAI（未安装自动降级） |
| AIROBOT_TOP_K / CHUNK_SIZE / CHUNK_OVERLAP | 召回条数与分块参数 |
| AIROBOT_HYBRID_ENABLED / VECTOR_TOP_K / BM25_TOP_K / FUSION_TOP_K | 混合检索开关与各路召回条数 |
| AIROBOT_RERANK_ENABLED / RERANK_MODEL | bge-reranker 重排开关与模型 |
| AIROBOT_RETRY_ATTEMPTS / RETRY_MAX_WAIT | 重试次数与最大退避秒数 |
| AIROBOT_RATELIMIT_ENABLED / RATELIMIT_PER_MINUTE | 限流开关与每分钟上限（按 IP，60 秒窗口） |
| AIROBOT_CACHE_ENABLED / CACHE_THRESHOLD / CACHE_LEXICAL_THRESHOLD / CACHE_MAX_ENTRIES | 语义缓存开关与双门限参数 |
| AIROBOT_MEMORY_MAX_TURNS / AIROBOT_MEMORY_RETRIEVE_TURNS | 会话记忆保留轮次 / 带入上下文的轮次 |

## 常见问题

**Q：未配置 API Key 能跑吗？** 能。服务可启动（健康检查/文档解析/检索均可用），
对话接口会提示"未配置 AIROBOT_LLM_API_KEY"。本地推荐装 Ollama 免费跑通全链路。

**Q：crewai / ragas / sentence-transformers 没装会怎样？** 自动降级：多 Agent 走内置
LangChain 路由、评测脚本需装 `requirements-eval.txt`、重排保留 RRF 融合顺序。

**Q：重排模型下载慢/挂起怎么办？** 已内置 HF 镜像（`HF_ENDPOINT=https://hf-mirror.com`）
与本地缓存优先策略；也可 `AIROBOT_RERANK_ENABLED=false` 关闭。

**Q：改了代码每次都要构建镜像吗？** 不用。日常开发用宿主机 `.venv` + `uvicorn --reload`；
镜像只在发布/交付时 `docker compose up -d --build`（改代码秒级重建，见"构建加速"）。

**Q：Java / Node 后端如何调用？** 通过 HTTP/SSE 调 `/api/v1/chat` 或 `/api/v1/chat/stream`，
参考 [接口文档](#接口文档)；生产建议走网关 + 内网隔离 + `X-API-Key` 鉴权。

## License

本项目使用 [MIT License](LICENSE)（Copyright (c) 2026 Liu Bojiang）。
MIT 是最宽松的开源许可之一：允许任何人自由使用、修改、分发（含商用），只需保留版权声明。
