# -*- coding: utf-8 -*-
"""Go 文章服务客户端：article 工具真实数据查询与 MQ 文章入库共用。

通过内部令牌（X-Internal-Token）访问 Go 网关的 /internal/ai 私有接口；
未配置 AIROBOT_GO_API_BASE_URL 时 enabled=False，所有查询抛 GoServiceError，
由调用方（工具层）转成友好降级文案。
httpx.TransportError（连接失败/超时）不在本层吞掉，交由 invoke_with_retry
按既有可重试判定自动指数退避。
"""
import logging

import httpx

from app.config import settings
from app.services.resilience import ainvoke_with_retry, invoke_with_retry

logger = logging.getLogger("airobot.go_client")


class GoServiceError(RuntimeError):
    """Go 文章服务返回异常（非 404 的 HTTP 错误 / 数据无法解析 / 未启用）。"""


def _normalize(payload: dict) -> dict:
    """把 Go 的 {article, tags} 归一化为工具与入库共用的扁平结构。"""
    article = payload.get("article") or {}
    return {
        "id": article.get("id"),
        "title": article.get("title") or "",
        "summary": article.get("summary") or "",
        "content": article.get("content") or "",
        "username": article.get("username") or "",
        "tags": payload.get("tags") or [],
        "likes_count": article.get("likes_count") or 0,
        "comments_count": article.get("comments_count") or 0,
        "create_time": article.get("create_time"),
    }


class GoArticleClient:
    """异步 + 同步双通道：异步供内置路由 / SSE 与消费者，同步供 CrewAI 工具线程。"""

    def __init__(self, base_url: str, token: str, timeout: float,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._base_url = (base_url or "").rstrip("/")
        self._token = token
        self._timeout = timeout
        self._transport = transport  # 测试注入 httpx.MockTransport 用
        self._async_client: httpx.AsyncClient | None = None
        self._sync_client: httpx.Client | None = None

    @property
    def enabled(self) -> bool:
        return bool(self._base_url)

    def _detail_url(self) -> str:
        return f"{self._base_url}/internal/ai/article/detail"

    def _headers(self) -> dict[str, str]:
        return {"X-Internal-Token": self._token}

    def _parse(self, resp: httpx.Response, article_id: int) -> dict | None:
        """404 -> None（文章不存在）；其余非 200 -> GoServiceError。"""
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise GoServiceError(
                f"Go 文章服务返回异常状态 {resp.status_code}（article_id={article_id}）")
        try:
            return _normalize(resp.json())
        except ValueError as exc:
            raise GoServiceError(f"Go 文章服务返回数据无法解析: {exc}") from exc

    async def get_article_detail(self, article_id: int) -> dict | None:
        """异步查询文章详情；未启用抛 GoServiceError，404 返回 None。"""
        if not self.enabled:
            raise GoServiceError("Go 文章服务未启用（未配置 AIROBOT_GO_API_BASE_URL）")
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(timeout=self._timeout,
                                                   transport=self._transport)
        return await ainvoke_with_retry(self._fetch_async, article_id)

    async def _fetch_async(self, article_id: int) -> dict | None:
        resp = await self._async_client.post(self._detail_url(), json={"id": article_id},
                                             headers=self._headers())
        return self._parse(resp, article_id)

    def get_article_detail_sync(self, article_id: int) -> dict | None:
        """同步查询（CrewAI 工具在独立线程运行，不能复用事件循环）。"""
        if not self.enabled:
            raise GoServiceError("Go 文章服务未启用（未配置 AIROBOT_GO_API_BASE_URL）")
        if self._sync_client is None:
            self._sync_client = httpx.Client(timeout=self._timeout,
                                             transport=self._transport)
        return invoke_with_retry(self._fetch_sync, article_id)

    def _fetch_sync(self, article_id: int) -> dict | None:
        resp = self._sync_client.post(self._detail_url(), json={"id": article_id},
                                      headers=self._headers())
        return self._parse(resp, article_id)

    async def aclose(self) -> None:
        """应用关闭时释放连接池。"""
        if self._async_client is not None:
            await self._async_client.aclose()
            self._async_client = None
        if self._sync_client is not None:
            self._sync_client.close()
            self._sync_client = None


go_client = GoArticleClient(settings.go_api_base_url, settings.go_api_internal_token,
                            settings.go_api_timeout)
