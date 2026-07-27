from logging import Logger
from typing import AsyncGenerator

from app.core.retriever import RAGRetriever
from app.system.schemas.chat import QueryResponseData, SourceChunk


class ChatService:
    def __init__(self, retriever: RAGRetriever, logger: Logger):
        self.retriever = retriever
        self.logger = logger

    async def query(
        self,
        user_id: str,
        query: str,
    ) -> None:
        self.logger.info(
            "Initiating streaming response for user_id=%s", user_id
        )
        async for response in self.retriever.answer(
            user_id,
            query,
            mode="hybrid",
        ):
            self.logger.info(
                "Streaming response chunk for user_id=%s", user_id
            )
            yield response
        self.logger.info(
            "Streaming response completed for user_id=%s", user_id
        )