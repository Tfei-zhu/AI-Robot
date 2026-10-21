这是基于当前源码的整体架构图：普通聊天使用单智能体，Go 专用任务按开关选择编排方式，知识入库直接进入知识库。

已读取项目说明及相关实现，未修改代码、未读取 `.env`。以下“默认”指代码或部署文件的默认值，不代表当前进程配置或依赖已就绪。

---

主图展示七层组件及三条主链路。实线表示请求响应调用，包括代码通过 `async/await` 实现的调用；虚线表示异步消息或 SSE（服务端事件流）；粗线表示数据读写。

<!-- readme-diagram:01-architecture-01 -->
![三条业务主线](../png/01-architecture-01.png)

<details>
<summary>展开原始完整流程</summary>

```mermaid
flowchart TB
    %% 本图只展示组件职责和依赖，不展开重试、修复等内部步骤。
    %% 蓝色表示已实现的组件；橙色表示可选组件，启用条件写在节点或连线上。

    subgraph client_layer["用户与 Dashboard"]
        user["用户 / 管理客户端"]
        dashboard["Dashboard<br/>聊天、Go 任务、报告与监控"]
        user --> dashboard
    end

    subgraph api_layer["FastAPI 接口"]
        api_guard["SecurityMiddleware + 接口中间件<br/>身份校验、权限控制、限流与会话隔离"]
        chat_api["普通聊天接口<br/>POST /api/v1/chat<br/>POST /api/v1/chat/stream"]
        go_api["Go 专用接口<br/>POST /api/v1/go/tasks 及 /stream<br/>GET /api/v1/go/tasks/{run_id}"]
        ingest_api["知识上传接口<br/>POST /api/v1/ingest<br/>仅管理员"]
        ops_api["观测接口<br/>GET /api/v1/stats<br/>GET /api/v1/traces"]
    end

    subgraph service_layer["业务服务"]
        chat_service["聊天服务 chat / stream_chat<br/>会话管理、首轮缓存、响应与轨迹<br/>缓存命中时直接答复"]
        go_service["GoTaskService<br/>执行专用任务、输出进度、保存报告"]
        article_consumer["ArticleIngestConsumer<br/>后台消费文章发布事件<br/>AMQP_URL 为空时不启动消费"]
        go_client["GoArticleClient<br/>共用文章详情客户端"]
        startup["lifespan 启动管理<br/>恢复知识与文章状态<br/>空库尝试导入指定样例、启动消费者"]
        runtime_state["进程内状态<br/>会话记忆、语义缓存、限流、近期轨迹"]
    end

    subgraph orchestration_layer["智能体编排：共用 LangGraph 状态图"]
        chat_agent["普通聊天单智能体<br/>规划、按需调用只读工具、回答"]
        go_selector{"Go 专用任务<br/>go_multi_agent.enabled"}
        single_go["默认 Go 工作流 single-v1<br/>固定节点编排代码生成与验证"]
        multi_go["可选 Go 多智能体 multi-v1<br/>SupervisorAgent：需求规划与审查<br/>CodeAgent：代码产物<br/>服务端控制编排与通过判定<br/>默认关闭"]
    end

    subgraph tool_layer["工具与检索"]
        kb_service["知识库 kb<br/>文档解析、分块、向量化与索引<br/>search_knowledge 只返回原文和来源<br/>向量与关键词检索、排名融合、可选重排"]
        readonly_tools["其他只读工具<br/>query_article：实时文章详情<br/>community_guideline：内置社区规范"]
        go_validator["Go 服务端验证<br/>DockerGoRunner<br/>单工作流经 validate_go_code 调用<br/>多智能体编排直接调用"]
    end

    subgraph persistence_layer["持久化"]
        sqlite_storage[("SQLite 分库<br/>知识分块、文章正文与入库状态、Go 报告<br/>具体边界见补图")]
    end

    subgraph external_layer["外部依赖"]
        llm_service["模型服务<br/>OpenAI 兼容接口<br/>云端服务或本地 Ollama"]
        embedding_service["向量化服务 Embedding<br/>文档与查询文本转为向量<br/>可与模型服务分别配置"]
        go_article_service["可选：Go 文章服务<br/>POST /internal/ai/article/detail<br/>需配置服务地址与内部令牌"]
        rabbitmq["可选：RabbitMQ<br/>文章发布事件队列<br/>需配置 AMQP_URL"]
        docker_engine["Docker Linux 引擎与验证容器<br/>固定镜像 airobot-go-validator:1.26.2<br/>Go 验证必需，需独立准备"]
    end

    %% Dashboard 没有知识上传界面；上传由管理员客户端调用接口。
    dashboard -->|"聊天、Go 任务、监控"| api_guard
    user -->|"直接调用接口；含管理员上传"| api_guard
    api_guard --> chat_api
    api_guard --> go_api
    api_guard -->|"管理员上传请求"| ingest_api
    api_guard --> ops_api

    %% 普通聊天不会自动转入 Go 专用任务，也不会自动委派多智能体。
    chat_api --> chat_service
    chat_service -->|"缓存未命中或不使用缓存"| chat_agent
    chat_service ==>|"读取历史与缓存；写入记忆、缓存和轨迹"| runtime_state
    chat_service -->|"缓存查询所需的文本向量"| kb_service
    chat_agent -->|"按需 search_knowledge"| kb_service
    chat_agent -->|"按需查询文章或规范"| readonly_tools
    chat_agent --> llm_service

    %% 多智能体开关只决定 Go 专用入口的执行分支。
    go_api -->|"创建任务"| go_service
    go_service --> go_selector
    go_selector -->|"false：默认"| single_go
    go_selector -->|"true：显式启用"| multi_go
    single_go --> llm_service
    multi_go -->|"角色模型可分别配置"| llm_service
    single_go -->|"具备向量配置时检索参考资料"| kb_service
    multi_go -->|"需求允许继续且具备向量配置时检索"| kb_service
    single_go --> go_validator
    multi_go --> go_validator
    go_validator -->|"调用 Docker 命令执行隔离验证"| docker_engine
    go_service ==>|"保存完整任务报告"| sqlite_storage
    go_service ==>|"记录近期轨迹"| runtime_state
    go_api ==>|"按账户读取历史报告"| sqlite_storage

    %% 上传和文章事件入库均直接调用知识库，不经过智能体。
    ingest_api -->|"上传文件解析与入库"| kb_service
    startup -->|"恢复分块；空库尝试指定样例"| kb_service
    startup -->|"恢复文章；按配置启动消费"| article_consumer
    rabbitmq -.->|"文章发布事件"| article_consumer
    article_consumer -->|"本地没有已保存正文时获取全文"| go_client
    article_consumer -->|"文章正文入库"| kb_service
    article_consumer ==>|"保存正文、入库状态与失败登记"| sqlite_storage
    kb_service ==>|"保存分块；启动读取并恢复索引"| sqlite_storage
    kb_service -->|"入库、查询向量化及索引恢复"| embedding_service

    readonly_tools -->|"仅 query_article 使用"| go_client
    go_client -->|"内部令牌鉴权，查询文章详情"| go_article_service

    %% Go 发布端不在本仓库；这条连接是文档描述的外部集成约定。
    go_article_service -.->|"外部约定：发布文章事件；发布端实现未核验"| rabbitmq

    ops_api ==>|"读取缓存、限流与近期轨迹"| runtime_state
    ops_api ==>|"读取知识库指标"| kb_service
    chat_api -.->|"流式接口输出 SSE"| dashboard
    go_api -.->|"流式接口输出 SSE"| dashboard

    subgraph legend_layer["图例"]
        legend_source["交互发起方"]
        legend_call["同步请求响应"]
        legend_event["异步消息 / 流式事件"]
        legend_data["数据读写"]
        legend_source --> legend_call
        legend_source -.-> legend_event
        legend_source ==> legend_data
    end

    classDef default fill:#eef5ff,stroke:#5279a4,color:#172b4d;
    classDef optional fill:#fff3dc,stroke:#bf8628,color:#614511;
    class multi_go,go_article_service,rabbitmq optional;
```

