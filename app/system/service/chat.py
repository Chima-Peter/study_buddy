from logging import Logger
from typing import Any, AsyncGenerator

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
    ):
        self.retriever = retriever
        self.repository = repository
        self.logger = logger

    async def save(
        self,
        *,
        user_id: str,
        query: str,
        chat: str,
        embedding: list[float],
        source: list[dict[str, Any]],
        context: str,
    ) -> None:
        record = ChatModel(
            user_id=user_id,
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
                await self.repository.create(record)
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

    async def list_by_user(
        self,
        user_id: str,
        *,
        limit: int = 50,
    ) -> list[ChatResponse]:
        chats = await self.repository.list_by_user(user_id, limit=limit)
        return [
            ChatResponse(
                id=item.id,
                user_id=item.user_id,
                query=item.query,
                chat=item.chat,
                created_at=item.created_at,
            )
            for item in chats
        ]

    async def query(
        self,
        user_id: str,
        query: str,
    ) -> AsyncGenerator[str, None]:
        self.logger.info(
            "Initiating streaming response for user_id=%s", user_id
        )
        async for response in self.retriever.answer(
            user_id,
            query,
            mode="hybrid",
            on_complete=self.save,
        ):
            self.logger.info(
                "Streaming response chunk for user_id=%s", user_id
            )
            yield response
        self.logger.info(
            "Streaming response completed for user_id=%s", user_id
        )
