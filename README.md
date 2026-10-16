# AI-Robot

面向 Go 技术文章社区的 AI 助手，支持知识问答、实时文章查询、流式对话，以及 Go 示例代码的隔离验证与修复。

基于 FastAPI、LangGraph（状态图编排）与 RAG（检索增强生成）构建；知识检索、文章查询和社区规范作为只读工具，由 Agent 按需调用。

![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688)
![LangGraph](https://img.shields.io/badge/LangGraph-1.0%2B-1C3C3C)

## 核心能力

| 能力 | 说明 |
| --- | --- |
| 社区对话 | JSON（结构化数据）与 SSE（服务端流式输出）共用 Agent 图，返回工具步骤与资料来源 |
| 混合检索 | 向量与关键词召回、排名融合、可选语义重排；支持 PDF、DOCX、Markdown、TXT |
| 社区集成 | 查询 Go 文章服务的实时详情，通过 RabbitMQ 发布事件自动导入文章 |
| Go 示例验证 | 支持 context 取消、任务池、channel 三类场景；隔离编译、检查、测试并最多修复两轮 |
| 上下文管理（实验） | Token（模型文本计量单位）预算、增量摘要、工具结果精简、证据复用与受限补读；默认关闭 |
| 运行观测 | Dashboard 展示执行阶段、调用用量、耗时与缓存指标；接口提供近期运行轨迹 |

请求流程：身份校验与限流 → Agent 规划 → 只读工具调用 → 最终回答 → 会话记录。

## 快速开始

需要 Python 3.11+、支持工具调用的模型服务和可用的 Embedding（文本向量）服务。以下使用 Windows PowerShell；Linux/macOS、本地 Ollama 和 Docker 部署见[使用与部署](docs/usage.md)。

### 1. 安装依赖

```powershell
# 在项目根目录执行；已有 .env 时保留原配置。
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

### 2. 编辑配置

示例默认使用 DashScope。在 `.env` 中填写以下配置；使用其他服务时，同步修改对应的 `BASE_URL` 和 `MODEL`。

```ini
# 模型、向量服务密钥，以及独立的管理员令牌。
AIROBOT_LLM_API_KEY=替换为模型密钥
AIROBOT_EMBEDDING_API_KEY=替换为向量服务密钥
AIROBOT_ADMIN_TOKEN=替换为独立随机长令牌

# 独立运行时清空 Go / RabbitMQ 集成配置，关闭可选重排。
AIROBOT_GO_API_BASE_URL=
AIROBOT_GO_INTERNAL_TOKEN=
AIROBOT_AI_INTERNAL_TOKEN=
AIROBOT_AMQP_URL=
AIROBOT_RERANK_ENABLED=false
```

完整配置见 [`.env.example`](.env.example)。接入 Go 网关时，两侧内部令牌必须一致，管理员令牌另行配置，详见[集成说明](docs/usage.md#与-go-文章社区集成)。

### 3. 启动服务

```powershell
# 默认单进程启动；生产环境保持单 worker。
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- [Dashboard](http://localhost:8000/dashboard)：在页面顶部填写与 `.env` 一致的管理员令牌。
- [接口文档](http://localhost:8000/docs)：查看请求与响应结构。
- [健康检查](http://localhost:8000/health)：检查进程存活；模型和检索是否可用需通过实际请求确认。

启动会恢复持久化知识；首次空库尝试导入[示例资料](data/knowledge_base.md)。索引恢复依赖 Embedding 服务。Go 代码验证还需要 Docker Linux 引擎及固定验证镜像，见 [Go 验证指南](docs/go-validation.md)。

## 主要接口

| 接口 | 用途 |
| --- | --- |
| `POST /api/v1/chat` | 非流式对话 |
| `POST /api/v1/chat/stream` | 流式对话与执行步骤 |
| `POST /api/v1/go/tasks`、`/api/v1/go/tasks/stream` | Go 示例生成、验证与修复 |
| `GET /api/v1/go/tasks/{run_id}` | 读取当前账户的任务报告 |
| `POST /api/v1/ingest` | 管理员上传知识资料 |
| `GET /api/v1/stats`、`/api/v1/traces` | 管理员查看指标与运行轨迹 |

所有 `/api/*` 接口需要身份凭据；聊天与 Go 任务支持管理员或可信 Go 网关身份。请求示例、流式事件与错误码见[接口说明](docs/usage.md#接口说明)。

## 测试与当前状态

```powershell
# 安装开发依赖，运行离线机制与业务回归测试。
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests -q
```

真实 Docker 验证与真实模型质量评测需要分别配置环境；模型评测会产生调用费用，入口与预算说明见[开发与评测](docs/development.md#测试与-ci)。

上下文模块已完成 30 条脚本、四组各重复 3 次的 **360 次真实模型对照评测**，综合质量与效率门槛尚未全部通过，当前保持 `AIROBOT_CONTEXT_MODE=off`。[查看完整结果](docs/context-management-final-results.md)。

## 文档导航

| 文档 | 内容 |
| --- | --- |
| [使用与部署](docs/usage.md) | 本地启动、模型配置、接口、鉴权、Go 集成、持久化、Docker 与常见问题 |
| [开发与评测](docs/development.md) | 技术架构、执行机制、项目结构、测试、CI 与质量评测 |
| [Go 验证指南](docs/go-validation.md) | 固定接口、验证镜像、任务状态与验收方法 |
| [上下文管理](docs/context-management.md) | 预算、摘要、原文补读、存储与回退 |
| [上下文验收结果](docs/context-management-final-results.md) | 四组对照数据、失败分析与启用条件 |
| [配置示例](.env.example) / [配置定义](app/config.py) | 环境变量及代码默认值 |
| [审计记录](AUDIT.md) / [改造记录](REVIEW.md) | 历史问题与修复记录 |

## License

[MIT](LICENSE)
