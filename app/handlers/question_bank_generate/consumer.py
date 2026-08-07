import json
from logging import Logger

from aio_pika.abc import AbstractIncomingMessage
from app.core.redis import RedisClient
from app.handlers.question_bank_generate.utils import notify_question_bank_status
from app.system.notification.service import NotificationService
from app.utils.llm import is_rate_limit_error
from pydantic import ValidationError

from app.agent.question_bank.graph import QuestionBankGraph
from app.core.rabbitmq import RabbitMQ, read_retry_count
from app.system.question_bank.service import QuestionBankService


async def handle_question_bank_generate(
    message: AbstractIncomingMessage,
    logger: Logger,
    rabbitmq: RabbitMQ,
    question_bank_graph: QuestionBankGraph,
    question_bank_service: QuestionBankService,
    redis: RedisClient,
    notification_service: NotificationService,
) -> None:
    payload: dict | None = None
    name: str | None = None
    document_id: str | None = None
    user_id: str | None = None

    async with message.process(requeue=False, ignore_processed=True):
        try:
            payload = json.loads(message.body)
            retry_count = read_retry_count(message.headers)
            name = payload.get("name")
            document_id = payload.get("document_id")
            user_id = payload.get("user_id")

            logger.info(
                "Received question bank generate message document_id=%s "
                "user_id=%s retry=%s",
                document_id,
                user_id,
                retry_count,
            )

            graph = question_bank_graph.start()
            await graph.ainvoke(
                {
                    "document_id": document_id,
                    "user_id": user_id,
                },
                config={
                    "configurable": {
                        "thread_id": (
                            f"question-bank:{user_id}:{document_id}"
                        ),
                    }
                },
            )

            await notify_question_bank_status(
                redis,
                logger,
                user_id,
                notification_service,
                document_id=document_id,
                name=name,
                status="success",
                comment=(
                    f'Question bank for "{name}" is ready.'
                ),
            )

            logger.info(
                "Question bank generate completed document_id=%s user_id=%s",
                document_id,
                user_id,
            )
        except (json.JSONDecodeError, ValidationError, TypeError) as e:
            logger.warning(
                "Non-retryable question bank generate payload error: %s",
                e,
            )
            await message.reject(requeue=False)
            return
        except Exception as e:
            logger.exception("Error generating question bank: %s", e)
            if payload is None:
                await message.reject(requeue=False)
                return

            retry_count = read_retry_count(message.headers)
            if retry_count >= rabbitmq.max_retries:
                document_id = payload.get("document_id")
                user_id = payload.get("user_id")
                name = payload.get("name") or document_id

                if document_id and user_id:
                    try:
                        if is_rate_limit_error(e):
                            reason = (
                                "Question bank generation failed because of "
                                "rate limiting errors across multiple retries."
                            )
                        else:
                            reason = (
                                "Question bank generation failed after "
                                "exhausting multiple retries."
                            )

                        await question_bank_service.mark_failed(
                            document_id,
                            user_id,
                            reason=reason,
                        )
                    except Exception:
                        logger.exception(
                            "Failed to mark question bank failed "
                            "document_id=%s user_id=%s",
                            document_id,
                            user_id,
                        )

                logger.error(
                    "Exhausted question bank generate retries "
                    "document_id=%s user_id=%s attempts=%s → DLQ",
                    document_id,
                    user_id,
                    retry_count,
                )

                await notify_question_bank_status(
                    redis,
                    logger,
                    user_id,
                    notification_service,
                    name=name,
                    document_id=document_id,
                    status="failed",
                    comment=(
                        f'Question bank generation for "{name}" '
                        "failed after all retries."
                    ),
                )

                await message.reject(requeue=False)
                return

            await rabbitmq.schedule_retry(
                "question_bank_generate_queue",
                payload,
                retry_count=retry_count,
                headers=message.headers,
            )
            return
