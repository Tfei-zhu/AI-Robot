# -*- coding: utf-8 -*-
"""RAG 全链路：分块 -> 向量 + BM25 双路索引 -> RRF 融合 -> bge-reranker 重排 -> 检索增强生成。
当前使用内存向量库（InMemoryVectorStore）便于开箱即用；
生产环境可无痛替换为 Chroma / FAISS / Milvus（接口一致）。
"""
import asyncio
import time
from pathlib import Path
from typing import List, Tuple

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from app.config import settings
from app.rag.fusion import reciprocal_rank_fusion
from app.rag.lexical import BM25Index
from app.rag.loader import parse_file
from app.rag.reranker import Reranker
from app.services.resilience import invoke_with_retry


def build_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        api_key=settings.embedding_api_key or "sk-placeholder-not-configured",
        base_url=settings.embedding_base_url,
        check_embedding_ctx_length=False,  # 非 OpenAI 模型（Ollama 等）不做 tiktoken 预检，直接发送原文
    )


def build_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key or "sk-placeholder-not-configured",
        base_url=settings.llm_base_url,
        temperature=0.3,
    )


def build_splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
    )


def build_markdown_splitter() -> MarkdownHeaderTextSplitter:
    """按 Markdown 标题层级切分（保留标题在正文中，增强检索上下文）。"""
    return MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "H1"), ("##", "H2"), ("###", "H3"), ("####", "H4")],
        strip_headers=False,
    )


