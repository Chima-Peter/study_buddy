import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from logging import Logger
from typing import Any

from aio_pika import Channel, DeliveryMode, Message, Queue
from aio_pika.abc import AbstractIncomingMessage
from aio_pika.exceptions import DeliveryError
from fastapi import HTTPException
import uuid_utils

RETRY_COUNT_HEADER = "x-retry-count"


@dataclass
class RabbitMQConsumer:
    queue: Queue
    tag: str


def retry_delay_tiers_ms(base_ms: int, max_ms: int, max_retries: int) -> list[int]:
    """Exponential delay tiers used as TTL retry queue names."""
    tiers: list[int] = []
    delay = base_ms
    for _ in range(max(max_retries, 1)):
        tiers.append(min(delay, max_ms))
        delay = min(delay * 2, max_ms)
    return sorted(set(tiers))


def delay_ms_for_attempt(
    attempt: int,
    *,
    base_ms: int,
    max_ms: int,
    tiers: list[int],
) -> int:
    desired = min(base_ms * (2**attempt), max_ms)
    for tier in tiers:
        if tier >= desired:
            return tier
    return tiers[-1]


def read_retry_count(headers: Mapping[str, Any] | None) -> int:
    if not headers:
        return 0
    raw = headers.get(RETRY_COUNT_HEADER, 0)
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def retry_queue_name(target_queue: str, delay_ms: int) -> str:
    return f"{target_queue}_retry_{delay_ms}ms"


