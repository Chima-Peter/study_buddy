from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from logging import Logger
from typing import Any

from aio_pika import Channel, DeliveryMode, Message, Queue
from aio_pika.abc import AbstractIncomingMessage
from aio_pika.exceptions import DeliveryError
from fastapi import HTTPException
import json
import uuid_utils


@dataclass
class RabbitMQConsumer:
    queue: Queue
    tag: str


class RabbitMQ:
    def __init__(self, channel: Channel, email_queue: Queue, document_queue: Queue, logger: Logger):
        self.channel = channel
        self.email_queue = email_queue
        self.document_queue = document_queue
        self._logger = logger

    async def publish_message(self, queue_name: str, payload: dict, retry_count: int = 0):
        if retry_count > 3:
            self._logger.error(
                "Publish failed queue=%s after %s retries", queue_name, retry_count)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to publish message to {queue_name} after {retry_count} retries",
            )
        try:
            self._logger.info(
                "Publishing message to %s on retry %s", queue_name, retry_count)
            message = Message(
                body=json.dumps(payload).encode(),
                delivery_mode=DeliveryMode.PERSISTENT,
                message_id=str(uuid_utils.uuid7()),
            )
            await self.channel.default_exchange.publish(
                message=message,
                routing_key=queue_name,
                timeout=5.0,
            )
            self._logger.debug("Published message to queue=%s", queue_name)
        except (DeliveryError, TimeoutError, Exception) as e:
            self._logger.warning(
                "Publish retry queue=%s attempt=%s error=%s", queue_name, retry_count, e)
            await self.publish_message(queue_name, payload, retry_count + 1)

    async def start_consumers(
        self,
        email_callback: Callable[[AbstractIncomingMessage], Awaitable[Any]],
        document_callback: Callable[[AbstractIncomingMessage], Awaitable[Any]],
    ) -> list[RabbitMQConsumer]:
        mail_consumer = await self._start_consumer("mail_queue", email_callback)
        document_consumer = await self._start_consumer("document_queue", document_callback)
        self._logger.info("Started RabbitMQ consumers")
        return [mail_consumer, document_consumer]

    async def stop_consumers(self, consumers: list[RabbitMQConsumer]) -> None:
        for consumer in consumers:
            await consumer.queue.cancel(consumer.tag)
        self._logger.info("Stopped RabbitMQ consumers")

    async def _start_consumer(
        self,
        queue_name: str,
        callback: Callable[[AbstractIncomingMessage], Awaitable[Any]],
    ) -> RabbitMQConsumer:
        match queue_name:
            case "mail_queue":
                queue = self.email_queue
            case "document_queue":
                queue = self.document_queue
            case _:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid queue name: {queue_name}",
                )

        self._logger.info("Consuming from queue=%s", queue_name)
        tag = await queue.consume(callback, no_ack=False)
        return RabbitMQConsumer(queue=queue, tag=tag)
