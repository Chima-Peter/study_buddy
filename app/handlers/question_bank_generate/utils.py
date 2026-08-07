from logging import Logger
from app.core.redis import RedisClient
from app.system.notification.schema import CreateNotificationRequest, EventPayload
from app.system.notification.service import NotificationService


async def notify_question_bank_status(
    redis: RedisClient,
    logger: Logger,
    user_id: str,
    notification_service: NotificationService,
    *,
    document_id: str,
    name: str | None,
    status: str,
    comment: str | None = None,
) -> None:
    try:
        await notification_service.create_notification(
            CreateNotificationRequest(
                title="Question Bank Status",
                content=comment
                or f"Question bank for {name} status changed to {status}",
            ),
            user_id,
        )
        await redis.publish_to_user(
            user_id,
            EventPayload(
                type="question_bank.status",
                data={
                    "document_id": document_id,
                    "name": name,
                    "status": status,
                    "comment": comment,
                },
            ),
        )
    except Exception:
        logger.exception(
            "Failed to publish question bank status notification "
            "user_id=%s document_id=%s status=%s",
            user_id,
            document_id,
            status,
        )
