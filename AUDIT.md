# 代码评审与修复台账

> 视角：外部评审（Claude Code）。与作者自述的 [REVIEW.md](REVIEW.md) 互为补充——REVIEW.md 记"我改了什么"，本文记"发现了什么、怎么改的、判断依据是什么、还剩什么"。
>
> 覆盖范围：`24a5133`（LangGraph 迁移完成）→ 本次提交。
>
> **核对方式分三级，文中逐项标注**：
> - **读代码** = 静态确认实现已存在
> - **实跑** = 有命令输出为证
> - **未验证** = 缺密钥或外部服务，无法验证
>
> **现状标记**：✅ 彻底修复 ｜ ⚠️ 部分修复 ｜ ❌ 未修

---

## 1. 结论摘要

| 编号 | 问题 | 严重度 | 现状 |
|---|---|---|---|
| A1 | 索引入库三元组非原子，异常后 BM25 永久错位 | P0 | ✅ |
| A2 | 消息重投丢数据，进程崩溃后文章永久丢失 | P0 | ✅ |
| A3 | 模块导入即清空 Milvus 生产集合 | P0 | ✅ |
| A4 | 文章 ID 回退正则误识别（"Go 1.22" → 文章 1） | P1 | ✅ |
| A5 | 语义缓存无隔离、缓存动态数据 | P1 | ✅（第二轮修正过严） |
| B1 | 控制台存储型 XSS | P1 | ✅ |
| B2 | 上传无大小限制，整文件读内存 | P1 | ✅ |
| B3 | API 无鉴权，会话默认共用 "default" | P0 | ✅ |
| C1 | CI 门禁是假的（只跑一个测试文件） | P1 | ✅ |
| C2 | "流式"接口实际攒完才吐 | P1 | ✅ |
| C3 | 单次问答 3 次 LLM 调用 | P2 | ⚠️ 只修一半（作者已披露） |
| C4 | 同步操作阻塞事件循环，BM25 O(N²) | P1 | ✅ |
| R1 | **重投风暴**：下游宕机时无限高速重投 | P1 | ✅（第二轮新增） |
| R2 | **语义缓存被 `exact=True` 关掉** | P2 | ✅（第二轮新增） |
| R3 | JSON 接口请求体无上限 | P2 | ✅（第二轮新增） |
| R4 | 死代码 `_load_ingested_ids`（且是陷阱） | P3 | ✅（第二轮新增） |

**A/B/C 为第一轮 12 项必修问题，R1–R4 是第二轮**——其中 R1–R3 是上一轮修复自己引入或遗留的。

---

## 2. 第一轮：12 项必修问题

### A1 索引入库三元组非原子 · ✅ 已修

**原问题**：`ingest_text` / `ingest_article` 里三步操作顺序错误：

```python
self._documents.extend(docs)                        # ① 先改内存
invoke_with_retry(self._store.add_documents, docs)  # ② 网络调用，可能抛异常
self._bm25.add_documents([...])                     # ③ 抛了就永远不执行
```

而 `search_bm25` 返回的是**下标**，由 `self._documents[i]` 取值。②失败 → `_documents` 已变长但 BM25 没跟上 → 之后每次 BM25 检索都返回**错位的文档**，而且是静默的（不报错，只是答案错）。

**修法**：抽出单一入口 `_ingest_docs`（`app/rag/retriever.py:149`），先算内容哈希做幂等去重（`_indexed_ids`），向量写入成功后才更新内存数组与 BM25，整体用 `@locked`（RLock）保护。失败时抛异常但不留半成品，重试用相同内容重放即可。

**实跑**：`tests/test_hardening.py::test_vector_failure_keeps_local_indexes_atomic_and_recoverable` 通过。

### A2 消息重投丢数据 · ✅ 已修

**原问题**：RabbitMQ 事件处理失败就吞掉，进程崩溃时正在处理的文章永久丢失。

**修法**：`app/services/article_consumer.py` 用 SQLite（WAL）做两件事——`ingested_articles` 表存**文章正文**与处理状态（`pending`/`ingested`），启动时 `restore()` 从原文重放、重建两路索引；`message.process(requeue=True)` 保证失败重新入队。

**注意**：这条修复本身引入了 R1（见下）。

### A3 导入即清库 · ✅ 已修

