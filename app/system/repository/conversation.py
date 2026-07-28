from logging import Logger

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import select

from app.system.models.conversations import ConversationDBModel, ConversationModel


class ConversationRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        logger: Logger,
    ):
        self.session_factory = session_factory
        self.logger = logger

    async def create(
        self, conversation: ConversationModel
    ) -> ConversationModel:
        async with self.session_factory() as session:
            db_conversation = ConversationDBModel(
                **conversation.model_dump_for_db()
            )
            session.add(db_conversation)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                self.logger.exception(
                    "Error creating conversation id=%s user_id=%s",
                    conversation.id,
                    conversation.user_id,
                )
                raise

            await session.refresh(db_conversation)
            self.logger.info(
                "Conversation created id=%s user_id=%s",
                db_conversation.id,
                db_conversation.user_id,
            )
            return ConversationModel(**db_conversation.model_dump())

    async def list_by_user(
        self,
        user_id: str,
        *,
        limit: int = 50,
    ) -> list[ConversationModel]:
        limit = min(max(limit, 1), 100)
        async with self.session_factory() as session:
            result = await session.execute(
                select(ConversationDBModel)
                .where(ConversationDBModel.user_id == user_id)
                .order_by(ConversationDBModel.created_at.desc())
                .limit(limit)
            )
            return [
                ConversationModel(**conversation.model_dump())
                for conversation in result.scalars().all()
            ]
