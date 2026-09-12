# -*- coding: utf-8 -*-
"""接口出入参模型。"""
from typing import Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=16000)
    session_id: Optional[str] = Field(default=None, min_length=1, max_length=128,
                                      pattern=r"^[A-Za-z0-9_-]+$")


class ChatResponse(BaseModel):
    reply: str
    intent: Optional[str] = None
    sources: list = []
    engine: str = "langgraph"
    run_id: str = ""
    steps: list = []
    cache_hit: bool = False
    session_id: str = ""


class IngestResponse(BaseModel):
    file_name: str
    chunks: int
    total_chunks: int


class StatsResponse(BaseModel):
    total_chunks: int
    llm_model: str
    embedding_model: str
    agent_engine: str = "langgraph"
    agent_max_tool_rounds: int = 0
    hybrid_enabled: bool = True
    bm25_ready: bool = False
    rerank_enabled: bool = False
    cache_enabled: bool = False
    cache_size: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    cache_threshold: float = 0.0
    ratelimit_enabled: bool = False
    ratelimit_per_minute: int = 0
    ratelimit_blocked: int = 0
