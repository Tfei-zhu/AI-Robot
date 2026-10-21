知识入库有三个独立入口：**文件上传负责解析新文件，文章事件负责获取并保存正文，启动恢复负责重建已有数据的索引**；它们只在分块进入 `_ingest_docs` 后共享索引写入流程。

以下按当前源码绘制，未读取 `.env`、未修改代码。实线表示执行顺序，虚线表示消息投递或重投，粗线表示数据保存。

---

**入口一：管理员上传文件。**

<!-- readme-diagram:04-knowledge-ingestion-01 -->
![管理员上传文件](../png/04-knowledge-ingestion-01.png)

<details>
<summary>展开原始完整流程</summary>

```mermaid
flowchart TB
    upload_entry["管理员上传<br/>POST /api/v1/ingest"]
    upload_guard["先通过管理员权限、请求体上限<br/>限流及 UploadFile 参数校验"]
    upload_check{"上传接口检查通过？<br/>已配置 Embedding 密钥<br/>文件后缀受支持<br/>文件非空且大小不超限"}
    upload_reject["返回错误<br/>400：配置缺失、类型不支持或空文件<br/>413：超出大小限制"]
    upload_temp["写入临时文件<br/>保留后缀，原文件名取 basename"]

    subgraph file_ingestion["run_blocking 调用 kb.ingest_file"]
        file_parse["loader.parse_file<br/>PDF：提取页面文本<br/>DOCX：读取段落<br/>MD / Markdown / TXT：读取文本"]
        file_split["ingest_text → _split_text<br/>Markdown：按 H1-H4 切分，长章节再次切分<br/>其他文本：递归字符切分"]
        file_documents["构造 Document<br/>保存标题、分块序号、标题层级<br/>doc_id = 文件名#分块序号"]
        upload_index["调用共享索引子流程<br/>_ingest_docs，persist=true"]
    end

    upload_success["finally 删除临时文件<br/>HTTP 200 返回本次新增 chunks 与 total_chunks<br/>新增数量可以为 0"]
    upload_failure["记录入库异常<br/>finally 删除临时文件<br/>HTTP 500 返回入库失败"]

    upload_entry --> upload_guard
    upload_guard --> upload_check
    upload_check -->|"否"| upload_reject
    upload_check -->|"是"| upload_temp
    upload_temp --> file_parse
    file_parse --> file_split
    file_split --> file_documents
    file_documents --> upload_index
    upload_index -->|"正常返回，包含 0"| upload_success

    %% 解析、分块、持久化或索引异常都由上传接口这一层转换为 HTTP 500。
    file_parse -->|"异常"| upload_failure
    file_split -->|"异常"| upload_failure
    upload_index -->|"异常"| upload_failure
```

</details>

支持 `.pdf`、`.docx`、`.md`、`.markdown`、`.txt`，不支持旧版 `.doc`。文件内容默认上限 **10 MiB**，整个上传请求另允许 **64 KiB** 的表单开销。

普通递归切分默认长度 **400 字符**、重叠 **80 字符**；Markdown 章节超过默认 **800 字符**才进一步递归切分。PDF 当前只提取文本，没有 OCR（图片文字识别）流程。

