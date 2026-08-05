import json
from logging import Logger

from aio_pika.abc import AbstractIncomingMessage
from pydantic import ValidationError

from app.core.rabbitmq import RabbitMQ, read_retry_count
from app.system.quiz.schema import QuizGenerateRequest


async def handle_quiz_generate(
    message: AbstractIncomingMessage,
    logger: Logger,
    rabbitmq: RabbitMQ,
) -> None:
    payload: dict | None = None

    async with message.process(requeue=False, ignore_processed=True):
        try:
            payload = json.loads(message.body)
            request = QuizGenerateRequest(**payload)
            retry_count = read_retry_count(message.headers)

            logger.info(
                "Received quiz generate message document_id=%s "
                "user_id=%s retry=%s",
                request.document_id,
                request.user_id,
                retry_count,
            )

            # TODO: invoke quiz_agent graph to generate quiz / study cards
            logger.info(
                "Quiz generate stub completed document_id=%s user_id=%s",
                request.document_id,
                request.user_id,
            )
        except (json.JSONDecodeError, ValidationError, TypeError) as e:
            logger.warning(
                "Non-retryable quiz generate payload error: %s",
                e,
            )
            await message.reject(requeue=False)
            return
        except Exception as e:
            logger.exception("Error generating quiz artifacts: %s", e)
            if payload is None:
                await message.reject(requeue=False)
                return

            retry_count = read_retry_count(message.headers)
            if retry_count >= rabbitmq.max_retries:
                logger.error(
                    "Exhausted quiz generate retries document_id=%s "
                    "user_id=%s attempts=%s → DLQ",
                    payload.get("document_id"),
                    payload.get("user_id"),
                    retry_count,
                )
                await message.reject(requeue=False)
                return

            await rabbitmq.schedule_retry(
                "quiz_generate_queue",
                payload,
                retry_count=retry_count,
                headers=message.headers,
            )
            return
