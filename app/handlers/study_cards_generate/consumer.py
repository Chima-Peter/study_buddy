import json
from logging import Logger

from aio_pika.abc import AbstractIncomingMessage
from pydantic import ValidationError

from app.agent.study_cards_agent.graph import StudyCardsGraph
from app.core.rabbitmq import RabbitMQ, read_retry_count
from app.system.study_cards.schema import StudyCardsGenerateRequest


async def handle_study_cards_generate(
    message: AbstractIncomingMessage,
    logger: Logger,
    rabbitmq: RabbitMQ,
    study_cards_graph: StudyCardsGraph,
) -> None:
    payload: dict | None = None

    async with message.process(requeue=False, ignore_processed=True):
        try:
            payload = json.loads(message.body)
            request = StudyCardsGenerateRequest(**payload)
            retry_count = read_retry_count(message.headers)

            logger.info(
                "Received study cards generate message document_id=%s "
                "user_id=%s retry=%s",
                request.document_id,
                request.user_id,
                retry_count,
            )

            graph = study_cards_graph.start()
            await graph.ainvoke(
                {
                    "document_id": request.document_id,
                    "user_id": request.user_id,
                },
                config={
                    "configurable": {
                        "thread_id": (
                            f"study-cards:{request.user_id}:{request.document_id}"
                        ),
                    }
                },
            )

            logger.info(
                "Study cards generate completed document_id=%s user_id=%s",
                request.document_id,
                request.user_id,
            )
        except (json.JSONDecodeError, ValidationError, TypeError) as e:
            logger.warning(
                "Non-retryable study cards generate payload error: %s",
                e,
            )
            await message.reject(requeue=False)
            return
        except Exception as e:
            logger.exception("Error generating study cards: %s", e)
            if payload is None:
                await message.reject(requeue=False)
                return

            retry_count = read_retry_count(message.headers)
            if retry_count >= rabbitmq.max_retries:
                logger.error(
                    "Exhausted study cards generate retries document_id=%s "
                    "user_id=%s attempts=%s → DLQ",
                    payload.get("document_id"),
                    payload.get("user_id"),
                    retry_count,
                )
                await message.reject(requeue=False)
                return

            await rabbitmq.schedule_retry(
                "study_cards_generate_queue",
                payload,
                retry_count=retry_count,
                headers=message.headers,
            )
            return
