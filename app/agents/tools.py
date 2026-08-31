# -*- coding: utf-8 -*-
"""Agent 工具集：RAG 检索问答 / 文章查询（Go 文章服务真实数据）/ 社区规范。

命名约定：
- search_knowledge / query_article / community_guideline：原始函数，内置路由与 SSE 流式直接调用；
- *_tool 变体：CrewAI Tool 包装（仅安装 crewai 后存在），供多 Agent 编排使用。
  CrewAI 在独立线程同步调用工具，故 query_article_tool 绑定同步版 query_article_sync。
"""
import logging
import re

import httpx

from app.rag.retriever import answer_with_rag, build_llm
from app.services.go_client import GoServiceError, go_client

logger = logging.getLogger("airobot.tools")

# 文章 ID 提取：优先「文章 12 / article #12」句式，兜底任意 1~10 位数字（真实自增 ID 通常较小）
_ARTICLE_ID_RE = re.compile(r"(?:文章|article)\s*#?\s*(\d{1,10})", re.IGNORECASE)
_FALLBACK_ID_RE = re.compile(r"\b(\d{1,10})\b")


def search_knowledge(query: str) -> str:
    """检索 Go 文章社区知识库并基于资料回答问题（RAG）。"""
    answer, _ = answer_with_rag(query, build_llm())
    return answer


def _extract_article_id(message: str) -> int | None:
    match = _ARTICLE_ID_RE.search(message) or _FALLBACK_ID_RE.search(message)
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
    """查询文章真实数据（同步版，供 CrewAI 工具线程调用）。"""
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


# CrewAI 工具版（供 Agent 编排；未安装 crewai 时为 None，系统自动降级）
search_knowledge_tool = None
query_article_tool = None
community_guideline_tool = None
CREW_TOOLS_READY = False
try:
    from crewai.tools import tool
    search_knowledge_tool = tool("search_knowledge")(search_knowledge)
    query_article_tool = tool("query_article")(query_article_sync)
    community_guideline_tool = tool("community_guideline")(community_guideline)
    CREW_TOOLS_READY = True
except Exception:  # pragma: no cover - crewai 未安装
    CREW_TOOLS_READY = False