**原问题**：`config.py` 有 `milvus_reset_on_start` 默认 `true`，且建库逻辑在**模块级**执行——`import app.rag.retriever` 就会 `drop_collection()`，测试、脚本、CI 只要引用到就清空生产集合。

**修法**：
- `milvus_reset_on_start` 整项删除，`config.py` 注释写明"启动、导入、实例化均不能删除集合"
- 建连推迟到真正读写时（`retriever.py:119` `_ensure_store`）
- 全仓库唯一残留的 `drop_collection` 在 `scripts/reset_collection.py:26`，且集合名必须匹配 `airobot_(eval|bench)_[0-9a-f]{32}`，碰不到生产集合
- 新增守卫（`retriever.py:123`）：旧集合若是自动主键，直接抛 `RuntimeError` 拒绝启动，而非静默清库

**实跑**：`grep -rn drop_collection` 全仓库仅一处；`test_old_auto_id_collection_is_rejected_without_drop` 通过。

### A4 文章 ID 误识别 · ✅ 已修

**原问题**：`_FALLBACK_ID_RE = re.compile(r"\b(\d{1,10})\b")` —— "Go 1.22 有什么新特性" 会提取出文章 ID `1`，触发一次错误的实时文章查询。

**修法**：删除回退正则，只保留 `_ARTICLE_ID_RE`（`app/agents/tools.py:21`），要求"文章/article + 数字"句式。测试补齐了三个反例。

### A5 语义缓存 · ✅ 已修（第二轮修正了过严）

**原问题**：缓存的 key 只有问题相似度，没有身份与知识库版本 → 跨用户串答案；且 `query_article` 这类动态数据也被缓存。

**修法**：
- `namespace` 按账户哈希隔离（跨账户不可能命中）
- `revision` 锁定知识库版本，入库后旧缓存自动失效
- `_cacheable()`（`app/services/chat.py:80`）只允许"有来源 + 全部成功 + 全部是 `search_knowledge`"，动态数据与混合工具组合一律不缓存
- 命中时同步写会话记忆（否则第二轮对话上下文缺失）
- `RLock` + `synchronized` 保护并发读写

**第二轮修正**：原实现给缓存查询传了 `exact=True`，要求问题文本逐字相同才可能命中——改写提问永远不会命中，等于把"语义"缓存降级成"精确"缓存。见 R2。

### B1 控制台存储型 XSS · ✅ 已修

**原问题**：`dashboard.html` 把 traces 里的 `message` / `session_id` / `engine` 直接插进 `innerHTML`，而 `message` 是用户输入。

**修法**：`escHtml()` 与 `escAttr()` 分开（属性值需额外转义引号），应用于全部渲染点——含作者自查补上的 `st.detail`。同时新增管理员令牌输入框与 `apiFetch()`，所有管理请求带 `Authorization`。

### B2 上传无大小限制 · ✅ 已修

**原问题**：`UploadFile` 整体读入内存，一个几 GB 的文件就能打爆服务。

**修法**：两道防线。`security.py:38-41` 在 **multipart 解析之前**限量（此时还没分配大缓冲），`main.py` 再按块读取并对**文件内容本身**精确限量（`max_upload_bytes`，默认 10 MiB）。

**第二轮修正**：这两道防线只覆盖了上传接口，`/api/v1/chat` 的 JSON body 仍然无上限——见 R3。

### B3 无鉴权 + 会话混用 · ✅ 已修

**原问题**：`/api/v1/chat` 匿名可用；`session_id` 默认值 `"default"`，所有用户共用同一份会话记忆。

**修法**：新增 `app/services/security.py`：

- **默认拒绝**：无有效凭据时 `/api/*` 一律 401；一个凭据都没配时 503（明确区分"配错了"和"没配"）
- **两类身份**：管理员（`Authorization: Bearer <AIROBOT_ADMIN_TOKEN>`）与可信网关（`X-Internal-Token` + `X-Account-Id`，账户 ID 需匹配 `[1-9][0-9]{0,19}`）
- **权限收敛**：网关只能访问 `/api/v1/chat` 与 `/api/v1/chat/stream`，管理接口一律 403
- **会话命名空间**：会话 key = `sha256(账户) + ":" + sha256(会话号)`，账户间无法互相覆盖
- **并发保护**：同一会话同时处理两条消息返回 409，`SessionStreamResponse` 在 `finally` 中释放锁
- `docker-compose.yml` 从 `"8000:8000"` 改为 `127.0.0.1:8000:8000`

