# -*- coding: utf-8 -*-
"""LangGraph Agent 的只读工具集。

RAG 是 ``search_knowledge`` 工具，而不是对话服务的固定分支。工具返回 JSON
字符串，既便于模型理解，也让编排层能够提取来源并把执行轨迹返回给客户端。
"""
import json
import logging
import re

import httpx
from langchain_core.tools import tool

from app.rag.retriever import aanswer_with_rag, answer_with_rag, build_llm
from app.services.go_client import GoServiceError, go_client

logger = logging.getLogger("airobot.tools")

# 文章 ID 提取：只接受明确的「文章 12 / article #12」句式，避免把版本号等普通数字误认为文章 ID。
_ARTICLE_ID_RE = re.compile(r"(?:文章|article)\s*#?\s*(\d{1,10})", re.IGNORECASE)


def search_knowledge(query: str) -> str:
    """检索 Go 文章社区知识库并基于资料回答问题（RAG）。"""
    answer, _ = answer_with_rag(query, build_llm())
    return answer


def _extract_article_id(message: str) -> int | None:
    match = _ARTICLE_ID_RE.search(message)
    return int(match.group(1)) if match else None


def _format_article(data: dict) -> str:
    """沿用原 Mock 的中文句式，字段来自 Go 文章服务真实数据。"""
    tags = "、".join(data.get("tags") or []) or "无"
    return (f"文章 {data.get('id')}：状态=已发布，标题=《{data.get('title')}》，"
            f"作者={data.get('username')}，标签={tags}，"
            f"点赞 {data.get('likes_count', 0)}，评论 {data.get('comments_count', 0)}。"
            "可在文章页继续收藏、评论或查看修订记录。")


def _no_id_reply() -> str:
    return "请告诉我文章 ID，例如：文章 12 的数据。"


def _handle_lookup(article_id: int, data: dict | None, err: Exception | None) -> str:
    """查询结果 -> 用户文案：服务异常降级 / 404 提示 / 真实数据。"""
    if err is not None:
        logger.warning("文章查询失败（id=%s）: %s", article_id, err)
        return "文章服务暂不可用，请稍后再试。"
    if data is None:
        return f"未找到文章 {article_id}，请确认 ID 是否正确。"
    return _format_article(data)


async def query_article(message: str) -> str:
    """查询 Go 文章的真实状态与基本信息（异步版，内置路由与 SSE 调用）。"""
    article_id = _extract_article_id(message)
    if article_id is None:
        return _no_id_reply()
    try:
        data = await go_client.get_article_detail(article_id)
        err = None
    except (GoServiceError, httpx.TransportError) as exc:
        data, err = None, exc
    return _handle_lookup(article_id, data, err)


def query_article_sync(message: str) -> str:
    """查询文章真实数据的同步兼容入口。"""
    article_id = _extract_article_id(message)
    if article_id is None:
        return _no_id_reply()
    try:
        data = go_client.get_article_detail_sync(article_id)
        err = None
    except (GoServiceError, httpx.TransportError) as exc:
        data, err = None, exc
    return _handle_lookup(article_id, data, err)


def community_guideline(_message: str) -> str:
    """查询 Go 文章社区的发布与讨论规范。"""
    return ("社区规范：文章应标注 Go 版本与可运行示例；引用内容请注明来源。"
            "评论请围绕技术问题友善讨论，禁止人身攻击、广告引流和泄露密钥等敏感信息。")


@tool("search_knowledge")
async def search_knowledge_tool(query: str) -> str:
    """检索 Go 技术与社区知识库，并返回带可引用来源的事实材料。"""
    answer, sources = await aanswer_with_rag(query, build_llm())
    return json.dumps({"answer": answer, "sources": sources}, ensure_ascii=False)


@tool("query_article")
async def query_article_tool(message: str) -> str:
    """按用户消息中的文章 ID 查询社区文章的实时详情。"""
    article_id = _extract_article_id(message)
    answer = await query_article(message)
    sources = [f"article:{article_id}"] if article_id is not None else []
    return json.dumps({"answer": answer, "sources": sources}, ensure_ascii=False)


@tool("community_guideline")
def community_guideline_tool(question: str) -> str:
    """获取社区发文、引用与讨论规范。"""
    return json.dumps({"answer": community_guideline(question),
                       "sources": ["community_guideline"]}, ensure_ascii=False)


AGENT_TOOLS = [search_knowledge_tool, query_article_tool, community_guideline_tool]
