from logging import Logger

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import select

from app.system.models.chat import ChatModel
from app.system.models.conversation import ConversationDBModel, ConversationModel


class ConversationRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        logger: Logger,
    ):
        self.session_factory = session_factory
        self.logger = logger

    async def create(
        self,
        conversation: ConversationModel,
    ) -> ConversationModel:
        async with self.session_factory() as session:
            db_conversation = ConversationDBModel(
                **conversation.model_dump_for_db()
            )
            session.add(db_conversation)
            await session.commit()
            await session.refresh(db_conversation)
            self.logger.info(
                "Conversation created id=%s user_id=%s",
                db_conversation.id,
                db_conversation.user_id,
            )
            return ConversationModel(**db_conversation.model_dump())

    async def list_by_user(self, user_id: str) -> list[ConversationModel]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(ConversationDBModel)
                .where(ConversationDBModel.user_id == user_id)
                .order_by(ConversationDBModel.created_at.desc())
            )
            return [
                ConversationModel(**conversation.model_dump())
                for conversation in result.scalars().all()
            ]

    async def get_with_chats(
        self,
        conversation_id: str,
        user_id: str,
    ) -> tuple[ConversationModel, list[ChatModel]] | None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(ConversationDBModel)
                .options(selectinload(ConversationDBModel.chats))
                .where(
                    ConversationDBModel.id == conversation_id,
                    ConversationDBModel.user_id == user_id,
                )
            )
            db_conversation = result.scalar_one_or_none()
            if db_conversation is None:
                return None

            conversation = ConversationModel(**db_conversation.model_dump())
            chats = [
                ChatModel(**chat.model_dump())
                for chat in db_conversation.chats
            ]
            return conversation, chats

    async def update_title(
        self,
        conversation_id: str,
        user_id: str,
        title: str,
    ) -> ConversationModel | None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(ConversationDBModel).where(
                    ConversationDBModel.id == conversation_id,
                    ConversationDBModel.user_id == user_id,
                )
            )
            db_conversation = result.scalar_one_or_none()
            if db_conversation is None:
                return None

            db_conversation.title = title
            await session.commit()
            await session.refresh(db_conversation)
            return ConversationModel(**db_conversation.model_dump())
