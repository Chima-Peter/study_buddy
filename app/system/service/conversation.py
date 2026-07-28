from logging import Logger
from typing import Any

from app.system.models.conversations import ConversationModel
from app.system.repository.conversation import ConversationRepository

SAVE_MAX_ATTEMPTS = 3


class ConversationService:
    def __init__(
        self,
        repository: ConversationRepository,
        logger: Logger,
    ):
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
        conversation_saved = False
        for attempt in range(1, SAVE_MAX_ATTEMPTS + 1):
            try:
                await self.repository.create(record)
                conversation_saved = True
                return
            except Exception:
                self.logger.exception(
                    "Conversation save failed attempt=%s/%s user_id=%s",
                    attempt,
                    SAVE_MAX_ATTEMPTS,
                    user_id,
                )

        if not conversation_saved:
            self.logger.error(
                "Conversation save failed after %s attempts user_id=%s",
                SAVE_MAX_ATTEMPTS,
                user_id,
            )
            raise Exception("Conversation save failed after %s attempts", SAVE_MAX_ATTEMPTS)
        self.logger.info(
            "Conversation saved successfully user_id=%s",
            user_id,
        )

    async def list(
        self,
        user_id: str,
        *,
        limit: int = 50,
    ) -> list[ConversationModel]:
        return await self.repository.list_by_user(user_id, limit=limit)
