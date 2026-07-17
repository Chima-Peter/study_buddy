from datetime import datetime
from logging import Logger

from app.system.models.notifications import NotificationModel
from app.system.repository.notification import NotificationRepository
from app.system.schemas.notification import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    CreateNotificationRequest,
    NotificationListResponseData,
    NotificationResponse,
)


class NotificationService:
    def __init__(
        self,
        repository: NotificationRepository,
        logger: Logger,
    ):
        self.repository = repository
        self.logger = logger

    async def create_notification(
        self,
        request: CreateNotificationRequest,
    ) -> NotificationResponse:
        notification = NotificationModel.from_request(request)
        result = await self.repository.create(notification)
        return result.to_response()

    async def list_notifications(
        self,
        *,
        limit: int = DEFAULT_LIST_LIMIT,
        cursor: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        unread_only: bool = False,
    ) -> NotificationListResponseData:
        notifications, next_cursor, has_more = await self.repository.list(
            limit=limit,
            cursor=cursor,
            created_after=created_after,
            created_before=created_before,
            unread_only=unread_only,
        )
        return NotificationListResponseData(
            items=[n.to_response() for n in notifications],
            next_cursor=next_cursor,
            has_more=has_more,
            limit=min(max(limit, 1), MAX_LIST_LIMIT),
        )

    async def mark_as_read(self, notification_id: str) -> NotificationResponse:
        notification = await self.repository.mark_as_read(notification_id)
        if notification is None:
            raise ValueError(f"Notification not found: {notification_id}")
        return notification.to_response()
