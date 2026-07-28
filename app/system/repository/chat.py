from logging import Logger

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import select

from app.system.models.chat import ChatDBModel, ChatModel


class ChatRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        logger: Logger,
    ):
        self.session_factory = session_factory
        self.logger = logger

    async def create(self, chat: ChatModel) -> ChatModel:
        async with self.session_factory() as session:
            db_chat = ChatDBModel(**chat.model_dump_for_db())
            session.add(db_chat)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                self.logger.exception(
                    "Error creating chat id=%s user_id=%s",
                    chat.id,
                    chat.user_id,
                )
                raise

            await session.refresh(db_chat)
            self.logger.info(
                "Chat created id=%s user_id=%s",
                db_chat.id,
                db_chat.user_id,
            )
            return ChatModel(**db_chat.model_dump())

    async def list_by_user(
        self,
        user_id: str,
        *,
        limit: int = 50,
    ) -> list[ChatModel]:
        limit = min(max(limit, 1), 100)
        async with self.session_factory() as session:
            result = await session.execute(
                select(ChatDBModel)
                .where(ChatDBModel.user_id == user_id)
                .order_by(ChatDBModel.created_at.desc())
                .limit(limit)
            )
            return [
                ChatModel(**chat.model_dump())
                for chat in result.scalars().all()
            ]
