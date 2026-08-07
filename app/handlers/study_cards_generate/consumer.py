import json
from logging import Logger

from aio_pika.abc import AbstractIncomingMessage
from app.core.redis import RedisClient
from app.handlers.study_cards_generate.utils import notify_study_cards_status
from app.system.notification.service import NotificationService
from pydantic import ValidationError

from app.agent.study_cards_agent.graph import StudyCardsGraph
from app.core.rabbitmq import RabbitMQ, read_retry_count
from app.system.study_cards.service import StudyCardsService


async def handle_study_cards_generate(
    message: AbstractIncomingMessage,
    logger: Logger,
    rabbitmq: RabbitMQ,
    study_cards_graph: StudyCardsGraph,
    study_cards_service: StudyCardsService,
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
                "Received study cards generate message document_id=%s "
                "user_id=%s retry=%s",
                document_id,
                user_id,
                retry_count,
            )

            graph = study_cards_graph.start()
            await graph.ainvoke(
                {
                    "document_id": document_id,
                    "user_id": user_id,
                },
                config={
                    "configurable": {
                        "thread_id": (
                            f"study-cards:{user_id}:{document_id}"
                        ),
                    }
                },
            )

            await notify_study_cards_status(
                redis,
                logger,
                user_id,
                notification_service,
                document_id=document_id,
                name=name,
                status="success",
                comment=(
                    f'Study cards for "{name}" are ready.'
                ),
            )

            logger.info(
                "Study cards generate completed document_id=%s user_id=%s",
                document_id,
                user_id,
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
                document_id = payload.get("document_id")
                user_id = payload.get("user_id")
                name = payload.get("name") or document_id
                if document_id and user_id:
                    try:
                        await study_cards_service.mark_failed(document_id, user_id)
                    except Exception:
                        logger.exception(
                            "Failed to mark study cards failed "
                            "document_id=%s user_id=%s",
                            document_id,
                            user_id,
                        )
                logger.error(
                    "Exhausted study cards generate retries document_id=%s "
                    "user_id=%s attempts=%s → DLQ",
                    document_id,
                    user_id,
                    retry_count,
                )
                await notify_study_cards_status(
                    redis,
                    logger,
                    user_id,
                    notification_service,
                    name=name,
                    document_id=document_id,
                    status="failed",
                    comment=(
                        f'Study cards generation for "{name}" '
                        "failed after all retries."
                    ),
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
