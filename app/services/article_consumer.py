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

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from app.config import settings

logger = logging.getLogger("airobot.article_consumer")

SUPERVISOR_BACKOFF_SECONDS = 30.0


class ArticleIngestConsumer:
    """RabbitMQ 文章发布事件 -> Go 内部 API 抓取正文 -> kb.ingest_article()。"""

    def __init__(self, kb, client, state_path: str | Path | None = None) -> None:
        self._kb = kb
        self._client = client
        self._state_path = self._resolve_state_path(state_path)
        if self._state_path != ":memory:":
            Path(self._state_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self._state_path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS ingested_articles ("
            "article_id INTEGER PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL,"
            "summary TEXT NOT NULL DEFAULT '', tags_json TEXT NOT NULL DEFAULT '[]',"
            "status TEXT NOT NULL, ingested_at TEXT NOT NULL)")
        self._db.commit()
        self._ingested_article_ids: set[int] = self._load_ingested_ids()
        self._task: asyncio.Task | None = None

    @property
    def ingested_article_ids(self) -> set[int]:
        return {int(row[0]) for row in self._db.execute(
            "SELECT article_id FROM ingested_articles WHERE status = 'ingested'").fetchall()}
    @staticmethod
    def _resolve_state_path(state_path: str | Path | None) -> str:
        if state_path is not None:
            return str(state_path)
        path = Path(settings.ingest_state_db)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[2] / path
        return str(path)

    def _load_ingested_ids(self) -> set[int]:
        rows = self._db.execute(
            "SELECT article_id FROM ingested_articles WHERE status = 'ingested'").fetchall()
        return {int(row[0]) for row in rows}

    def _article_status(self, article_id: int) -> str | None:
        row = self._db.execute(
            "SELECT status FROM ingested_articles WHERE article_id = ?", (article_id,)
        ).fetchone()
        return row[0] if row else None

    def _reserve_article(self, article_id: int, data: dict) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        self._db.execute(
            "INSERT OR IGNORE INTO ingested_articles "
            "(article_id, title, content, summary, tags_json, status, ingested_at) "
            "VALUES (?, ?, ?, ?, ?, 'pending', ?)",
            (article_id, data.get("title", ""), data.get("content", ""),
             data.get("summary", ""), json.dumps(data.get("tags") or [], ensure_ascii=False), now),
        )
        self._db.commit()
        return self._article_status(article_id) == "pending"

    def _mark_ingested(self, article_id: int) -> None:
        self._db.execute(
            "UPDATE ingested_articles SET status = 'ingested', ingested_at = ? "
            "WHERE article_id = ?", (datetime.now(timezone.utc).isoformat(), article_id)
        )
        self._db.commit()
        self._ingested_article_ids.add(article_id)

    def _delete_pending(self, article_id: int) -> None:
        self._db.execute(
            "DELETE FROM ingested_articles WHERE article_id = ? AND status = 'pending'",
            (article_id,),
        )
        self._db.commit()

    async def restore(self) -> int:
        """从 SQLite 重放文章正文，恢复进程内向量与 BM25 索引。"""
        rows = self._db.execute(
            "SELECT article_id, title, content, summary, tags_json "
            "FROM ingested_articles WHERE status IN ('pending', 'ingested') "
            "ORDER BY article_id"
        ).fetchall()
        restored = 0
        for article_id, title, content, summary, tags_json in rows:
            try:
                tags = json.loads(tags_json or "[]")
                if not isinstance(tags, list):
                    tags = []
                self._kb.ingest_article(article_id, title, content, summary=summary, tags=tags)
                self._mark_ingested(article_id)
                restored += 1
            except Exception as exc:
                logger.exception("恢复文章 %s 失败，将在下次启动或消息重投时重试: %s", article_id, exc)
        if restored:
            logger.info("从持久化状态恢复 %s 篇文章", restored)
        return restored

    def close(self) -> None:
        self._db.close()

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
                    async with message.process(requeue=True, ignore_processed=True):
                        await self._process_delivery(message)

    async def _process_delivery(self, message) -> None:
        """单条投递：坏 JSON 丢弃；可恢复失败抛出并让 RabbitMQ 重新入队。"""
        try:
            payload = json.loads(message.body)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.exception("文章事件消息无法解析，丢弃该消息: %s", exc)
            return
        result = await self.handle_event(payload)
        event_id = payload.get("event_id", "unknown") if isinstance(payload, dict) else "unknown"
        if result == "skipped":
            raise RuntimeError(f"文章事件处理失败，重新入队（event_id={event_id}）")
        logger.info("文章事件处理完成: %s（event_id=%s）", result, event_id)

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
        if self._article_status(article_id) in {"pending", "ingested"}:
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
        if not self._reserve_article(article_id, data):
            logger.info("文章 %s 已由其他投递处理中，跳过重复入库", article_id)
            return "duplicate"
        try:
            chunks = self._kb.ingest_article(
                article_id, data.get("title", ""), data.get("content", ""),
                summary=data.get("summary", ""), tags=data.get("tags") or [])
        except Exception as exc:
            self._delete_pending(article_id)
            logger.error("文章 %s 入库失败，跳过该消息: %s", article_id, exc)
            return "skipped"
        self._mark_ingested(article_id)
        logger.info("文章入库成功: id=%s 分块=%s 总块数=%s",
                    article_id, chunks, self._kb.chunk_count)
        return "ingested"
