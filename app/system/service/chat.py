from functools import partial
from logging import Logger
from typing import Any, AsyncGenerator

from app.core.redis import RedisClient
from app.core.retriever import RAGRetriever
from app.system.models.chat import ChatModel
from app.system.repository.chat import ChatRepository
from app.system.schemas.chat import ChatResponse

SAVE_MAX_ATTEMPTS = 3


class ChatService:
    def __init__(
        self,
        retriever: RAGRetriever,
        repository: ChatRepository,
        logger: Logger,
        redis: RedisClient
    ):
        self.retriever = retriever
        self.repository = repository
        self.logger = logger
        self.redis = redis

    async def save(
        self,
        *,
        user_id: str,
        conversation_id: str,
        query: str,
        chat: str,
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
        for attempt in range(1, SAVE_MAX_ATTEMPTS + 1):
            try:
                await self.repository.create(record, user_id)
                self.logger.info(
                    "Chat saved successfully user_id=%s",
                    user_id,
                )
                return
            except Exception:
                self.logger.exception(
                    "Chat save failed attempt=%s/%s user_id=%s",
                    attempt,
                    SAVE_MAX_ATTEMPTS,
                    user_id,
                )

        self.logger.error(
            "Chat save failed after %s attempts user_id=%s",
            SAVE_MAX_ATTEMPTS,
            user_id,
        )

    async def query(
        self,
        user_id: str,
        conversation_id: str,
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
            on_complete=partial(
                self.save,
                conversation_id=conversation_id,
            ),
        ):
            self.logger.info(
                "Streaming response chunk for user_id=%s", user_id
            )
            yield response
        self.logger.info(
            "Streaming response completed for user_id=%s", user_id
        )
