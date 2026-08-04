import json
from logging import Logger

from aio_pika.abc import AbstractIncomingMessage

from app.core.redis import RedisClient
from app.handlers.document.util import notify_document_status
from app.system.document.schema import (
    DOCUMENT_STATUS_COMMENTS,
    ingest_failure_comment,
)
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
            logger.exception(
                "Invalid document DLQ payload; cannot mark document failed"
            )
            return

        document_id = payload.get("document_id")
        user_id = payload.get("user_id")
        if not document_id or not user_id:
            return

        # Handler already sets a specific failure comment before reject.
        # Preserve it; only fill a DLQ fallback when still pending/processing.
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

        comment = ingest_failure_comment(
            "processing could not be completed",
            exhausted_retries=True,
        )

        if existing.status == "failed" and existing.comment not in (
            None,
            DOCUMENT_STATUS_COMMENTS["failed"],
        ):
            logger.info(
                "DLQ skipped comment overwrite document_id=%s user_id=%s "
                "comment=%s",
                document_id,
                user_id,
                comment,
            )
            await notify_document_status(
                redis,
                logger,
                user_id,
                existing,
                notification_service,
            )
            return

        updated = await document_service.update_status(
            document_id,
            "failed",
            user_id,
            from_statuses=("pending", "processing", "failed"),
            comment=comment,
        )
        if updated is None:
            logger.warning(
                "Could not mark document failed from DLQ document_id=%s user_id=%s",
                document_id,
                user_id,
            )
            return

        await notify_document_status(
            redis,
            logger,
            user_id,
            updated,
            notification_service,
        )
        logger.info(
            "Marked document failed from DLQ document_id=%s user_id=%s comment=%s",
            document_id,
            user_id,
            comment,
        )
