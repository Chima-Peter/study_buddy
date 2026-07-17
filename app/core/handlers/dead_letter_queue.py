import json
from logging import Logger

from aio_pika.abc import AbstractIncomingMessage

from app.system.service.document import DocumentService


async def handle_dead_letter_queue(
    message: AbstractIncomingMessage,
    logger: Logger,
    document_service: DocumentService,
) -> None:
    async with message.process():
        logger.error(
            "Dead letter message id=%s routing_key=%s body=%s headers=%s",
            message.message_id,
            message.routing_key,
            message.body.decode(),
            message.headers,
        )

        try:
            payload = json.loads(message.body)
        except json.JSONDecodeError:
            logger.exception("Invalid dead letter payload; cannot mark document failed")
            return

        document_id = payload.get("document_id")
        user_id = payload.get("user_id")
        if not document_id or not user_id:
            return

        updated = await document_service.update_status(
            document_id,
            "failed",
            user_id,
            from_statuses=("pending", "processing", "failed"),
        )
        if updated is None:
            logger.warning(
                "Could not mark document failed from DLQ document_id=%s user_id=%s",
                document_id,
                user_id,
            )
            return

        logger.info(
            "Marked document failed from DLQ document_id=%s user_id=%s",
            document_id,
            user_id,
        )
