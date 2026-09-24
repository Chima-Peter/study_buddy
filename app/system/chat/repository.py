from datetime import datetime
from logging import Logger

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import select

from app.system.chat.model import ChatDBModel, ChatModel
from app.system.conversation.model import ConversationDBModel

DEFAULT_SUBSEQUENT_LIMIT = 20
MAX_SUBSEQUENT_LIMIT = 50


class ChatRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        logger: Logger,
    ):
        self.session_factory = session_factory
        self.logger = logger

    async def get(
        self,
        chat_id: str,
        user_id: str,
    ) -> ChatModel | None:
        async with self.session_factory() as session:
            db_chat = await session.scalar(
                select(ChatDBModel)
                .join(
                    ConversationDBModel,
                    ConversationDBModel.id == ChatDBModel.conversation_id,
                )
                .where(
                    ChatDBModel.id == chat_id,
                    ConversationDBModel.user_id == user_id,
                )
            )
            if db_chat is None:
                return None
            return ChatModel(**db_chat.model_dump())

    async def list_subsequent(
        self,
        conversation_id: str,
        *,
        cursor: str,
        before_created_at: datetime | None = None,
        limit: int = DEFAULT_SUBSEQUENT_LIMIT,
    ) -> tuple[list[ChatModel], str | None, bool]:
        """Page chats with ``id > cursor`` (uuid7 ≈ time order).

        First cursor should be the given chat id so that chat is excluded.
        Optional ``before_created_at`` caps the window (exclusive).
        """
        limit = min(max(limit, 1), MAX_SUBSEQUENT_LIMIT)
        async with self.session_factory() as session:
            filters = [
                ChatDBModel.conversation_id == conversation_id,
                ChatDBModel.id > cursor,
            ]
            if before_created_at is not None:
                filters.append(ChatDBModel.created_at < before_created_at)

            result = await session.execute(
                select(ChatDBModel)
                .where(*filters)
                .order_by(ChatDBModel.id.asc())
                .limit(limit + 1)
            )
            db_rows = list(result.scalars().all())

            has_more = len(db_rows) > limit
            page = db_rows[:limit]
            next_cursor = str(page[-1].id) if has_more and page else None

            chats = [ChatModel(**row.model_dump()) for row in page]
            self.logger.info(
                "Subsequent chats listed conversation_id=%s count=%s "
                "has_more=%s cursor=%s",
                conversation_id,
                len(chats),
                has_more,
                cursor,
            )
            return chats, next_cursor, has_more

    async def delete_by_ids(self, chat_ids: list[str]) -> int:
        if not chat_ids:
            return 0
        async with self.session_factory() as session:
            result = await session.execute(
                delete(ChatDBModel).where(ChatDBModel.id.in_(chat_ids))
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                self.logger.exception(
                    "Error deleting chats count=%s",
                    len(chat_ids),
                )
                raise
            deleted = result.rowcount or 0
            self.logger.info("Chats deleted count=%s", deleted)
            return deleted

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

    async def update_continuation_key(
        self,
        chat_id: str,
        continuation_key: str,
        user_id: str,
    ) -> bool:
        async with self.session_factory() as session:
            db_chat = await session.scalar(
                select(ChatDBModel)
                .join(
                    ConversationDBModel,
                    ConversationDBModel.id == ChatDBModel.conversation_id,
                )
                .where(
                    ChatDBModel.id == chat_id,
                    ConversationDBModel.user_id == user_id,
                )
            )
            if db_chat is None:
                self.logger.warning(
                    "Chat not found for continuation_key update "
                    "chat_id=%s user_id=%s",
                    chat_id,
                    user_id,
                )
                return False

            db_chat.continuation_key = continuation_key
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                self.logger.exception(
                    "Error updating continuation_key chat_id=%s",
                    chat_id,
                )
                raise

            self.logger.info(
                "Continuation key updated chat_id=%s",
                chat_id,
            )
            return True

    async def update_turn(
        self,
        chat_id: str,
        user_id: str,
        *,
        query: str,
        response: str,
        query_message_id: str | None,
        response_message_id: str | None,
        audit: dict,
    ) -> ChatModel | None:
        async with self.session_factory() as session:
            db_chat = await session.scalar(
                select(ChatDBModel)
                .join(
                    ConversationDBModel,
                    ConversationDBModel.id == ChatDBModel.conversation_id,
                )
                .where(
                    ChatDBModel.id == chat_id,
                    ConversationDBModel.user_id == user_id,
                )
            )
            if db_chat is None:
                self.logger.warning(
                    "Chat not found for turn update chat_id=%s user_id=%s",
                    chat_id,
                    user_id,
                )
                return None

            db_chat.query = query
            db_chat.chat = response
            db_chat.query_message_id = query_message_id
            db_chat.response_message_id = response_message_id
            db_chat.audit = audit
            db_chat.continuation_key = None
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                self.logger.exception(
                    "Error updating chat turn chat_id=%s",
                    chat_id,
                )
                raise

            await session.refresh(db_chat)
            self.logger.info(
                "Chat turn updated chat_id=%s conversation_id=%s",
                db_chat.id,
                db_chat.conversation_id,
            )
            return ChatModel(**db_chat.model_dump())