**部署耦合（重要）**：此项要求 Go 网关配置 `AI_INTERNAL_TOKEN` 且两侧一致，否则线上直接 401。详见第 4 节。

### C1 CI 门禁 · ✅ 已修

**原问题**：CI 只跑 `test_stability.py`，另外三个测试文件和评测脚本根本不参与，改坏了也不拦。

**修法**：CI 现在跑全部 5 个测试文件 + `eval/run_agent_eval.py`，评测带真实阈值 `--min-baseline-hit-rate 0.85 --min-judge-score 3.5`，未达标 `sys.exit(1)`；制品上传用 `always()` 保证失败也能拿到报告。

**注意**：评测步骤在未配置仓库 Secrets 时会**跳过**（`ci.yml` 的 env 判断），此时门禁不生效。这是有意设计，但意味着"CI 绿"不等于"评测通过"。

### C2 假流式 · ✅ 已修

**原问题**：`/api/v1/chat/stream` 先跑完整张图拿到最终答案，再伪装成流式逐块发送——首字延迟等于完整生成时间。

**修法**：`_finalize_node`（`app/agents/graph.py:168-185`）在流式模式下用 `get_stream_writer()` 逐块转发模型输出；调用方用 `stream_mode=["updates", "custom"]` 双模式消费（`app/services/chat.py:206-208`），`updates` 拿图状态、`custom` 拿 token。规划文本与工具参数不转发，避免泄露提示词结构。

**取消安全**：用 `aclosing` 保证客户端断开时关闭图执行；记忆只在完整成功后写入，错误或取消不留半截答案。

**实跑**：`test_stream_tokens_arrive_before_final_generation_completes`、`test_closing_stream_cancels_graph_without_committing_memory` 通过。

### C3 三次 LLM 调用 · ⚠️ 只修一半（作者已在 REVIEW.md:38 披露）

**原问题**：每次问答 3 次模型调用，其中一次是藏在工具内部的隐藏生成（黑盒双扣）。

**现状**：工具内的隐藏生成**已移除**（`search_knowledge` 只返回 chunks + sources，不调模型），但调用次数没降——现在是"规划 → 工具 → 再规划 → 最终生成"，单工具路径仍是 3 次。

**实测**（`eval/run_agent_eval.py` 输出）：

```
单工具路径：model_calls: 3, tool_rounds: 1
直接回答：  model_calls: 2, tool_rounds: 0
```

**评审结论：这是设计取舍，不是缺陷。** 第二次规划调用是为了让模型决定"是否还要调更多工具"，轮次到顶时已不再多花一次规划（`graph.py:98-101`）。若强行压到 2 次，做法是第二次规划返回空工具调用时直接拿它的 content 当最终答案——代价是规划提示词的文风漏进用户答复，而这正是当初拆开两个节点的理由。**建议保持现状。**

### C4 阻塞事件循环 + BM25 O(N²) · ✅ 已修

**原问题**：文件解析、向量入库是同步阻塞调用，直接在 async 路由里执行会卡死整个事件循环；BM25 每次入库都整体重建语料，O(N²)。

**修法**：
- `app/services/concurrency.py:5` `run_blocking()`：用 `asyncio.shield` 包住线程任务，取消时**等线程做完再释放资源**（否则临时文件/SQLite 连接会在使用中被回收）
- `app/rag/lexical.py` 改为增量索引：`prepare()` 只对新文档分词，维护倒排表 `_postings` 与文档长度，检索只遍历命中词的文章（O(df) 而非 O(N)）
- IDF 改用正值公式 `log1p((n - df + 0.5)/(df + 0.5))`，避免小语料负分导致零召回

**副作用（需关注）**：IDF 变正后排名与分数会变，应通过真实检索评测比对质量。见第 4 节。

---

## 3. 第二轮：修复自身引入/遗留的 4 项（R1–R4）

### R1 重投风暴 · ✅ 已修（第一轮 A2 引入）

**问题**：A2 的修法是 `message.process(requeue=True)` + 失败抛异常。但 RabbitMQ 对 requeue **没有内建延迟**——抛异常 → 立刻重投 → 立刻再失败，形成高速循环。而 `"skipped"` 恰好包含"Go 服务宕机"这个必然场景（`_handle_event` 捕获 `GoServiceError` 后返回 skipped）。

