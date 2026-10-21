当前检索链是 **`search_knowledge → kb.search_detailed → 返回原文证据`**；生成回答由普通聊天智能体另行调用模型完成。

已核对相关实现，未修改代码、未读取 `.env`。下面数量均为代码默认值，不代表当前运行配置。

---

**主图：混合检索顺序执行，重排失败才明确保留原排序。**

<!-- readme-diagram:05-rag-retrieval-01 -->
![从查询到检索证据](../png/05-rag-retrieval-01.png)

<details>
<summary>展开原始完整流程</summary>

```mermaid
flowchart TB
    query_input["查询输入 query<br/>search_knowledge_tool 实际执行时进入"]
    search_entry["run_blocking 调用 search_knowledge<br/>进入 kb.search_detailed<br/>使用已有索引，持有知识库锁<br/>最终数量 K 默认取 TOP_K=5"]
    hybrid_check{"HYBRID_ENABLED=true<br/>且 BM25.ready=true？"}

    subgraph recall_layer["召回：向量先执行，关键词后执行"]
        vector_hybrid["向量召回 search_vector<br/>后端将查询文本向量化，再 similarity_search<br/>HYBRID_VECTOR_TOP_K 默认 15"]
        bm25_recall["关键词召回 search_bm25<br/>jieba 分词 → BM25 排名<br/>从内存 _documents 取回文档<br/>HYBRID_BM25_TOP_K 默认 15"]
        vector_only["纯向量召回 search_vector<br/>查询向量化 → similarity_search<br/>直接请求 K 条，默认 5<br/>不执行 BM25 与排名融合"]
    end

    subgraph fusion_layer["排名融合"]
        rank_fusion["RRF：倒数排名融合<br/>按 metadata.doc_id 汇总排名贡献<br/>每次贡献为 1 / (60 + 排名)<br/>HYBRID_FUSION_TOP_K 默认最多 10"]
        candidate_docs["按融合后的 ID 取回文档<br/>任一路正常返回空列表时<br/>另一侧结果仍可进入融合"]
    end

    subgraph rerank_layer["可选语义重排"]
        rerank_enabled{"RERANK_ENABLED？<br/>代码默认 true<br/>Docker 默认 false"}
        candidates_empty{"候选列表为空？"}
        reranker_ready{"Reranker.ready<br/>缓存模型，或尝试加载<br/>BAAI/bge-reranker-base"}
        reranker_score["CrossEncoder 对 query、文档成对打分<br/>输入 max_length=512，代码固定<br/>按分数降序排序，取前 K 条"]
        original_order["保留进入重排前的顺序<br/>返回前 K 条<br/>加载或打分异常时记录 warning"]
    end

    result_clip["统一执行 docs[:K]<br/>默认最多 5 条，不足时原样返回<br/>不补齐，也没有最低相关性过滤"]
    retrieval_result["返回 docs 与 detail<br/>包含各阶段数量、耗时和分支标记<br/>空列表同样属于正常返回"]
    retrieval_failure["检索异常向工具调用层传播<br/>不自动切换另一种召回方式"]

    query_input --> search_entry
    search_entry --> hybrid_check
    hybrid_check -->|"是"| vector_hybrid
    hybrid_check -->|"否：关闭混合或关键词索引未就绪"| vector_only

    %% 不是并行双路召回；向量调用抛错时，BM25 尚未执行。
    vector_hybrid -->|"正常返回，含空列表"| bm25_recall
    bm25_recall -->|"正常返回，含空列表"| rank_fusion
    rank_fusion --> candidate_docs
    candidate_docs --> rerank_enabled
    vector_only -->|"正常返回，含空列表"| rerank_enabled

    vector_hybrid -->|"初始化异常或查询重试后仍失败"| retrieval_failure
    vector_only -->|"初始化异常或查询重试后仍失败"| retrieval_failure
    bm25_recall -->|"异常：不保留已取得的向量结果"| retrieval_failure
    rank_fusion -->|"异常"| retrieval_failure

    rerank_enabled -->|"关闭"| result_clip
    rerank_enabled -->|"开启"| candidates_empty
    candidates_empty -->|"是：不加载、不打分"| result_clip
    candidates_empty -->|"否"| reranker_ready
    reranker_ready -->|"可用"| reranker_score
    reranker_ready -->|"依赖缺失或加载失败"| original_order
    reranker_score -->|"成功"| result_clip
    reranker_score -->|"打分异常"| original_order
    original_order --> result_clip
    result_clip --> retrieval_result
```