class KnowledgeBase:
    """进程内知识库：向量 + BM25 双路索引，RRF 融合，可选 bge-reranker 重排。"""

    def __init__(self) -> None:
        self._store = InMemoryVectorStore(embedding=build_embeddings())
        self._splitter = build_splitter()
        self._markdown_splitter = build_markdown_splitter()
        self._bm25 = BM25Index()
        self._reranker = Reranker()
        self._documents: List[Document] = []
        self.chunk_count = 0

    @property
    def bm25_ready(self) -> bool:
        return self._bm25.ready

    def ingest_text(self, title: str, text: str) -> int:
        chunks = self._split_text(title, text)
        docs = [
            Document(
                page_content=c.page_content,
                metadata={**c.metadata, "title": title, "chunk": i,
                          "doc_id": f"{title}#{i}"},
            )
            for i, c in enumerate(chunks)
        ]
        if docs:
            self._documents.extend(docs)
            invoke_with_retry(self._store.add_documents, docs)
            self._bm25.add_documents([d.page_content for d in docs])
            self.chunk_count += len(docs)
        return len(docs)

    def embed_query(self, query: str) -> list[float]:
        """查询向量化（语义缓存用），带重试。"""
        return invoke_with_retry(self._store.embedding.embed_query, query)

    def _split_text(self, title: str, text: str) -> List[Document]:
        """按文件类型选择分块策略：Markdown 先按标题层级，再对超长章节二次切分。"""
        if title.lower().endswith((".md", ".markdown")):
            return self._split_markdown(text)
        return [Document(page_content=c) for c in self._splitter.split_text(text)]

    def _split_markdown(self, text: str) -> List[Document]:
        sections = self._markdown_splitter.split_text(text)
        docs: List[Document] = []
        max_section_len = max(settings.chunk_size * 2, settings.chunk_size + 200)
        for section in sections:
            if len(section.page_content) <= max_section_len:
                docs.append(section)
            else:
                docs.extend(self._splitter.split_documents([section]))
        return docs

    def ingest_file(self, path: Path) -> int:
        return self.ingest_text(path.name, parse_file(path))

    def search(self, query: str, top_k: int | None = None) -> List[Document]:
        """混合检索：向量 + BM25 -> RRF 融合 -> bge-reranker 重排。"""
        docs, _ = self.search_detailed(query, top_k)
        return docs

    def search_detailed(self, query: str, top_k: int | None = None) -> Tuple[List[Document], dict]:
        """混合检索并返回各阶段耗时明细，供控制台全链路可视化使用。

        返回 (docs, detail)，detail 字段：
        vector_ms / vector_hits / bm25_ms / bm25_hits / fusion_ms / fused /
        rerank_ms / rerank_enabled / hybrid。
        """
        top_k = top_k or settings.top_k
        detail = {"vector_ms": 0.0, "vector_hits": 0, "bm25_ms": 0.0, "bm25_hits": 0,
                  "fusion_ms": 0.0, "fused": 0, "rerank_ms": 0.0, "rerank_enabled": False,
                  "hybrid": bool(self._bm25.ready and settings.hybrid_enabled)}
        if not self._bm25.ready or not settings.hybrid_enabled:
            t0 = time.perf_counter()
            docs = self.search_vector(query, top_k)
            detail["vector_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            detail["vector_hits"] = len(docs)
            return self._rerank_if_enabled(query, docs, top_k, detail), detail

        t0 = time.perf_counter()
        vector_docs = self.search_vector(query, settings.hybrid_vector_top_k)
        detail["vector_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        detail["vector_hits"] = len(vector_docs)

        t0 = time.perf_counter()
        bm25_docs = self.search_bm25(query, settings.hybrid_bm25_top_k)
        detail["bm25_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        detail["bm25_hits"] = len(bm25_docs)

        t0 = time.perf_counter()
        fused_ids = reciprocal_rank_fusion(
            [[d.metadata.get("doc_id") for d in vector_docs],
             [d.metadata.get("doc_id") for d in bm25_docs]],
            top_k=settings.hybrid_fusion_top_k,
        )
        detail["fusion_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        detail["fused"] = len(fused_ids)
        doc_map = {d.metadata.get("doc_id"): d for d in vector_docs + bm25_docs}
        docs = [doc_map[did] for did in fused_ids if did in doc_map]
        return self._rerank_if_enabled(query, docs, top_k, detail), detail

    def _rerank_if_enabled(self, query: str, docs: List[Document], top_k: int,
                           detail: dict) -> List[Document]:
        if settings.rerank_enabled:
            t0 = time.perf_counter()
            docs = self._reranker.rerank(query, docs, top_k)
            detail["rerank_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            detail["rerank_enabled"] = True
        return docs[:top_k]

    def search_vector(self, query: str, top_k: int | None = None) -> List[Document]:
        """纯向量检索（对照用）。"""
        return invoke_with_retry(
            self._store.similarity_search, query, k=top_k or settings.hybrid_vector_top_k)

    def search_bm25(self, query: str, top_k: int | None = None) -> List[Document]:
        """纯 BM25 词面检索（对照用）。"""
        indices = self._bm25.search(query, top_k or settings.hybrid_bm25_top_k)
        return [self._documents[i] for i in indices]

    def search_hybrid(self, query: str, top_k: int | None = None) -> List[Document]:
        """RRF 融合（不含重排），供评测脚本与对照实验使用。"""
        top_k = top_k or settings.top_k
        if not self._bm25.ready or not settings.hybrid_enabled:
            return self.search_vector(query, top_k)
        vector_docs = self.search_vector(query, settings.hybrid_vector_top_k)
        bm25_docs = self.search_bm25(query, settings.hybrid_bm25_top_k)
        fused_ids = reciprocal_rank_fusion(
            [[d.metadata.get("doc_id") for d in vector_docs],
             [d.metadata.get("doc_id") for d in bm25_docs]],
            top_k=settings.hybrid_fusion_top_k,
        )
        doc_map = {d.metadata.get("doc_id"): d for d in vector_docs + bm25_docs}
        return [doc_map[did] for did in fused_ids if did in doc_map]


kb = KnowledgeBase()


RAG_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "你是二手交易平台的智能客服助手。只能依据给定的资料回答问题；"
     "资料中没有的信息要如实说明不知道，禁止编造。回答使用简洁友好的中文。"),
    MessagesPlaceholder("history"),
    ("human", "资料：\n{context}\n\n问题：{question}"),
])


def answer_with_rag(query: str, llm=None, history=None) -> Tuple[str, List[str]]:
    """检索 -> 生成，返回 (回答, 来源列表)。"""
    if kb.chunk_count == 0:
        return ("知识库为空，请先通过 POST /api/v1/ingest 或 scripts/ingest.py 导入资料。", [])
    llm = llm or build_llm()
    docs = kb.search(query)
    context = "\n\n".join(d.page_content for d in docs)
    chain = RAG_PROMPT | llm | StrOutputParser()
    answer = invoke_with_retry(
        chain.invoke, {"context": context, "question": query, "history": history or []})
    sources = [f"{d.metadata.get('title', '')}#{d.metadata.get('chunk', 0)}" for d in docs]
    return answer, sources


async def aanswer_with_rag(query: str, llm=None, history=None) -> Tuple[str, List[str]]:
    """异步版：检索（线程池）+ 生成（ainvoke），供 async 接口使用，避免阻塞事件循环。"""
    if kb.chunk_count == 0:
        return ("知识库为空，请先通过 POST /api/v1/ingest 或 scripts/ingest.py 导入资料。", [])
    llm = llm or build_llm()
    docs = await asyncio.to_thread(kb.search, query)
    context = "\n\n".join(d.page_content for d in docs)
    chain = RAG_PROMPT | llm | StrOutputParser()
    from app.services.resilience import ainvoke_with_retry
    answer = await ainvoke_with_retry(
        chain.ainvoke, {"context": context, "question": query, "history": history or []})
    sources = [f"{d.metadata.get('title', '')}#{d.metadata.get('chunk', 0)}" for d in docs]
    return answer, sources
