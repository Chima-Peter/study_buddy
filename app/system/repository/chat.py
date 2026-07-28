from logging import Logger

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import select

from app.system.models.chat import ChatDBModel, ChatModel
from app.system.models.conversation import ConversationDBModel


class ChatRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        logger: Logger,
    ):
        self.session_factory = session_factory
        self.logger = logger

    async def conversation_belongs_to_user(
        self,
        conversation_id: str,
        user_id: str,
    ) -> bool:
        async with self.session_factory() as session:
            conversation = await session.scalar(
                select(ConversationDBModel.id).where(
                    ConversationDBModel.id == conversation_id,
                    ConversationDBModel.user_id == user_id,
                )
            )
            return conversation is not None

    async def create(self, chat: ChatModel, user_id: str) -> ChatModel:
        async with self.session_factory() as session:
            conversation = await session.scalar(
                select(ConversationDBModel).where(
                    ConversationDBModel.id == chat.conversation_id,
                    ConversationDBModel.user_id == user_id,
                )
            )
            if conversation is None:
                raise ValueError("Conversation not found")

            db_chat = ChatDBModel(**chat.model_dump_for_db())
            session.add(db_chat)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                self.logger.exception(
                    "Error creating chat id=%s conversation_id=%s",
                    chat.id,
                    chat.conversation_id,
                )
                raise

            await session.refresh(db_chat)
            self.logger.info(
                "Chat created id=%s conversation_id=%s",
                db_chat.id,
                db_chat.conversation_id,
            )
            return ChatModel(**db_chat.model_dump())