源码：[main.py:153](../../../app/main.py#L153)、[loader.py:9](../../../app/rag/loader.py#L9)、[retriever.py:205](../../../app/rag/retriever.py#L205)、[retriever.py:249](../../../app/rag/retriever.py#L249)。

---

**入口二：RabbitMQ 文章事件。正文先落库，再进入知识索引流程。**

<!-- readme-diagram:04-knowledge-ingestion-02 -->
![文章发布事件入库](../png/04-knowledge-ingestion-02.png)

<details>
<summary>展开原始完整流程</summary>

```mermaid
flowchart TB
    rabbitmq["RabbitMQ 文章发布队列<br/>消费者与 API 使用同一个 kb 实例"]
    mq_delivery["接收消息<br/>进入 message.process<br/>requeue=true，ignore_processed=true"]
    event_valid{"JSON 合法且为对象？<br/>article_id 为正整数？"}
    article_duplicate{"article_id 已在本进程<br/>_ingested_article_ids 中？"}
    article_local{"ingested_articles 中<br/>已有该 ID 的记录？"}
    local_body["读取本地保存的正文与元数据<br/>不重新请求 Go 服务"]
    go_client["GoArticleClient 获取文章全文<br/>POST /internal/ai/article/detail"]
    article_found{"文章是否存在？"}

    subgraph article_ingestion["文章正文保存与入库"]
        article_pending["INSERT OR IGNORE 保存文章正文<br/>新记录 status=pending 并提交<br/>既有记录不覆盖"]
        article_documents["kb.ingest_article<br/>非空正文：拼接标题，按 Markdown 分块<br/>附加 article_id、summary、tags<br/>doc_id = article:ID#分块序号<br/>空正文直接产生 0 分块"]
        article_index["调用共享索引子流程<br/>_ingest_docs，persist=true"]
        article_mark["标记 status=ingested 并提交<br/>删除该文章的失败登记<br/>加入本进程已处理集合，清除失败计数"]
    end

    mq_skipped["获取、保存或入库发生被捕获异常<br/>返回 skipped"]
    retry_count["内存中的该文章失败计数 + 1"]
    retry_limit{"是否达到失败上限？<br/>默认第 5 次"}
    retry_raise["抛出 RetryLater"]
    mq_requeue["处理块异常退出<br/>reject：requeue=true"]
    mq_backoff["消息已重新入队<br/>本消费者等待后再取消息<br/>默认指数退避，起始 2 秒，最高 30 秒"]
    failure_record["持久化 ingest_failures<br/>登记 article_id、event_id、次数与时间<br/>正常返回，停止本轮重投"]

    mq_ack["正常退出 message.process<br/>ACK：确认并移除本次消息"]
    mq_unexpected["失败登记等位置再次发生未捕获异常<br/>处理块尝试 reject 并重新入队<br/>消费监督循环等待 30 秒后重连"]

    rabbitmq -.-> mq_delivery
    mq_delivery --> event_valid
    event_valid -->|"否：坏 JSON 或 invalid"| mq_ack
    event_valid -->|"是"| article_duplicate
    article_duplicate -->|"是：duplicate"| mq_ack
    article_duplicate -->|"否"| article_local
    article_local -->|"有记录"| local_body
    article_local -->|"无记录"| go_client
    local_body --> article_pending
    go_client --> article_found
    article_found -->|"404：not_found"| mq_ack
    article_found -->|"存在"| article_pending

    article_pending ==> article_documents
    article_documents --> article_index
    article_index -->|"正常返回，包括新增 0 块"| article_mark
    article_mark -->|"ingested"| mq_ack

    article_local -->|"读取异常"| mq_skipped
    go_client -->|"请求异常"| mq_skipped
    article_pending -->|"保存异常"| mq_skipped
    article_documents -->|"异常"| mq_skipped
    article_index -->|"异常"| mq_skipped
    article_mark -->|"异常"| mq_skipped
    mq_skipped --> retry_count
    retry_count --> retry_limit
    retry_limit -->|"未达到"| retry_raise
    retry_raise --> mq_requeue
    mq_requeue --> mq_backoff
    mq_backoff -.->|"后续再次消费"| mq_delivery
    retry_limit -->|"达到"| failure_record
    failure_record --> mq_ack

    %% 未捕获异常不属于有界 skipped 重投的正常出口。
    failure_record -->|"登记本身失败等"| mq_unexpected
    mq_unexpected -.-> rabbitmq
```

</details>

这里的 ACK（消息确认）**不等于成功入库**：非法消息、重复文章、404，以及达到失败上限后，都会正常结束并 ACK。代码没有把这些失败消息转入死信队列。

失败次数保存在进程内，重启后重新计数；`event_id` 用于日志和失败登记，实际重复判断依据是 `article_id`。图中的确认和拒绝动作以消息通道可用为前提，连接中断时不能保证确认已经送达。

源码：[article_consumer.py:95](../../../app/services/article_consumer.py#L95)、[article_consumer.py:202](../../../app/services/article_consumer.py#L202)、[article_consumer.py:228](../../../app/services/article_consumer.py#L228)、[article_consumer.py:259](../../../app/services/article_consumer.py#L259)。ACK／拒绝行为另核对了本地依赖：message.py:567（本地参考：`.venv/Lib/site-packages/aio_pika/message.py:567`）。

---

**入口三：启动恢复与空库初始化，顺序不能交换。**

<!-- readme-diagram:04-knowledge-ingestion-03 -->
![启动恢复已有知识](../png/04-knowledge-ingestion-03.png)

<details>
<summary>展开原始完整流程</summary>

```mermaid
flowchart TB
    startup["lifespan 启动<br/>前置配置校验通过"]
    knowledge_read["kb.restore<br/>从 knowledge.sqlite3 读取分块原文与元数据"]
    knowledge_restore["直接重建 Document<br/>不读取原上传文件，不重新解析或分块<br/>调用共享索引子流程：persist=false"]
    startup_failure["恢复异常向外传播<br/>本次应用启动失败"]
    sample_check{"样例文件存在且<br/>当前 kb.chunk_count=0？"}
    sample_ingest["导入指定 data/knowledge_base.md<br/>解析、Markdown 分块<br/>调用共享索引子流程：persist=true"]
    sample_warning["样例导入失败<br/>记录 warning，继续启动"]

    consumer_create["创建 ArticleIngestConsumer<br/>打开文章状态数据库"]
    article_rows["consumer.restore<br/>读取本地 pending / ingested 文章记录"]
    article_loop{"还有下一篇待恢复文章？"}
    article_restore["用本地正文重新构造文章分块<br/>不调用 Go 服务，不消费 MQ 消息<br/>调用共享索引子流程：persist=true"]
    article_result{"本篇恢复是否成功？"}
    article_mark["标记 ingested<br/>加入当前进程已处理集合<br/>清除该文章失败登记"]
    article_warning["记录本篇恢复异常<br/>保留数据，继续下一篇"]

    mq_enabled{"是否配置 AMQP_URL？"}
    mq_start["创建后台消费任务<br/>连接 RabbitMQ、声明交换机与队列<br/>连接失败由后台监督循环处理"]
    mq_disabled["不启动 MQ 消费任务"]
    startup_ready["启动流程 yield<br/>允许服务接收请求<br/>不代表所有外部依赖已就绪"]

    startup --> knowledge_read
    knowledge_read --> knowledge_restore
    knowledge_read -->|"异常"| startup_failure
    knowledge_restore -->|"异常"| startup_failure
    knowledge_restore -->|"成功，含 0 块"| sample_check
    sample_check -->|"是"| sample_ingest
    sample_check -->|"否"| consumer_create
    sample_ingest -->|"成功"| consumer_create
    sample_ingest -->|"异常"| sample_warning
    sample_warning --> consumer_create

    %% 样例判断发生在文章状态恢复之前。
    consumer_create --> article_rows
    article_rows --> article_loop
    article_loop -->|"有"| article_restore
    article_restore --> article_result
    article_result -->|"成功，含重复返回 0"| article_mark
    article_result -->|"本篇异常"| article_warning
    article_mark --> article_loop
    article_warning --> article_loop
    article_loop -->|"无"| mq_enabled

    %% 即使没有 AMQP_URL，上面的本地文章恢复仍然执行。
    mq_enabled -->|"已配置"| mq_start
    mq_enabled -->|"未配置"| mq_disabled
    mq_start --> startup_ready
    mq_disabled --> startup_ready
```

</details>

`kb.restore` 恢复的是**已经保存的分块**，仍可能重新调用向量服务构建索引；`consumer.restore` 恢复的是**文章正文**，会重新分块，但相同分块已被前一步恢复时，会在共享流程中去重，跳过再次向量化。

“空库”判断实际只看当前 `kb.chunk_count`，不是扫描整个 `data` 目录或统计外部 Milvus 集合。样例检查先于文章恢复，所以即使文章状态库里有旧文章，此时分块数为零仍可能先导入样例。

源码：[main.py:36](../../../app/main.py#L36)、[retriever.py:186](../../../app/rag/retriever.py#L186)、[article_consumer.py:142](../../../app/services/article_consumer.py#L142)、[article_consumer.py:173](../../../app/services/article_consumer.py#L173)。

---

**共享索引子流程：先保存分块，再更新向量索引，最后更新关键词索引与进程状态。**

<!-- readme-diagram:04-knowledge-ingestion-04 -->
![共享索引写入顺序](../png/04-knowledge-ingestion-04.png)

<details>
<summary>展开原始完整流程</summary>

```mermaid
flowchart TB
    ingest_docs["进入 kb._ingest_docs<br/>持有知识库 RLock<br/>与同一 kb 的检索操作互斥"]
    chunk_key["计算分块稳定 ID<br/>SHA-256：分块正文 + 完整元数据<br/>先去掉本批次重复项"]
    pending_check{"排除当前进程 _indexed_ids 后<br/>是否仍有待索引分块？"}
    no_new_chunks["返回 0<br/>没有新增索引<br/>可能是重复数据，也可能根本没有分块"]

    persist_check{"persist=true？"}
    knowledge_commit["knowledge.sqlite3<br/>INSERT OR IGNORE 保存原文和元数据<br/>SQLite 事务在此提交"]
    ensure_store["取得向量后端<br/>默认 InMemoryVectorStore<br/>可选 Milvus<br/>旧 Milvus 自动主键集合直接报错"]
    bm25_prepare["BM25.prepare<br/>仅为待索引文本分词并准备词频<br/>此时尚未修改 BM25 索引"]

    subgraph vector_write["向量后端写入：带应用层重试"]
        vector_backend{"向量后端"}
        memory_vector["默认 InMemoryVectorStore.add_documents<br/>调用 Embedding 服务批量文本向量化<br/>按稳定 ID 写入内存向量索引"]
        milvus_vector["可选 Milvus，配置 Embedding 函数<br/>无集合：add_documents<br/>已有集合：upsert<br/>按稳定 ID 写入外部向量索引"]
    end

    bm25_update["BM25.add_prepared<br/>增量更新进程内关键词索引"]
    memory_update["追加 _documents<br/>更新 _indexed_ids 和 chunk_count<br/>revision + 1"]
    indexed_ready["本批新增分块完成索引<br/>返回新增数量给所属入口"]
    search_ready["后续 search_knowledge<br/>调用 kb.search_detailed 召回<br/>查询时才进行排名融合与可选重排"]
    ingest_failure["异常向所属入口传播<br/>此前提交的 SQLite 分块不会自动回滚<br/>向量侧也可能已有部分写入"]

    ingest_docs --> chunk_key
    chunk_key --> pending_check
    pending_check -->|"否"| no_new_chunks
    pending_check -->|"是"| persist_check
    persist_check -->|"是"| knowledge_commit
    persist_check -->|"否：分块恢复入口"| ensure_store
    knowledge_commit ==> ensure_store
    ensure_store --> bm25_prepare
    bm25_prepare --> vector_backend
    vector_backend -->|"inmemory"| memory_vector
    vector_backend -->|"milvus"| milvus_vector

    %% 只有向量写入返回成功，代码才继续更新 BM25 和索引完成标记。
    memory_vector ==> bm25_update
    milvus_vector ==> bm25_update
    bm25_update ==> memory_update
    memory_update --> indexed_ready
    indexed_ready --> search_ready

    knowledge_commit -->|"异常"| ingest_failure
    ensure_store -->|"异常"| ingest_failure
    bm25_prepare -->|"异常"| ingest_failure
    memory_vector -->|"重试后仍失败"| ingest_failure
    milvus_vector -->|"重试后仍失败"| ingest_failure
    bm25_update -->|"异常"| ingest_failure
    memory_update -->|"异常"| ingest_failure
```

</details>

源码：[retriever.py:133](../../../app/rag/retriever.py#L133)、[retriever.py:149](../../../app/rag/retriever.py#L149)、[lexical.py:33](../../../app/rag/lexical.py#L33)、[retriever.py:275](../../../app/rag/retriever.py#L275)。默认向量后端内部的向量化顺序已核对：in_memory.py:188（本地参考：`.venv/Lib/site-packages/langchain_core/vectorstores/in_memory.py:188`）。

---

需要保留的几个边界：

| 情况 | 实际处理 |
|---|---|
| 重复文件或分块 | 按“正文＋完整元数据”的哈希去重，不是只比较正文；标题、分块位置等变化可能产生新数据 |
| 同名文件内容改变 | 新分块追加，代码没有按文件名删除旧版本，不属于覆盖导入 |
| SQLite 已有分块 | 不代表当前进程已经完成索引；是否跳过索引取决于 `_indexed_ids` |
| 文件解析后没有文本 | 上传字节非空仍可能得到 0 分块，正常返回新增 0 |
| 文章正文为空 | `build_article_docs` 返回空列表；消费者仍可标记 `ingested` 并 ACK，但不会新增可检索内容 |
| 向量化失败 | 可能已有持久化分块，BM25 和完成标记尚未更新；没有跨 SQLite、向量库和内存的统一事务 |
| 达到文章失败上限 | 保存失败登记后 ACK；只有已经保存正文的文章能在启动恢复时重试，仅有失败登记不会自动重新抓取 |
| 历史回填、文章更新或删除 | 没有主动回填与同步流程；事件重投读取既有文章记录时也不会重新获取最新正文 |

三个入口均直接调用知识库，不经过聊天智能体，也不调用生成模型；Embedding（文本向量化）是索引写入的外部依赖。