**后果**：Go 服务宕机一小时，AI 侧会以每秒数百次的速度循环重投同一条消息，每次都去请求已经挂掉的对端——把故障从"数据丢失"放大成"打爆对端"。

**修法**（`app/services/article_consumer.py`）：

- 新增 `RetryLater(RuntimeError)`（`:29`），携带 `delay`；继承 `RuntimeError` 以兼容按父类捕获的调用方
- 失败计数器 `_attempts`（内存态，重启即清零，与 `restore()` 的语义一致）
- 指数退避 `_retry_delay()`（`:128`）：`base * 2^(attempt-1)`，默认 2s/4s/8s/16s，封顶 30s
- 退避在消费者循环里 `asyncio.sleep(exc.delay)`，此时消息已重新入队，只是先不取下一轮
- 超过 `AIROBOT_AMQP_MAX_RETRIES`（默认 5）后**停止重投**，登记到 `ingest_failures` 表并放行
- 登记数通过 `/health` 的 `ingest_failed_events` 暴露，运维可见，不是静默丢数据
- 成功入库时清除失败登记与计数器

**实跑**：`test_consumer_retries_are_bounded_and_back_off` —— 断言退避为 `[1.0, 2.0]`、`failed_event_count` 从 1 归 0、计数随成功清零。

**未验证**：退避只是 `asyncio.sleep`，**没有接真实 RabbitMQ 验证过重投时序**。另外单条毒消息退避期间会占用消费位（prefetch 内已投递的消息排队等待），吞吐要求高时应改为死信队列 + TTL 重试队列。

### R2 语义缓存被 `exact=True` 关掉 · ✅ 已修（第一轮 A5 修过头）

**问题**：`_cache_lookup` 给 `semantic_cache.get` 传了 `exact=True`，而 `get()` 里 `if exact and item["query"] != query_text: continue` —— 只有问题文本**逐字相同**才可能命中。用户换个说法就永远不命中，语义缓存的主要收益归零，只剩"重复问同一个问题"这一种几乎无价值的情况。

**实测对比**（缓存里存"Go 的 context 如何取消"，查询"Go 并发代码里 context 怎么取消任务"）：

```
旧行为 exact=True  -> None          ← 改写提问不命中
新行为 默认        -> {'reply': '语义答案'}
新行为 跨账户      -> None          ← 隔离依然有效
```

**修法**：去掉 `exact=True`。三层防护已经足够——namespace 按账户哈希隔离、revision 锁定知识库版本、`get()` 内再要求余弦相似度与词面重叠**双门限**通过。`exact` 参数本身保留（API 未变），只是不再使用。

**⚠️ 这是评审推翻作者刻意决定的一处**。作者在 REVIEW.md:9 明确写了"相同问题、认证身份、知识版本才可命中"，若当时有特定理由（例如实测到误命中），把 `chat.py:55-60` 的注释删掉、并在 `semantic_cache.get(...)` 调用里加回 `exact=True` 即可还原。

**残留风险**：误命中现在只由 `AIROBOT_CACHE_LEXICAL_THRESHOLD`（默认 0.5）把关。该阈值用"交集 / 较小集合"计算，**缓存侧问题较短时偏松**（缓存 3 个词、新问题 10 个词且这 3 个词都在，重叠率算 1.0）。要更保守就把阈值调到 0.7。本次未改动词面重叠公式，以免影响既有语义与测试。

### R3 JSON 接口请求体无上限 · ✅ 已修（第一轮 B2 遗留）

**问题**：大小限制只覆盖了 `/api/v1/ingest`。`/api/v1/chat` 的 JSON body 无上限，鉴权通过后仍可送 1 GB 让 Pydantic 整块吃进内存。`ChatRequest.message` 虽然有 `max_length=16000`，但那是**读完之后**才校验的。

**修法**：把原来的 buffer-and-replay 逻辑抽成 `_forward_with_limited_body`（`app/services/security.py:45`），现在覆盖所有 `POST/PUT/PATCH`：上传接口按文件上限 + multipart 开销，其余按 `AIROBOT_MAX_REQUEST_BYTES`（默认 256 KiB）。无 `Content-Length` 的分块传输按实际字节数累计拦截。

**实跑**：`test_json_body_limit_before_parser` —— 断言超长请求返回 **413 而不是 422**（422 说明是 Pydantic 拦的，413 才证明中间件先跑）；同时断言正常请求仍能通过、`chat` 只被调用一次。

