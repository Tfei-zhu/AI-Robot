# -*- coding: utf-8 -*-
"""全局配置：全部从环境变量 / .env 读取，密钥不落盘。"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    try:
        load_dotenv(Path(__file__).resolve().parent.parent / ".env", encoding="utf-8-sig")
    except TypeError:
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass


def _env(key: str, default: str = "") -> str:
    val = os.getenv(key)
    return (val if val is not None else default).strip()


class Settings:
    # 大模型（OpenAI 兼容协议）
    llm_base_url: str = _env("AIROBOT_LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    llm_api_key: str = _env("AIROBOT_LLM_API_KEY")
    llm_model: str = _env("AIROBOT_LLM_MODEL", "qwen-plus")
    # Embedding
    embedding_base_url: str = _env("AIROBOT_EMBEDDING_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    embedding_api_key: str = _env("AIROBOT_EMBEDDING_API_KEY")
    embedding_model: str = _env("AIROBOT_EMBEDDING_MODEL", "text-embedding-v4")
    # Agent：每个请求最多允许的工具调用轮次，防止模型进入无限循环
    agent_max_tool_rounds: int = int(_env("AIROBOT_AGENT_MAX_TOOL_ROUNDS", "4"))
    # RAG
    top_k: int = int(_env("AIROBOT_TOP_K", "5"))
    chunk_size: int = int(_env("AIROBOT_CHUNK_SIZE", "400"))
    chunk_overlap: int = int(_env("AIROBOT_CHUNK_OVERLAP", "80"))
    # 会话记忆
    memory_max_turns: int = int(_env("AIROBOT_MEMORY_MAX_TURNS", "20"))
    memory_retrieve_turns: int = int(_env("AIROBOT_MEMORY_RETRIEVE_TURNS", "6"))
    # 检索工程（混合检索 + 重排）
    hybrid_enabled: bool = _env("AIROBOT_HYBRID_ENABLED", "true").lower() == "true"
    hybrid_vector_top_k: int = int(_env("AIROBOT_HYBRID_VECTOR_TOP_K", "15"))
    hybrid_bm25_top_k: int = int(_env("AIROBOT_HYBRID_BM25_TOP_K", "15"))
    hybrid_fusion_top_k: int = int(_env("AIROBOT_HYBRID_FUSION_TOP_K", "10"))
    rerank_enabled: bool = _env("AIROBOT_RERANK_ENABLED", "true").lower() == "true"
    rerank_model: str = _env("AIROBOT_RERANK_MODEL", "BAAI/bge-reranker-base")
    # 向量库后端：inmemory（默认，零依赖）| milvus（持久化 ANN，需 langchain-milvus + 运行中的 Milvus）
    vector_store: str = _env("AIROBOT_VECTOR_STORE", "inmemory").lower()
    milvus_uri: str = _env("AIROBOT_MILVUS_URI", "http://localhost:19530")
    milvus_token: str = _env("AIROBOT_MILVUS_TOKEN")
    milvus_collection: str = _env("AIROBOT_MILVUS_COLLECTION", "airobot_kb")
    # 旧清库开关不再读取：启动、导入、实例化均不能删除集合。
    knowledge_state_db: str = _env("AIROBOT_KNOWLEDGE_STATE_DB", "data/knowledge.sqlite3")
    # 稳定性工程（重试 / 限流 / 语义缓存）
    retry_attempts: int = int(_env("AIROBOT_RETRY_ATTEMPTS", "3"))
    retry_max_wait: float = float(_env("AIROBOT_RETRY_MAX_WAIT", "8"))
    ratelimit_enabled: bool = _env("AIROBOT_RATELIMIT_ENABLED", "true").lower() == "true"
    ratelimit_per_minute: int = int(_env("AIROBOT_RATELIMIT_PER_MINUTE", "30"))
    cache_enabled: bool = _env("AIROBOT_CACHE_ENABLED", "true").lower() == "true"
    cache_threshold: float = float(_env("AIROBOT_CACHE_THRESHOLD", "0.75"))
    cache_lexical_threshold: float = float(_env("AIROBOT_CACHE_LEXICAL_THRESHOLD", "0.5"))
    cache_max_entries: int = int(_env("AIROBOT_CACHE_MAX_ENTRIES", "1000"))
    # Go 文章服务对接（article 工具真实数据 + RabbitMQ 文章入库）
    go_api_base_url: str = _env("AIROBOT_GO_API_BASE_URL")          # 例: http://localhost:8080；空 = 未启用
    go_api_internal_token: str = _env("AIROBOT_GO_INTERNAL_TOKEN")  # 调 Go /internal/ai 的内部令牌
    ai_internal_token: str = _env("AIROBOT_AI_INTERNAL_TOKEN")      # 校验 Go 网关身份头（X-Internal-Token）
    admin_token: str = _env("AIROBOT_ADMIN_TOKEN")                 # 独立管理凭据，不能与网关令牌相同
    go_api_timeout: float = float(_env("AIROBOT_GO_API_TIMEOUT", "5"))
    # RabbitMQ 文章发布事件订阅（未配置 AIROBOT_AMQP_URL 时不启动消费者）
    amqp_url: str = _env("AIROBOT_AMQP_URL")
    amqp_exchange: str = _env("AIROBOT_AMQP_EXCHANGE", "article.timeline.events")
    amqp_queue: str = _env("AIROBOT_AMQP_QUEUE", "article.ai.ingest.queue")
    amqp_routing_key: str = _env("AIROBOT_AMQP_ROUTING_KEY", "article.timeline.publish")
    amqp_prefetch: int = int(_env("AIROBOT_AMQP_PREFETCH", "5"))
    # 文章入库状态与正文持久化（相对路径以项目根目录为基准，随 data 卷保存）
    ingest_state_db: str = _env("AIROBOT_INGEST_STATE_DB", "data/airobot_state.sqlite3")
    # 单个上传文件大小上限，避免整文件读入内存导致 OOM
    max_upload_bytes: int = max(1, int(_env("AIROBOT_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024))))


settings = Settings()