@dataclass
class RabbitMQ:
    channel: Channel
    llm_channel: Channel
    study_cards_channel: Channel
    email_queue: Queue
    email_dlq_queue: Queue
    document_queue: Queue
    document_dlq_queue: Queue
    memory_extract_queue: Queue
    memory_extract_dlq_queue: Queue
    study_cards_generate_queue: Queue
    study_cards_generate_dlq_queue: Queue
    logger: Logger
    # target_queue -> { delay_ms -> Queue }
    retry_queues: dict[str, dict[int, Queue]] = field(default_factory=dict)
    max_retries: int = 5
    retry_base_ms: int = 5_000
    retry_max_ms: int = 300_000
    retry_tiers_ms: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.retry_tiers_ms:
            self.retry_tiers_ms = retry_delay_tiers_ms(
                self.retry_base_ms,
                self.retry_max_ms,
                self.max_retries,
            )

    def _channel_for_queue(self, queue_name: str) -> Channel:
        if queue_name.startswith("memory_extract_queue"):
            return self.llm_channel
        if queue_name.startswith("study_cards_generate_queue"):
            return self.study_cards_channel
        return self.channel

    async def publish_message(self, queue_name: str, payload: dict, retry_count: int = 0):
        if retry_count > 3:
            self._logger.error(
                "Publish failed queue=%s after %s retries", queue_name, retry_count)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to publish message to {queue_name} after {retry_count} retries",
            )
        try:
            self.logger.info(
                "Publishing message to %s on retry %s", queue_name, retry_count)
            message = Message(
                body=json.dumps(payload).encode(),
                delivery_mode=DeliveryMode.PERSISTENT,
                message_id=str(uuid_utils.uuid7()),
            )
            channel = self._channel_for_queue(queue_name)
            await channel.default_exchange.publish(
                message=message,
                routing_key=queue_name,
                timeout=5.0,
            )
            self.logger.debug("Published message to queue=%s", queue_name)
        except (DeliveryError, TimeoutError, Exception) as e:
            self.logger.warning(
                "Publish retry queue=%s attempt=%s error=%s", queue_name, retry_count, e)
            await self.publish_message(queue_name, payload, retry_count + 1)

    async def schedule_retry(
        self,
        target_queue: str,
        payload: dict,
        *,
        retry_count: int,
        headers: Mapping[str, Any] | None = None,
    ) -> int:
        """Publish to a TTL queue that dead-letters back onto ``target_queue``.

        Returns the delay (ms) used.
        """
        tiers = self.retry_queues.get(target_queue)
        if not tiers:
            raise RuntimeError(
                f"Retry queues are not configured for target_queue={target_queue}"
            )

        delay_ms = delay_ms_for_attempt(
            retry_count,
            base_ms=self.retry_base_ms,
            max_ms=self.retry_max_ms,
            tiers=self.retry_tiers_ms,
        )
        if delay_ms not in tiers:
            delay_ms = min(tiers.keys(), key=lambda t: (abs(t - delay_ms), t))

        next_headers = {
            k: v
            for k, v in dict(headers or {}).items()
            if not str(k).startswith("x-death")
            and not str(k).startswith("x-first-death")
            and not str(k).startswith("x-last-death")
            and k not in ("x-delivery-count", "x-acquired-count")
        }
        next_headers[RETRY_COUNT_HEADER] = retry_count + 1

        routing_key = retry_queue_name(target_queue, delay_ms)
        message = Message(
            body=json.dumps(payload).encode(),
            delivery_mode=DeliveryMode.PERSISTENT,
            message_id=str(uuid_utils.uuid7()),
            headers=next_headers,
        )
        channel = self._channel_for_queue(target_queue)
        await channel.default_exchange.publish(
            message=message,
            routing_key=routing_key,
            timeout=5.0,
        )
        self.logger.info(
            "Scheduled retry target=%s attempt=%s delay_ms=%s queue=%s payload_id=%s",
            target_queue,
            retry_count + 1,
            delay_ms,
            routing_key,
            payload.get("document_id")
            or payload.get("conversation_id")
            or payload.get("id"),
        )
        return delay_ms

    async def start_consumers(
        self,
        email_callback: Callable[[AbstractIncomingMessage], Awaitable[Any]],
        document_callback: Callable[[AbstractIncomingMessage], Awaitable[Any]],
        memory_extract_callback: Callable[
            [AbstractIncomingMessage], Awaitable[Any]
        ],
        study_cards_generate_callback: Callable[
            [AbstractIncomingMessage], Awaitable[Any]
        ],
        mail_dlq_callback: Callable[[AbstractIncomingMessage], Awaitable[Any]],
        document_dlq_callback: Callable[
            [AbstractIncomingMessage], Awaitable[Any]
        ],
        memory_extract_dlq_callback: Callable[
            [AbstractIncomingMessage], Awaitable[Any]
        ],
        study_cards_generate_dlq_callback: Callable[
            [AbstractIncomingMessage], Awaitable[Any]
        ],
    ) -> list[RabbitMQConsumer]:
        mail_consumer = await self._start_consumer("mail_queue", email_callback)
        document_consumer = await self._start_consumer(
            "document_queue", document_callback
        )
        memory_extract_consumer = await self._start_consumer(
            "memory_extract_queue", memory_extract_callback
        )
        study_cards_generate_consumer = await self._start_consumer(
            "study_cards_generate_queue", study_cards_generate_callback
        )
        mail_dlq_consumer = await self._start_consumer(
            "mail_queue_dlq", mail_dlq_callback
        )
        document_dlq_consumer = await self._start_consumer(
            "document_queue_dlq", document_dlq_callback
        )
        memory_extract_dlq_consumer = await self._start_consumer(
            "memory_extract_queue_dlq", memory_extract_dlq_callback
        )
        study_cards_generate_dlq_consumer = await self._start_consumer(
            "study_cards_generate_queue_dlq", study_cards_generate_dlq_callback
        )
        self.logger.info("Started RabbitMQ consumers")
        return [
            mail_consumer,
            document_consumer,
            memory_extract_consumer,
            study_cards_generate_consumer,
            mail_dlq_consumer,
            document_dlq_consumer,
            memory_extract_dlq_consumer,
            study_cards_generate_dlq_consumer,
        ]

    async def stop_consumers(self, consumers: list[RabbitMQConsumer]) -> None:
        for consumer in consumers:
            try:
                await asyncio.wait_for(
                    consumer.queue.cancel(consumer.tag, nowait=True),
                    timeout=2.0,
                )
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception) as e:
                self.logger.debug(
                    "Consumer cancel interrupted tag=%s: %s", consumer.tag, e)
        self.logger.info("Stopped RabbitMQ consumers")

    async def _start_consumer(
        self,
        queue_name: str,
        callback: Callable[[AbstractIncomingMessage], Awaitable[Any]],
    ) -> RabbitMQConsumer:
        match queue_name:
            case "mail_queue":
                queue = self.email_queue
            case "mail_queue_dlq":
                queue = self.email_dlq_queue
            case "document_queue":
                queue = self.document_queue
            case "document_queue_dlq":
                queue = self.document_dlq_queue
            case "memory_extract_queue":
                queue = self.memory_extract_queue
            case "memory_extract_queue_dlq":
                queue = self.memory_extract_dlq_queue
            case "study_cards_generate_queue":
                queue = self.study_cards_generate_queue
            case "study_cards_generate_queue_dlq":
                queue = self.study_cards_generate_dlq_queue
            case _:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid queue name: {queue_name}",
                )

        tag = await queue.consume(callback, no_ack=False)
        return RabbitMQConsumer(queue=queue, tag=tag)

    @property
    def _logger(self) -> Logger:
        return self.logger