</details>

正常混合路径的数量关系是 **`最多15＋最多15 → 融合最多10 → 最终最多5`**。纯向量路径直接召回最多 5 条，再进行可选重排，没有额外扩大候选集。

源码：[retriever.py:275](../../../app/rag/retriever.py#L275)、[fusion.py:6](../../../app/rag/fusion.py#L6)、[lexical.py:50](../../../app/rag/lexical.py#L50)、[reranker.py:21](../../../app/rag/reranker.py#L21)。

---

**补图：检索证据如何返回智能体，以及上下文模式下的额外裁剪。**

<!-- readme-diagram:05-rag-retrieval-02 -->
![证据返回与最终生成](../png/05-rag-retrieval-02.png)

<details>
<summary>展开原始完整流程</summary>

```mermaid
flowchart TB
    agent_request["普通聊天单智能体<br/>请求 search_knowledge(query)"]
    context_mode{"CONTEXT_MODE=enforce？<br/>默认 off"}
    reuse_check{"精确检索缓存是否命中？<br/>同一会话、精确参数、知识版本与进程<br/>默认 TTL=600 秒"}
    reuse_result["复用原始检索结果<br/>本次不重新召回或重排"]
    actual_retrieval["实际执行主图检索流程"]
    retrieval_result["取得 docs 与 detail"]

    subgraph evidence_boundary["检索工具边界：只返回证据，不生成答案"]
        evidence_payload["search_knowledge 构造 JSON<br/>chunks：原文 text 与 source<br/>sources：资料来源列表<br/>retrieval：检索阶段指标"]
        empty_payload["若 docs 为空<br/>chunks=[]，sources=[]<br/>不是工具错误"]
        original_sources["工具调用层先提取原始 sources"]
        project_check{"是否 enforce？"}
        projected_evidence["保存完整工具原始结果<br/>证据去重、摘取片段、必要时省略内容<br/>返回 result_id、来源和 truncated 标记<br/>工具视图默认 ≤1500 Token<br/>可见证据正文总额默认 ≤4000 Token"]
        raw_evidence["off / observe<br/>保留工具原始 JSON<br/>此处没有额外正文字符或 Token 裁剪"]
        tool_message["回填 ToolMessage<br/>累积原始来源与工具步骤<br/>记录摘要仅截取前 240 字符<br/>该摘要不替代模型收到的工具内容"]
    end

    tool_failure["普通检索异常<br/>转为错误 ToolMessage<br/>tool_result.ok=false"]
    budget_failure["ContextBudgetExceeded<br/>直接上抛，退出图执行"]

    subgraph generation_boundary["生成回答边界"]
        chat_agent["返回 agent 继续规划<br/>可继续调用工具，或进入 finalize"]
        final_answer["finalize 另行调用生成模型<br/>依据历史与工具消息组织回答<br/>汇总来源随响应返回"]
    end

    agent_request --> context_mode
    context_mode -->|"否"| actual_retrieval
    context_mode -->|"是"| reuse_check
    reuse_check -->|"命中"| reuse_result
    reuse_check -->|"未命中"| actual_retrieval
    actual_retrieval -->|"成功"| retrieval_result
    actual_retrieval -->|"普通异常"| tool_failure
    retrieval_result --> evidence_payload
    reuse_result --> evidence_payload

    %% 空结果仍然回到智能体；没有在工具中强制返回固定拒答文案。
    evidence_payload -->|"空结果说明"| empty_payload
    evidence_payload --> original_sources
    original_sources --> project_check
    project_check -->|"是"| projected_evidence
    project_check -->|"否"| raw_evidence
    projected_evidence -->|"成功"| tool_message
    projected_evidence -->|"预算无法满足"| budget_failure
    projected_evidence -->|"普通异常"| tool_failure
    raw_evidence --> tool_message
    tool_message --> chat_agent
    tool_failure --> chat_agent
    chat_agent -->|"信息足够或达到工具轮次上限"| final_answer

    %% 检索与重排不调用生成模型；最终回答属于智能体编排层。
```

</details>

来源优先使用 `metadata.doc_id`，缺失时回退为 `标题#分块序号`。`enforce` 的模型结果视图最多保留 20 个来源，但图状态累积的是投影前提取的来源，最终再去重。

`enforce` 的裁剪与重排是两件事：前者限制模型可见证据，后者调整候选文档排序。超长代码片段可能被替换为补读提示，完整工具结果另存；存在补读线索时，智能体可使用 `read_tool_result`，单次结果默认最多 1000 Token（模型文本计量单位）。

源码：[tools.py:27](../../../app/agents/tools.py#L27)、[graph.py:163](../../../app/agents/graph.py#L163)、[evidence.py:23](../../../app/context/evidence.py#L23)、[tool_projection.py:43](../../../app/context/tool_projection.py#L43)、[tool_projection.py:105](../../../app/context/tool_projection.py#L105)。

---

**实际配置与固定参数：**

| 阶段 | 数量、开关及边界 |
|---|---|
| 最终数量 | `AIROBOT_TOP_K=5`；工具参数只有 `query`，没有对模型开放 `top_k` 参数 |
| 混合检索 | `AIROBOT_HYBRID_ENABLED=true`，还要求 `BM25.ready` |
| 混合路径向量召回 | `AIROBOT_HYBRID_VECTOR_TOP_K=15` |
| 关键词召回 | `AIROBOT_HYBRID_BM25_TOP_K=15`；BM25 的 `k1=1.5`、`b=0.75` 写死在代码中 |
| 排名融合 | `AIROBOT_HYBRID_FUSION_TOP_K=10`；RRF 平滑常数 `k=60` 是函数默认值，没有项目环境配置项，也没有融合权重配置 |
| 重排 | `AIROBOT_RERANK_ENABLED` 代码默认 `true`，Docker 默认 `false`；模型由 `AIROBOT_RERANK_MODEL` 指定 |
| 重排模型输入 | `CrossEncoder(max_length=512)` 写死，没有对应项目配置项 |
| 相关性过滤 | 本链路未设置向量最低分、重排最低分或 `score_threshold`；语义答案缓存的 `0.75` 门限不用于这里 |
| 向量调用重试 | 可重试异常默认最多尝试 3 次，含首次；后端初始化不在该查询重试包装内 |

配置依据：[config.py:121](../../../app/config.py#L121)、[config.py:152](../../../app/config.py#L152)、[resilience.py:18](../../../app/services/resilience.py#L18)、[Dockerfile:20](../../../Dockerfile#L20)。

这些数量限制针对**单次检索**，不是整次聊天的来源总数；智能体可进行多次工具调用。

---

**空结果与部分能力不可用的真实路径：**

| 情况 | 实际处理 |
|---|---|
| 混合检索关闭，或 BM25 没有可用倒排词项 | 走纯向量检索，跳过 BM25 和 RRF |
| 非 Milvus 后端且 `chunk_count=0` | `search_vector` 直接返回 `[]`，不调用向量服务 |
| Milvus 后端初始化成功，但集合不存在 | 向量召回返回 `[]`；这不同于连接失败或依赖缺失 |
| 向量正常返回 `[]`，BM25 有结果 | 混合流程继续，关键词结果可通过 RRF 返回 |
| BM25 正常返回 `[]`，向量有结果 | 混合流程继续，向量结果可通过 RRF 返回 |
| 向量调用抛错、Milvus 缺依赖或连接失败 | 异常上抛，不自动切换 BM25 或内存后端 |
| BM25 执行抛错 | 异常上抛，不使用已经取得的向量结果作回退 |
| 重排依赖缺失、模型加载或打分失败 | 保留重排前顺序，取前 K 条 |
| 最终结果为空 | 工具正常返回空证据，智能体继续规划；没有硬编码拒答 |
| `enforce` 证据预算不足 | 抛出预算异常，不伪装成空检索结果 |

`detail.rerank_enabled=true` 只表示进入了启用重排的分支，**不能证明模型实际加载或打分成功**。

`retriever.py` 虽然还定义了 `answer_with_rag` / `aanswer_with_rag` 这两个“检索后生成”的辅助函数，但当前普通聊天的 `search_knowledge` 工具链没有调用它们；上图的生成边界位于 [graph.py:231](../../../app/agents/graph.py#L231)，而不是检索工具内部。