</details>

---

补图细化索引与存储边界，避免把内存索引、会话缓存误画成持久化数据库。重复的组件 ID 对应主图中的同一组件。

<!-- readme-diagram:01-architecture-02 -->
![索引与存储边界](../png/01-architecture-02.png)

<details>
<summary>展开原始完整流程</summary>

```mermaid
flowchart LR
    subgraph owner_layer["数据使用方"]
        kb_service["知识库 kb<br/>入库、检索与启动恢复"]
        article_consumer["ArticleIngestConsumer"]
        go_service["GoTaskService"]
        chat_service["聊天服务"]
        context_service["可选：上下文管理<br/>预算、摘要、证据复用与受限补读<br/>CONTEXT_MODE 默认 off"]
    end

    subgraph memory_layer["进程内索引与状态：本身不持久化"]
        vector_memory["InMemoryVectorStore<br/>默认向量索引"]
        bm25_memory["BM25 关键词索引<br/>始终位于进程内"]
        runtime_state["MemoryStore / SemanticCache / traces<br/>默认会话、答案缓存与近期轨迹"]
        reranker["可选：bge-reranker<br/>本地相关性重排模型<br/>代码默认开启；Docker 默认关闭"]
    end

    subgraph database_layer["SQLite 持久化：默认位于 data 目录"]
        knowledge_db[("knowledge.sqlite3<br/>分块原文与元数据")]
        article_db[("airobot_state.sqlite3<br/>文章正文、入库状态与失败登记")]
        go_db[("go_tasks.sqlite3<br/>按账户保存任务报告")]
        context_db[("可选：context.sqlite3<br/>会话原文、摘要、证据与运行记录")]
    end

    subgraph external_vector_layer["可选外部索引"]
        milvus["Milvus<br/>VECTOR_STORE=milvus 时替代内存向量索引<br/>需额外依赖及独立服务"]
    end

    %% 两种向量后端二选一；BM25 不随 Milvus 切换到外部存储。
    kb_service ==>|"默认：写入与查询向量"| vector_memory
    kb_service ==>|"选择 milvus 时写入与查询"| milvus
    kb_service ==>|"维护与查询关键词索引"| bm25_memory
    kb_service -->|"开关开启且模型可用时调用"| reranker

    %% SQLite 保存知识原文；启动恢复会重新走索引构建及向量化路径。
    kb_service ==>|"写分块；启动读取恢复"| knowledge_db
    article_consumer ==>|"保存与恢复文章、登记状态"| article_db
    go_service ==>|"保存与读取报告"| go_db
    chat_service ==>|"读写默认会话、缓存与轨迹"| runtime_state

    %% off 默认不创建上下文数据库；已有数据库可继续被读取和提交原文。
    chat_service -->|"上下文策略与条件存储接入"| context_service
    context_service ==>|"启用时使用；off 时可复用已有库"| context_db

    classDef default fill:#eef5ff,stroke:#5279a4,color:#172b4d;
    classDef optional fill:#fff3dc,stroke:#bf8628,color:#614511;
    class context_service,context_db,reranker,milvus optional;
```

