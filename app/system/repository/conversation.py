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
        self.logger.info(
            "Creating conversation id=%s user_id=%s",
            conversation.id,
            conversation.user_id,
        )
        async with self.session_factory() as session:
            db_conversation = ConversationDBModel(
                **conversation.model_dump_for_db()
            )
            session.add(db_conversation)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                self.logger.exception(
                    "Failed to create conversation id=%s user_id=%s",
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

    async def list_by_user(self, user_id: str) -> list[ConversationModel]:
        self.logger.info("Listing conversations user_id=%s", user_id)
        async with self.session_factory() as session:
            result = await session.execute(
                select(ConversationDBModel)
                .where(ConversationDBModel.user_id == user_id)
                .order_by(ConversationDBModel.created_at.desc())
            )
            if result is None:
                self.logger.info(
                    "No conversations found user_id=%s",
                    user_id,
                )
                return []
            conversations = [
                ConversationModel(**conversation.model_dump())
                for conversation in result.scalars().all()
            ]
            self.logger.info(
                "Conversations listed user_id=%s count=%s",
                user_id,
                len(conversations),
            )
            return conversations

    async def get_with_chats(
        self,
        conversation_id: str,
        user_id: str,
    ) -> tuple[ConversationModel, list[ChatModel]] | None:
        self.logger.info(
            "Getting conversation id=%s user_id=%s",
            conversation_id,
            user_id,
        )
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
                self.logger.info(
                    "Conversation not found id=%s user_id=%s",
                    conversation_id,
                    user_id,
                )
                return None

            conversation = ConversationModel(**db_conversation.model_dump())
            chats = [
                ChatModel(**chat.model_dump())
                for chat in db_conversation.chats
            ]
            self.logger.info(
                "Conversation retrieved id=%s user_id=%s chat_count=%s",
                conversation_id,
                user_id,
                len(chats),
            )
            return conversation, chats

    async def get(
        self,
        conversation_id: str,
        user_id: str,
    ) -> ConversationModel | None:
        self.logger.info(
            "Getting conversation id=%s user_id=%s",
            conversation_id,
            user_id,
        )
        async with self.session_factory() as session:
            result = await session.execute(
                select(ConversationDBModel).where(
                    ConversationDBModel.id == conversation_id,
                    ConversationDBModel.user_id == user_id,
                )
            )
            db_conversation = result.scalar_one_or_none()
            if db_conversation is None:
                self.logger.info(
                    "Conversation not found id=%s user_id=%s",
                    conversation_id,
                    user_id,
                )
                return None
            return ConversationModel(**db_conversation.model_dump())

    async def update_title(
        self,
        conversation_id: str,
        user_id: str,
        title: str,
    ) -> ConversationModel | None:
        self.logger.info(
            "Updating conversation title id=%s user_id=%s",
            conversation_id,
            user_id,
        )
        async with self.session_factory() as session:
            result = await session.execute(
                select(ConversationDBModel).where(
                    ConversationDBModel.id == conversation_id,
                    ConversationDBModel.user_id == user_id,
                )
            )
            db_conversation = result.scalar_one_or_none()
            if db_conversation is None:
                self.logger.info(
                    "Conversation not found for title update id=%s user_id=%s",
                    conversation_id,
                    user_id,
                )
                return None

            db_conversation.title = title
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                self.logger.exception(
                    "Failed to update conversation title id=%s user_id=%s",
                    conversation_id,
                    user_id,
                )
                raise
            await session.refresh(db_conversation)
            self.logger.info(
                "Conversation title updated id=%s user_id=%s",
                conversation_id,
                user_id,
            )
            return ConversationModel(**db_conversation.model_dump())

    async def update_summary(
        self,
        conversation_id: str,
        user_id: str,
        summary: str,
    ) -> ConversationModel | None:
        self.logger.info(
            "Updating conversation summary id=%s user_id=%s",
            conversation_id,
            user_id,
        )
        async with self.session_factory() as session:
            result = await session.execute(
                select(ConversationDBModel).where(
                    ConversationDBModel.id == conversation_id,
                    ConversationDBModel.user_id == user_id,
                )
            )
            db_conversation = result.scalar_one_or_none()
            if db_conversation is None:
                self.logger.info(
                    "Conversation not found for summary update id=%s user_id=%s",
                    conversation_id,
                    user_id,
                )
                return None

            db_conversation.summary = summary
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                self.logger.exception(
                    "Failed to update conversation summary id=%s user_id=%s",
                    conversation_id,
                    user_id,
                )
                raise
            await session.refresh(db_conversation)
            self.logger.info(
                "Conversation summary updated id=%s user_id=%s",
                conversation_id,
                user_id,
            )
            return ConversationModel(**db_conversation.model_dump())