### R4 死代码 `_load_ingested_ids` · ✅ 已修（差点修坏）

**问题**：`_load_ingested_ids` 定义了从未调用。

**关键**：本想"补上遗漏的调用"把它接进构造流程——**读懂了用途才发现结论正好相反**。`_ingested_article_ids` 是 `restore()` 判断"本进程内已重建过索引的文章"的依据，一旦在构造时用数据库状态预填充，重启后 `restore()` 会跳过全部文章，进程内向量库与 BM25 索引根本建不起来——**RAG 会静默返回空**。

**修法**：删掉这个方法，并在那个空集合旁写明为什么必须从空集开始（`article_consumer.py:62-65`）。跨进程去重的权威来源是数据库状态，不是这个内存集合。

---

## 4. 遗留问题

### 4.1 未验证事项（不是"已解决"，是"没条件验证"）

| 事项 | 原因 |
|---|---|
| **真实模型质量** | 本地 LLM / Embedding 密钥为空，全部评测用替身模型跑，**不代表真实回答质量** |
| CI 评测门禁 | 未配置仓库 Secrets 时评测步骤跳过，`--min-judge-score 3.5` 这条线是空的 |
| 真实 Milvus / RabbitMQ 联调 | 未连接真实服务验收（含 R1 的退避时序） |
| RAGAS 端到端 | 同上，需密钥 |

**这是当前最大的缺口**：所有"质量"结论都是替身模型下的结构性验证，不是真实效果。

### 4.2 已知设计限制（有意的，但要知道）

| 事项 | 说明 |
|---|---|
| **单实例部署** | `inmemory` 向量库不跨进程共享，**不要部署多个索引进程/worker**。消费者必须跑在 API 进程内 |
| **冷启动开销** | 重启要从 SQLite 原文重新向量化，数据量大时启动慢（不丢数据）。冷启动优化不在已完成范围内 |
| **C3 三次调用** | 见上文，建议保持；如需降本按 C3 的方案改，但会牺牲答复质量 |
| **BM25 排名变化** | IDF 改用正值后排名/分数与历史不可比，需用真实检索评测重新确认质量 |
| **`/api/*` 全关闭** | 两个令牌都不配时全部 503。控制台需要手填管理员令牌，否则刷新无数据 |

### 4.3 跨仓库契约问题（低优先级）

**`X-Account-Id: 0` 会被拒**：Go 侧 `proxy.go:106` 在 accountID 缺失/为 0 时发送字符串 `"0"`，而 AI 侧正则 `[1-9][0-9]{0,19}` 不接受 0 → 返回 401。正常 JWT 的账户 ID ≥ 1，所以只在异常令牌下触发。若要收紧，两侧应统一"缺失时不发送该头"的约定。

### 4.4 尚未覆盖的低等级建议

命名、注释密度、可读性一类问题未在此逐条列出。核心逻辑（索引原子性、缓存隔离、鉴权边界、并发与取消）已全部覆盖。

---

## 5. 上线前必做配置

### 5.1 Milvus

当前 `AIROBOT_VECTOR_STORE` 取默认值 `inmemory`，**Milvus 未参与，无需迁移**。

若将来切换到 `milvus`：**空集合也必须删掉或改名**，因为 `retriever.py:123` 的守卫只看 schema 的 `auto_id` 标志，不看有没有数据：

```bash
python -c "from pymilvus import MilvusClient; MilvusClient(uri='http://localhost:19530').drop_collection('airobot_kb')"
```

`scripts/reset_collection.py` 会拒绝删这个集合名（只允许 `airobot_eval_*` / `airobot_bench_*`），只能手工删或改 `AIROBOT_MILVUS_COLLECTION`。

### 5.2 令牌

**本质是"一个共享口令 + 一个独立管理口令"。** Go 侧只有一个 `cfg.AI.InternalToken`，同时用于两个方向：校验进来的 `/internal/ai` 调用（`router.go:91`），以及代理出去时盖章 `X-Internal-Token`（`proxy.go:105`）。所以 AI-Robot 必须用同一个值填两个变量：

