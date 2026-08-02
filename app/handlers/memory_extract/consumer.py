import json
from logging import Logger

from aio_pika.abc import AbstractIncomingMessage
from pydantic import ValidationError

from app.core.rabbitmq import RabbitMQ, read_retry_count
from app.memory.schema import MemoryExtractRequest
from app.memory.service import MemoryService


async def handle_memory_extract(
    message: AbstractIncomingMessage,
    memory_service: MemoryService,
    logger: Logger,
    rabbitmq: RabbitMQ,
) -> None:
    payload: dict | None = None

    async with message.process(requeue=False, ignore_processed=True):
        try:
            payload = json.loads(message.body)
            request = MemoryExtractRequest(**payload)
            retry_count = read_retry_count(message.headers)

            logger.info(
                "Received memory extract message user_id=%s "
                "conversation_id=%s retry=%s",
                request.user_id,
                request.conversation_id,
                retry_count,
            )

            await memory_service.store(
                user_id=request.user_id,
                context=request.context,
                known_memories=request.known_memories,
            )
            logger.info(
                "Memory extract completed user_id=%s conversation_id=%s",
                request.user_id,
                request.conversation_id,
            )
        except (json.JSONDecodeError, ValidationError, TypeError) as e:
            logger.warning(
                "Non-retryable memory extract payload error: %s",
                e,
            )
            await message.reject(requeue=False)
            return
        except Exception as e:
            logger.exception("Error extracting memories: %s", e)
            if payload is None:
                await message.reject(requeue=False)
                return

            retry_count = read_retry_count(message.headers)
            if retry_count >= rabbitmq.max_retries:
                logger.error(
                    "Exhausted memory extract retries user_id=%s "
                    "conversation_id=%s attempts=%s → DLQ",
                    payload.get("user_id"),
                    payload.get("conversation_id"),
                    retry_count,
                )
                await message.reject(requeue=False)
                return

            await rabbitmq.schedule_retry(
                "memory_extract_queue",
                payload,
                retry_count=retry_count,
                headers=message.headers,
            )
            return
