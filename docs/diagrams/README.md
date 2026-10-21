# AI-Robot 架构与流程图

9 个主题、27 张 README 简版图，统一采用 Notion 极简风。每张只展示主链与关键分支；详细条件、异常、阈值和源码位置见对应说明。

直接打开 [图册](index.html) 浏览，或按下方主题阅读。PNG 可直接嵌入 Markdown；SVG 可无损放大，Mermaid 可编辑。

## 整体架构

![三条业务主线](png/01-architecture-01.png)

[SVG](svg/01-architecture-01.svg) · [Mermaid](mermaid/01-architecture-01.mmd) · [完整说明](notes/01-architecture.md)

<details>
<summary>查看该主题的其他流程</summary>

### 索引与存储边界

![索引与存储边界](png/01-architecture-02.png)

[SVG](svg/01-architecture-02.svg) · [Mermaid](mermaid/01-architecture-02.mmd)

</details>

## 请求生命周期

![请求进入服务](png/02-request-lifecycle-01.png)

[SVG](svg/02-request-lifecycle-01.svg) · [Mermaid](mermaid/02-request-lifecycle-01.mmd) · [完整说明](notes/02-request-lifecycle.md)

<details>
<summary>查看该主题的其他流程</summary>

### 普通 JSON 返回

![普通 JSON 返回](png/02-request-lifecycle-02.png)

[SVG](svg/02-request-lifecycle-02.svg) · [Mermaid](mermaid/02-request-lifecycle-02.mmd)

### SSE 建立与结束

![SSE 建立与结束](png/02-request-lifecycle-03.png)

[SVG](svg/02-request-lifecycle-03.svg) · [Mermaid](mermaid/02-request-lifecycle-03.mmd)

### Go 任务执行与收尾

![Go 任务执行与收尾](png/02-request-lifecycle-04.png)

[SVG](svg/02-request-lifecycle-04.svg) · [Mermaid](mermaid/02-request-lifecycle-04.mmd)

</details>

## 普通聊天智能体

![普通聊天：缓存与智能体](png/03-chat-agent-01.png)

[SVG](svg/03-chat-agent-01.svg) · [Mermaid](mermaid/03-chat-agent-01.mmd) · [完整说明](notes/03-chat-agent.md)

<details>
<summary>查看该主题的其他流程</summary>

### 一轮只读工具调用

![一轮只读工具调用](png/03-chat-agent-02.png)

[SVG](svg/03-chat-agent-02.svg) · [Mermaid](mermaid/03-chat-agent-02.mmd)

</details>

## 知识入库

![管理员上传文件](png/04-knowledge-ingestion-01.png)

[SVG](svg/04-knowledge-ingestion-01.svg) · [Mermaid](mermaid/04-knowledge-ingestion-01.mmd) · [完整说明](notes/04-knowledge-ingestion.md)

<details>
<summary>查看该主题的其他流程</summary>

### 文章发布事件入库

![文章发布事件入库](png/04-knowledge-ingestion-02.png)

[SVG](svg/04-knowledge-ingestion-02.svg) · [Mermaid](mermaid/04-knowledge-ingestion-02.mmd)

### 启动恢复已有知识

![启动恢复已有知识](png/04-knowledge-ingestion-03.png)

[SVG](svg/04-knowledge-ingestion-03.svg) · [Mermaid](mermaid/04-knowledge-ingestion-03.mmd)

### 共享索引写入顺序

![共享索引写入顺序](png/04-knowledge-ingestion-04.png)

[SVG](svg/04-knowledge-ingestion-04.svg) · [Mermaid](mermaid/04-knowledge-ingestion-04.mmd)

</details>

## RAG 检索

![从查询到检索证据](png/05-rag-retrieval-01.png)

[SVG](svg/05-rag-retrieval-01.svg) · [Mermaid](mermaid/05-rag-retrieval-01.mmd) · [完整说明](notes/05-rag-retrieval.md)

<details>
<summary>查看该主题的其他流程</summary>

### 证据返回与最终生成

![证据返回与最终生成](png/05-rag-retrieval-02.png)

[SVG](svg/05-rag-retrieval-02.svg) · [Mermaid](mermaid/05-rag-retrieval-02.mmd)