| 变量 | 配在哪 | 取值 |
|---|---|---|
| `AI_INTERNAL_TOKEN` | Go 侧 | **口令 G** |
| `AIROBOT_AI_INTERNAL_TOKEN` | AI-Robot | **口令 G**（校验 Go 送来的头） |
| `AIROBOT_GO_INTERNAL_TOKEN` | AI-Robot | **口令 G**（调 Go `/internal/ai`） |
| `AIROBOT_ADMIN_TOKEN` | AI-Robot | **口令 A**（必须与 G 不同，`main.py:33` 会强制） |

生成：`openssl rand -hex 32`（生成两次，得到两个不同的值）。

**联合 docker compose（推荐）** —— 一致性是构造上成立的，AI-Robot 的 compose 里三处都指向同一个 `${AI_INTERNAL_TOKEN}`，因此**只填 Go 仓库那一份 `.env`**：

```bash
cd csdn_article_go
cp .env.example .env
# .env 中填：AI_INTERNAL_TOKEN / AIROBOT_ADMIN_TOKEN（注意管理员令牌是配在 Go 仓库的 .env 里）
#            AIROBOT_LLM_API_KEY / AIROBOT_EMBEDDING_API_KEY（不填则容器起来也答不了话）
docker compose --profile app up -d --build
```

**此路径下 AI-Robot 自己的 `.env` 不参与**：Dockerfile 只 COPY `app`/`data`/`.env.example`，`.dockerignore` 排除了 `.env`；且 `load_dotenv()` 默认 `override=False`，即使存在也不会盖掉 compose 注入的值。

**分别手动跑** —— AI-Robot 侧 `.env` 填上述三个变量（G、G、A）；Go 侧 **`config.compose-local.yaml` 里没有 `ai:` 段**，只能用环境变量：

```bash
export AI_BASE_URL=http://127.0.0.1:8000
export AI_INTERNAL_TOKEN=<口令 G>
```

`AI_BASE_URL` 不设的话网关直接返回 503「AI 服务未启用」（`proxy.go:94`）。

### 5.3 验证命令

```bash
# 1 公开健康检查（含放弃重投的文章数）
curl -s localhost:8000/health | python -m json.tool
# 2 默认拒绝是否生效 -> 期望 401
curl -s -o /dev/null -w '%{http_code}\n' localhost:8000/api/v1/stats
# 3 管理员凭据是否生效 -> 期望 200
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $ADM" localhost:8000/api/v1/stats
# 4 模拟网关：证明 G 两侧一致 -> 期望 200（需模型密钥）
curl -s -H "X-Internal-Token: $GW" -H "X-Account-Id: 1" -H 'Content-Type: application/json' \
     -d '{"message":"文章 1 的数据"}' -X POST localhost:8000/api/v1/chat
```

第 4 条只证明 AI 侧认这个口令。**真正的一致性要端到端验**：走 Go 网关登录拿 JWT 后 POST `/ai/chat`——这条通了才说明 Go 盖章的值与 AI 校验的值相同。

---

## 6. 复现验证

```bash
cd AI-Robot
python -m compileall -q app eval scripts tests     # 语法

# 离线单测：6 + 12 + 5 + 3 + 26 = 52 项
python tests/test_stability.py
python tests/test_integration.py
python tests/test_agent.py
python tests/test_tracing.py
python -m unittest discover -s tests -p "test_hardening.py" -v

python eval/run_agent_eval.py                     # 离线 Agent 评测，6 类路径

python -c "from app.main import app; print(len(app.routes))"   # 导入冒烟
```

依赖见 `requirements.txt`；评测依赖见 `requirements-eval.txt`（含 RAGAS/torch，较重）。

---

## 7. 变更文件清单（本台账对应的提交）

| 文件 | 变更 |
|---|---|
| `app/services/article_consumer.py` | R1 有界重投 + 退避 + 失败登记；R4 删除死代码 |
| `app/services/security.py` | R3 请求体上限推广到全部 JSON 接口 |
| `app/services/chat.py` | R2 去掉 `exact=True` |
| `app/config.py` | 新增 `amqp_max_retries` / `amqp_retry_backoff_seconds` / `amqp_retry_max_backoff_seconds` / `max_request_bytes` |
| `app/main.py` | `/health` 上报 `ingest_failed_events` |
| `tests/test_hardening.py` | 新增 3 项回归（均在此次改动前不通过） |
| `.env.example` | 新配置项与说明 |
| `REVIEW.md` | 作者视角的第二轮记录 |
| `AUDIT.md` | 本文件 |
