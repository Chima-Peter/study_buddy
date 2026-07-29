
from logging import Logger
from app.core.redis import RedisClient
from app.system.schemas.document import DocumentResponse
from app.system.schemas.notification import CreateNotificationRequest, EventPayload
from app.system.service.document import DocumentService
from app.system.service.notification import NotificationService


def is_file_not_found_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    status_code = getattr(exc, "response", None)
    code = getattr(status_code, "status_code", None) if status_code is not None else None
    if code == 404:
        return True
    if getattr(exc, "status_code", None) == 404:
        return True
    return any(
        token in text
        for token in (
            "404",
            "not found",
            "nosuchkey",
            "no such file",
            "object not found",
        )
    )


async def notify_document_status(
    redis: RedisClient,
    logger: Logger,
    user_id: str,
    document: DocumentResponse,
    notification_service: NotificationService,
) -> None:
    try:
        await notification_service.create_notification(
            CreateNotificationRequest(
                title="Document Status",
                content=document.comment
                or f"{document.name} status changed to {document.status}",
            ),
            user_id,
        )
        await redis.publish_to_user(
            user_id,
            EventPayload(
                type="document.status",
                data={
                    "document_id": document.id,
                    "name": document.name,
                    "status": document.status,
                    "comment": document.comment,
                },
            ),
        )
    except Exception:
        logger.exception(
            "Failed to publish document status notification "
            "user_id=%s document_id=%s status=%s",
            user_id,
            document.id,
            document.status,
        )


async def continue_ingestion(
    document_service: DocumentService,
    document_id: str,
    user_id: str,
    logger: Logger,
    *,
    file_name: str | None = None,
) -> bool:
    try:
        document = await document_service.get_document_by_id(document_id, user_id)
    except ValueError:
        logger.info(
            "Document not found file=%s user_id=%s document_id=%s",
            file_name,
            user_id,
            document_id,
        )
        return False

    if document.status == "completed":
        logger.info(
            "Document already completed file=%s user_id=%s document_id=%s",
            file_name,
            user_id,
            document_id,
        )
        return False
    if document.status == "cancelled":
        logger.info(
            "Document ingestion already cancelled file=%s user_id=%s document_id=%s",
            file_name,
            user_id,
            document_id,
        )
        return False
    return True