</details>

## Go 专用任务编排

![Go 专用任务的两条分支](png/06-go-orchestration-01.png)

[SVG](svg/06-go-orchestration-01.svg) · [Mermaid](mermaid/06-go-orchestration-01.mmd) · [完整说明](notes/06-go-orchestration.md)

<details>
<summary>查看该主题的其他流程</summary>

### 多智能体：两个角色顺序协作

![多智能体：两个角色顺序协作](png/06-go-orchestration-02.png)

[SVG](svg/06-go-orchestration-02.svg) · [Mermaid](mermaid/06-go-orchestration-02.mmd)

### 服务端成功与修复门禁

![服务端成功与修复门禁](png/06-go-orchestration-03.png)

[SVG](svg/06-go-orchestration-03.svg) · [Mermaid](mermaid/06-go-orchestration-03.mmd)

</details>

## Go 沙箱验证

![Go 代码进入隔离验证](png/07-go-sandbox-01.png)

[SVG](svg/07-go-sandbox-01.svg) · [Mermaid](mermaid/07-go-sandbox-01.mmd) · [完整说明](notes/07-go-sandbox.md)

<details>
<summary>查看该主题的其他流程</summary>

### 容器内的四阶段检查

![容器内的四阶段检查](png/07-go-sandbox-02.png)

[SVG](svg/07-go-sandbox-02.svg) · [Mermaid](mermaid/07-go-sandbox-02.mmd)

### 验证结束后的资源清理

![验证结束后的资源清理](png/07-go-sandbox-03.png)

[SVG](svg/07-go-sandbox-03.svg) · [Mermaid](mermaid/07-go-sandbox-03.mmd)

</details>

## 上下文管理

![上下文管理的三种模式](png/08-context-management-01.png)

[SVG](svg/08-context-management-01.svg) · [Mermaid](mermaid/08-context-management-01.mmd) · [完整说明](notes/08-context-management.md)

<details>
<summary>查看该主题的其他流程</summary>

### 摘要与模型输入预算

![摘要与模型输入预算](png/08-context-management-02.png)

[SVG](svg/08-context-management-02.svg) · [Mermaid](mermaid/08-context-management-02.mmd)

### 工具结果精简与证据复用

![工具结果精简与证据复用](png/08-context-management-03.png)

[SVG](svg/08-context-management-03.svg) · [Mermaid](mermaid/08-context-management-03.mmd)

### 按需补读完整工具结果

![按需补读完整工具结果](png/08-context-management-04.png)

[SVG](svg/08-context-management-04.svg) · [Mermaid](mermaid/08-context-management-04.mmd)

</details>

## 验证、评测与功能启用

![验证机制、集成与真实效果](png/09-verification-evaluation-01.png)

[SVG](svg/09-verification-evaluation-01.svg) · [Mermaid](mermaid/09-verification-evaluation-01.mmd) · [完整说明](notes/09-verification-evaluation.md)

<details>
<summary>查看该主题的其他流程</summary>

### Go 多智能体对照评测

![Go 多智能体对照评测](png/09-verification-evaluation-02.png)

[SVG](svg/09-verification-evaluation-02.svg) · [Mermaid](mermaid/09-verification-evaluation-02.mmd)

### 上下文四组对照与验收

![上下文四组对照与验收](png/09-verification-evaluation-03.png)

[SVG](svg/09-verification-evaluation-03.svg) · [Mermaid](mermaid/09-verification-evaluation-03.mmd)

</details>

## 编辑与重新生成

- `readme_specs.py`：27 张简版图的节点、连接和布局。
- `notes/`：原始完整说明；默认展示新图，原 Mermaid 流程折叠保留。
- `render.cjs`：本地批量生成 SVG、PNG、缩略图和图册。
- `svg-validation.json`、`render-report.json`：构图与导出检查结果。

使用 Node.js 运行 `render.cjs`。可通过 `DIAGRAM_PYTHON`、`DIAGRAM_RUNTIME_MODULES`、`DIAGRAM_FONT`、`FIREWORKS_SKILL_ROOT` 指定本机依赖。

本目录是技术文档图示，不代表当前运行环境已启用可选功能，也不将历史评测结果视为当前版本认证。
