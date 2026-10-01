import json
from logging import Logger

from aio_pika.abc import AbstractIncomingMessage

from app.core.redis import RedisClient
from app.handlers.document.util import notify_document_status
from app.system.document.service import DocumentService
from app.system.notification.service import NotificationService


async def handle_document_dead_letter_queue(
    message: AbstractIncomingMessage,
    logger: Logger,
    document_service: DocumentService,
    redis: RedisClient,
    notification_service: NotificationService,
) -> None:
    async with message.process():
        logger.error(
            "Document DLQ message id=%s routing_key=%s body=%s headers=%s",
            message.message_id,
            message.routing_key,
            message.body.decode(),
            message.headers,
        )

        try:
            payload = json.loads(message.body)
        except json.JSONDecodeError:
            logger.exception("Invalid document DLQ payload")
            return

        document_id = payload.get("document_id")
        user_id = payload.get("user_id")
        if not document_id or not user_id:
            return

        try:
            existing = await document_service.get_document_by_id(
                document_id, user_id
            )
        except ValueError:
            logger.warning(
                "DLQ document not found document_id=%s user_id=%s",
                document_id,
                user_id,
            )
            return

        await notify_document_status(
            redis,
            logger,
            user_id,
            notification_service,
            document_id=existing.id,
            name=existing.name,
            status=existing.status,
            comment=existing.comment,
        )
        logger.info(
            "DLQ notified document_id=%s user_id=%s status=%s",
            document_id,
            user_id,
            existing.status,
        )
