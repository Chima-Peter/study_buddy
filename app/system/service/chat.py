from logging import Logger

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
    ) -> QueryResponseData:
        self.logger.info(
            "ChatService query start user_id=%s", user_id
        )
        result = await self.retriever.answer(
            user_id,
            query,
            mode="hybrid",
        )
        return QueryResponseData(
            answer=result["answer"],
            sources=[
                SourceChunk(
                    content=s["content"],
                    metadata=s["metadata"],
                    rrf_score=s["rrf_score"],
                )
                for s in result["sources"]
            ],
        )
