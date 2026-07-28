import asyncio
from logging import Logger
from typing import Any, AsyncGenerator

from app.core.redis import RedisClient
from app.core.retriever import RAGRetriever
from app.system.models.chat import ChatModel
from app.system.repository.chat import ChatRepository
from app.system.repository.conversation import ConversationRepository
from app.system.schemas.chat import ChatResponse

SAVE_MAX_ATTEMPTS = 3


class ChatService:
    def __init__(
        self,
        retriever: RAGRetriever,
        repository: ChatRepository,
        conversation_repository: ConversationRepository,
        logger: Logger,
        redis: RedisClient,
    ):
        self.retriever = retriever
        self.repository = repository
        self.conversation_repository = conversation_repository
        self.logger = logger
        self.redis = redis

    async def save(
        self,
        *,
        user_id: str,
        conversation_id: str,
        query: str,
        chat: str,
        first_message: bool,
        title: str | None,
        embedding: list[float],
        source: list[dict[str, Any]],
        context: str,
    ) -> None:
        record = ChatModel(
            conversation_id=conversation_id,
            query=query,
            chat=chat,
            audit={
                "embedding": embedding,
                "source": source,
                "context": context,
            },
        )

        async def save_chat() -> None:
            for attempt in range(0, SAVE_MAX_ATTEMPTS + 1):
                try:
                    if attempt > SAVE_MAX_ATTEMPTS:
                        self.logger.error(
                            "Chat save failed after %s attempts user_id=%s",
                            SAVE_MAX_ATTEMPTS,
                            user_id,
                        )
                        return
                    await self.repository.create(record, user_id)
                    self.logger.info(
                        "Chat saved successfully user_id=%s",
                        user_id,
                    )
                    return
                except Exception:
                    self.logger.exception(
                        "Chat save failed user_id=%s attempt=%s/%s",
                        attempt,
                        user_id,
                        SAVE_MAX_ATTEMPTS,
                    )

        async def update_conversation_title() -> None:
            if not first_message or not title:
                return

            for attempt in range(0, SAVE_MAX_ATTEMPTS + 1):
                try:
                    if attempt > SAVE_MAX_ATTEMPTS:
                        self.logger.error(
                            "Conversation title update failed after %s attempts id=%s user_id=%s",
                            SAVE_MAX_ATTEMPTS,
                            conversation_id,
                            user_id,
                        )
                        return
                    conversation = await self.conversation_repository.update_title(
                        conversation_id,
                        user_id,
                        title,
                    )
                    if conversation is None:
                        self.logger.warning(
                            "Conversation title update skipped id=%s user_id=%s",
                            conversation_id,
                            user_id,
                        )
                    else:
                        self.logger.info(
                            "Conversation title updated from first message "
                            "id=%s user_id=%s",
                            conversation_id,
                            user_id,
                        )
                    return
                except Exception:
                    self.logger.exception(
                        "Conversation title update failed id=%s user_id=%s, attempt=%s/%s",
                        conversation_id,
                        user_id,
                        attempt,
                        SAVE_MAX_ATTEMPTS,
                    )

        async with asyncio.TaskGroup() as tg:
            tg.create_task(save_chat())
            tg.create_task(update_conversation_title())

    async def query(
        self,
        user_id: str,
        conversation_id: str,
        first_message: bool,
        query: str,
    ) -> AsyncGenerator[str, None]:
        conversation_owner_id = await self.redis.get(conversation_id)
        if conversation_owner_id:
            if conversation_owner_id != user_id:
                yield "Conversation not found"
                return
        else:
            if not await self.repository.conversation_belongs_to_user(
                conversation_id,
                user_id,
            ):
                yield "Conversation not found"
                return

            await self.redis.set(conversation_id, user_id)

        self.logger.info(
            "Initiating streaming response for user_id=%s", user_id
        )
        async for response in self.retriever.answer(
            user_id,
            query,
            mode="hybrid",
            first_message=first_message,
            conversation_id=conversation_id,
            on_complete=self.save,
        ):
            self.logger.info(
                "Streaming response chunk for user_id=%s", user_id
            )
            yield response
        self.logger.info(
            "Streaming response completed for user_id=%s", user_id
        )
