from datetime import datetime
from logging import Logger

from app.system.notification.model import NotificationModel
from app.system.notification.repository import NotificationRepository
from app.system.notification.schema import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    CreateNotificationRequest,
    MarkNotificationsReadResponseData,
    NotificationListResponseData,
    NotificationResponse,
)
from app.utils.errors import NotificationNotFoundError


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
        user_id: str,
    ) -> NotificationResponse:
        notification = NotificationModel.from_request(request, user_id)
        result = await self.repository.create(notification)
        return result.to_response()

    async def list_notifications(
        self,
        user_id: str,
        *,
        limit: int = DEFAULT_LIST_LIMIT,
        cursor: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        unread_only: bool = False,
    ) -> NotificationListResponseData:
        notifications, next_cursor, has_more = await self.repository.list_notifications(
            user_id,
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

    async def mark_as_read(
        self,
        notification_id: str,
        user_id: str,
    ) -> NotificationResponse:
        notification = await self.repository.mark_as_read(notification_id, user_id)
        if notification is None:
            raise NotificationNotFoundError(notification_id)
        return notification.to_response()

    async def mark_many_as_read(
        self,
        notification_ids: list[str],
        user_id: str,
    ) -> MarkNotificationsReadResponseData:
        unique_ids = list(dict.fromkeys(notification_ids))
        notifications = await self.repository.mark_many_as_read(
            unique_ids, user_id
        )
        found_ids = {notification.id for notification in notifications}
        missing_ids = [nid for nid in unique_ids if nid not in found_ids]
        if missing_ids:
            raise NotificationNotFoundError(missing_ids)

        items = [n.to_response() for n in notifications]
        return MarkNotificationsReadResponseData(
            items=items,
            marked_count=len(items),
        )
