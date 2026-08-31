# -*- coding: utf-8 -*-
"""文章发布事件消费者：订阅 Go 网关的 RabbitMQ 文章发布事件，抓取正文并入库知识库。

设计要点：
- 队列由本服务自建自 declare（article.ai.ingest.queue），绑定到 Go 现有交换机
  article.timeline.events 的 article.timeline.publish 路由键 —— Go 侧 MQ 零改动；
- declare 标志必须与 Go DeclareTopic 完全一致（durable topic 交换机 + durable 队列），
  否则会 PRECONDITION_FAILED；
- 未配置 AIROBOT_AMQP_URL 时优雅降级（不启动消费者，对话服务照常可用）；
- 投毒消息策略：解析失败或重试后仍失败 -> 大声日志 + ack 跳过（开发规模不建 DLX，
  卡死队列比跳过一篇文章更糟）；去重由本类的内存集合负责（入库成功后记录）；
- 消费者必须运行在 API 进程内：inmemory 向量库不跨进程共享，独立进程入库对服务不可见。
"""
import asyncio
import json
import logging

from app.config import settings

logger = logging.getLogger("airobot.article_consumer")

SUPERVISOR_BACKOFF_SECONDS = 30.0


class ArticleIngestConsumer:
    """RabbitMQ 文章发布事件 -> Go 内部 API 抓取正文 -> kb.ingest_article()。"""

    def __init__(self, kb, client) -> None:
        self._kb = kb
        self._client = client
        self._ingested_article_ids: set[int] = set()
        self._task: asyncio.Task | None = None

    @property
    def ingested_article_ids(self) -> set[int]:
        return set(self._ingested_article_ids)

    async def start(self) -> asyncio.Task | None:
        """启动后台消费任务；未配置 AMQP 时返回 None（优雅降级）。"""
        if not settings.amqp_url:
            logger.info("未配置 AIROBOT_AMQP_URL，文章入库消费者不启动")
            return None
        self._task = asyncio.create_task(self._run_supervisor())
        return self._task

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_supervisor(self) -> None:
        """监督循环：断连/异常退出后 30 秒退避重连，保证网络抖动后自动恢复。"""
        while True:
            try:
                await self._consume_forever()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("文章入库消费者异常退出，%.0f 秒后重连: %s",
                             SUPERVISOR_BACKOFF_SECONDS, exc)
            await asyncio.sleep(SUPERVISOR_BACKOFF_SECONDS)

    async def _consume_forever(self) -> None:
        import aio_pika  # 懒加载：不影响未启用 MQ 场景的核心对话链路与 CI 导入冒烟
        from aio_pika.exchange import ExchangeType

        connection = await aio_pika.connect_robust(settings.amqp_url)
        async with connection:
            channel = await connection.channel()
            await channel.set_qos(prefetch_count=settings.amqp_prefetch)
            # 与 Go DeclareTopic 严格对齐：durable topic 交换机 + durable 队列 + bind
            exchange = await channel.declare_exchange(
                settings.amqp_exchange, ExchangeType.TOPIC, durable=True)
            queue = await channel.declare_queue(settings.amqp_queue, durable=True)
            await queue.bind(exchange, routing_key=settings.amqp_routing_key)
            logger.info("文章入库消费者已连接: exchange=%s queue=%s routing_key=%s",
                        settings.amqp_exchange, settings.amqp_queue,
                        settings.amqp_routing_key)
            async with queue.iterator() as queue_iter:
                async for message in queue_iter:
                    async with message.process(ignore_processed=True):
                        await self._process_delivery(message)

    async def _process_delivery(self, message) -> None:
        """单条投递：解析失败/未预期异常都只记日志不抛出（保证 ack 跳过，不卡队列）。"""
        try:
            payload = json.loads(message.body)
            result = await self.handle_event(payload)
            event_id = payload.get("event_id", "unknown") if isinstance(payload, dict) else "unknown"
            logger.info("文章事件处理完成: %s（event_id=%s）", result, event_id)
        except Exception as exc:
            logger.exception("文章事件处理出现未预期异常，跳过该消息: %s", exc)

    async def handle_event(self, payload: dict) -> str:
        """处理单条文章事件（纯逻辑，便于离线测试）。

        返回 ingested | duplicate | not_found | invalid | skipped。
        """
        if not isinstance(payload, dict):
            return "invalid"
        article_id = payload.get("article_id")
        if not isinstance(article_id, int) or article_id <= 0:
            logger.error("文章事件缺少合法 article_id，跳过: %r", article_id)
            return "invalid"
        if article_id in self._ingested_article_ids:
            logger.info("文章 %s 重复投递，跳过入库", article_id)
            return "duplicate"
        try:
            data = await self._client.get_article_detail(article_id)
        except Exception as exc:
            logger.error("抓取文章 %s 失败，跳过该消息: %s", article_id, exc)
            return "skipped"
        if data is None:
            logger.warning("文章 %s 不存在（可能已删除），跳过", article_id)
            return "not_found"
        try:
            chunks = self._kb.ingest_article(
                article_id, data.get("title", ""), data.get("content", ""),
                summary=data.get("summary", ""), tags=data.get("tags") or [])
        except Exception as exc:
            logger.error("文章 %s 入库失败，跳过该消息: %s", article_id, exc)
            return "skipped"
        self._ingested_article_ids.add(article_id)
        logger.info("文章入库成功: id=%s 分块=%s 总块数=%s",
                    article_id, chunks, self._kb.chunk_count)
        return "ingested"
