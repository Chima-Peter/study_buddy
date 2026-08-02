import json
from logging import Logger

from aio_pika.abc import AbstractIncomingMessage


async def handle_memory_extract_dead_letter_queue(
    message: AbstractIncomingMessage,
    logger: Logger,
) -> None:
    async with message.process():
        body = message.body.decode()
        logger.error(
            "Memory extract DLQ message id=%s routing_key=%s body=%s headers=%s",
            message.message_id,
            message.routing_key,
            body,
            message.headers,
        )
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            logger.exception("Invalid memory extract DLQ payload")
            return

        logger.error(
            "Memory extract exhausted retries user_id=%s conversation_id=%s",
            payload.get("user_id"),
            payload.get("conversation_id"),
        )
