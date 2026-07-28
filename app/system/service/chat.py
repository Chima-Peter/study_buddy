from logging import Logger
from typing import Any, AsyncGenerator

from app.core.retriever import RAGRetriever
from app.system.models.conversations import ConversationModel
from app.system.repository.chat import ChatRepository
from app.system.schemas.chat import ConversationResponse

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
        conversation: str,
        embedding: list[float],
        source: list[dict[str, Any]],
        context: str,
    ) -> None:
        record = ConversationModel(
            user_id=user_id,
            query=query,
            conversation=conversation,
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
                    "Conversation saved successfully user_id=%s",
                    user_id,
                )
                return
            except Exception:
                self.logger.exception(
                    "Conversation save failed attempt=%s/%s user_id=%s",
                    attempt,
                    SAVE_MAX_ATTEMPTS,
                    user_id,
                )

        self.logger.error(
            "Conversation save failed after %s attempts user_id=%s",
            SAVE_MAX_ATTEMPTS,
            user_id,
        )

    async def list_by_user(
        self,
        user_id: str,
        *,
        limit: int = 50,
    ) -> list[ConversationResponse]:
        conversations = await self.repository.list_by_user(user_id, limit=limit)
        return [
            ConversationResponse(
                id=item.id,
                user_id=item.user_id,
                query=item.query,
                conversation=item.conversation,
                created_at=item.created_at,
            )
            for item in conversations
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
