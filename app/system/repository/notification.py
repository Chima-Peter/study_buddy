from datetime import datetime, timezone
from logging import Logger

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import select

from app.system.models.notifications import NotificationDBModel, NotificationModel
from app.system.schemas.notification import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT


class NotificationRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        logger: Logger,
    ):
        self.session_factory = session_factory
        self.logger = logger

    async def create(self, notification: NotificationModel) -> NotificationModel:
        async with self.session_factory() as session:
            db_notification = NotificationDBModel(
                **notification.model_dump_for_db()
            )
            session.add(db_notification)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                self.logger.exception(
                    "Error creating notification id=%s", notification.id
                )
                raise

            await session.refresh(db_notification)
            self.logger.info("Notification created id=%s", db_notification.id)
            return NotificationModel(**db_notification.model_dump())

    async def get_by_id(
        self,
        notification_id: str,
        user_id: str,
    ) -> NotificationModel | None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(NotificationDBModel).where(
                    NotificationDBModel.id == notification_id,
                    NotificationDBModel.user_id == user_id,
                )
            )
            db_notification = result.scalar_one_or_none()
            if db_notification is None:
                return None
            return NotificationModel(**db_notification.model_dump())

    async def list_notifications(
        self,
        user_id: str,
        *,
        limit: int = DEFAULT_LIST_LIMIT,
        cursor: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        unread_only: bool = False,
    ) -> tuple[list[NotificationModel], str | None, bool]:
        limit = min(max(limit, 1), MAX_LIST_LIMIT)

        async with self.session_factory() as session:
            filters = [NotificationDBModel.user_id == user_id]
            if created_after is not None:
                filters.append(NotificationDBModel.created_at >= created_after)
            if created_before is not None:
                filters.append(NotificationDBModel.created_at <= created_before)
            if unread_only:
                filters.append(NotificationDBModel.read_at.is_(None))
            if cursor is not None:
                filters.append(NotificationDBModel.id < cursor)

            query = (
                select(NotificationDBModel)
                .order_by(NotificationDBModel.id.desc())
                .limit(limit + 1)
            )
            query = query.where(*filters)

            result = await session.execute(query)
            db_notifications = list(result.scalars().all())

            has_more = len(db_notifications) > limit
            page = db_notifications[:limit]
            next_cursor = page[-1].id if has_more and page else None

            self.logger.info(
                "Notifications listed count=%s has_more=%s",
                len(page),
                has_more,
            )
            return (
                [NotificationModel(**n.model_dump()) for n in page],
                str(next_cursor) if next_cursor is not None else None,
                has_more,
            )

    async def mark_as_read(
        self,
        notification_id: str,
        user_id: str,
    ) -> NotificationModel | None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(NotificationDBModel).where(
                    NotificationDBModel.id == notification_id,
                    NotificationDBModel.user_id == user_id,
                )
            )
            db_notification = result.scalar_one_or_none()
            if db_notification is None:
                return None

            if db_notification.read_at is None:
                db_notification.read_at = datetime.now(timezone.utc)
                await session.commit()
                await session.refresh(db_notification)
                self.logger.info(
                    "Notification marked read id=%s", notification_id
                )

            return NotificationModel(**db_notification.model_dump())
