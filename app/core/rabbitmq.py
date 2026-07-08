from collections.abc import Awaitable, Callable
from logging import Logger
from typing import Any

from aio_pika.abc import AbstractIncomingMessage
from fastapi import HTTPException
from aio_pika import Message, DeliveryMode, Channel, Queue
import json
import uuid_utils

from aio_pika.exceptions import DeliveryError


class RabbitMQ:
    def __init__(self, channel: Channel, email_queue: Queue, document_queue: Queue, logger: Logger):
        self.channel = channel
        self.email_queue = email_queue
        self.document_queue = document_queue
        self.logger = logger

    async def publish_message(self, queue_name: str, payload: dict, retry_count: int = 0):
        if retry_count > 3:
            self.logger.error(
                "Failed to publish message to %s after %s retries",
                queue_name,
                retry_count,
            )
            raise HTTPException(
                status_code=500,
                detail=f"Failed to publish message to {queue_name} after {retry_count} retries",
            )
        try:
            self.logger.info("Publishing message to %s on retry %s", queue_name, retry_count)
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
        except DeliveryError as e:
            self.logger.error(
                "Failed to publish message to %s (attempt %s): %s",
                queue_name,
                retry_count,
                e,
            )
            await self.publish_message(queue_name, payload, retry_count + 1)
        except TimeoutError as e:
            self.logger.error(
                "Timeout while publishing message to %s (attempt %s): %s",
                queue_name,
                retry_count,
                e,
            )
            await self.publish_message(queue_name, payload, retry_count + 1)
        except Exception as e:
            self.logger.error(
                "Failed to publish message to %s (attempt %s): %s",
                queue_name,
                retry_count,
                e,
            )
            await self.publish_message(queue_name, payload, retry_count + 1)


    async def consume_message(
        self,
        queue_name: str,
        callback: Callable[[AbstractIncomingMessage], Awaitable[Any]],
    ) -> None:
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

        self.logger.info("Consuming messages from %s queue", queue_name)
        await queue.consume(callback, no_ack=False)