from logging import Logger

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import select

from app.system.chat.model import ChatModel
from app.system.conversation.model import ConversationDBModel, ConversationModel
from app.system.conversation.schema import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT, STATUS_LITERAL


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

    async def list_by_user(
        self,
        user_id: str,
        *,
        limit: int = DEFAULT_LIST_LIMIT,
        cursor: str | None = None,
        status: STATUS_LITERAL | None = None,
    ) -> tuple[list[ConversationModel], str | None, bool]:
        limit = min(max(limit, 1), MAX_LIST_LIMIT)
        self.logger.info(
            "Listing conversations user_id=%s limit=%s cursor=%s status=%s",
            user_id,
            limit,
            cursor,
            status,
        )
        async with self.session_factory() as session:
            filters = [ConversationDBModel.user_id == user_id]
            if status is not None:
                filters.append(ConversationDBModel.status == status)
            if cursor is not None:
                filters.append(ConversationDBModel.id < cursor)

            result = await session.execute(
                select(ConversationDBModel)
                .where(*filters)
                .order_by(ConversationDBModel.id.desc())
                .limit(limit + 1)
            )
            db_rows = list(result.scalars().all())

            has_more = len(db_rows) > limit
            page = db_rows[:limit]
            next_cursor = page[-1].id if has_more and page else None

            conversations = [
                ConversationModel(**conversation.model_dump())
                for conversation in page
            ]
            self.logger.info(
                "Conversations listed user_id=%s count=%s has_more=%s",
                user_id,
                len(conversations),
                has_more,
            )
            return (
                conversations,
                str(next_cursor) if next_cursor is not None else None,
                has_more,
            )

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

    async def update(
        self,
        payload: ConversationModel
    ) -> ConversationModel | None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(ConversationDBModel).where(
                    ConversationDBModel.id == payload.id,
                    ConversationDBModel.user_id == payload.user_id,
                )
            )
            db_conversation = result.scalar_one_or_none()
            if db_conversation is None:
                self.logger.info(
                    "Conversation not found for title update id=%s user_id=%s",
                    payload.id,
                    payload.user_id,
                )
                return None

            if payload.title:
                db_conversation.title = payload.title
            if payload.summary:
                db_conversation.summary = payload.summary
            if payload.status:
                db_conversation.status = payload.status
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                self.logger.exception(
                    "Failed to update conversation title id=%s user_id=%s",
                    payload.id,
                    payload.user_id,
                )
                raise
            await session.refresh(db_conversation)
            self.logger.info(
                "Conversation title updated id=%s user_id=%s",
                payload.id,
                payload.user_id,
            )
            return ConversationModel(**db_conversation.model_dump())