</details>

---

关键分支与对应源码：

| 分支或边界 | 实际逻辑 | 源码位置 |
|---|---|---|
| 普通聊天 | 缓存命中直接返回；否则进入单智能体，按需调用只读工具。不会因问题涉及 Go 就切换专用任务 | [chat.py:137](../../../app/services/chat.py#L137)、[graph.py:272](../../../app/agents/graph.py#L272)、[tools.py:104](../../../app/agents/tools.py#L104) |
| Go 专用任务 | 默认 `single-v1`；`AIROBOT_GO_MULTI_AGENT_ENABLED=true` 才进入 `multi-v1`。报告可以重新读取，未实现任务恢复执行 | [config.py:30](../../../app/config.py#L30)、[service.py:76](../../../app/go_validation/service.py#L76)、[go_workflow.py:537](../../../app/agents/go_workflow.py#L537)、[store.py:42](../../../app/go_validation/store.py#L42) |
| 知识入库 | 上传直接调用 `kb.ingest_file`；启动只在空库时尝试指定样例，不扫描整个 `data` 目录 | [main.py:36](../../../app/main.py#L36)、[main.py:153](../../../app/main.py#L153)、[retriever.py:266](../../../app/rag/retriever.py#L266) |
| 文章事件与实时查询 | 共用 Go 客户端；`AMQP_URL` 为空时不启动消费者。发布端属于外部服务，本仓库无法核验其实现；未实现历史文章主动回填及更新、删除同步 | [article_consumer.py:173](../../../app/services/article_consumer.py#L173)、[article_consumer.py:259](../../../app/services/article_consumer.py#L259)、[go_client.py:62](../../../app/services/go_client.py#L62)、[usage.md](../../usage.md) |
| 检索与重排 | 混合检索默认开启；向量后端默认 `inmemory`，Milvus 可选。重排代码默认开启，但需要额外依赖和模型，加载失败时跳过；Docker 默认关闭 | [config.py:152](../../../app/config.py#L152)、[retriever.py:71](../../../app/rag/retriever.py#L71)、[retriever.py:275](../../../app/rag/retriever.py#L275)、[reranker.py:21](../../../app/rag/reranker.py#L21)、[docker-compose.yml:20](../../../docker-compose.yml#L20) |
| 持久化与上下文 | 默认会话、缓存、轨迹在内存；知识原文和 Go 报告有独立持久化。实验上下文策略默认 `off`；关闭后仍可能复用已有上下文库 | [retriever.py:133](../../../app/rag/retriever.py#L133)、[memory.py:15](../../../app/services/memory.py#L15)、[config.py:130](../../../app/config.py#L130)、[session.py:9](../../../app/context/session.py#L9) |
| Docker 连接 | Go 验证必须通过固定容器执行，容器禁网；默认 Compose 只部署应用与 Ollama，未配备应用调用 Docker 所需的客户端和引擎连接，也未部署 Go 服务或 RabbitMQ；Milvus 使用独立 Compose 文件 | [runner.py:23](../../../app/go_validation/runner.py#L23)、[Dockerfile:25](../../../Dockerfile#L25)、[docker-compose.yml:7](../../../docker-compose.yml#L7)、[docker-compose-milvus.yml:6](../../../docker-compose-milvus.yml#L6) |

Dashboard 实际调用聊天、Go 任务和监控接口，没有知识上传界面；文章工具也没有发布、评论或修改文章的写入能力。对应实现见 [dashboard.html:529](../../../app/static/dashboard.html#L529) 和 [tools.py](../../../app/agents/tools.py)。
