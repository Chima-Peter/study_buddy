from logging import Logger

from app.core.retriever import RAGRetriever, SearchMode
from app.system.schemas.chat import QueryResponseData, SourceChunk


class ChatService:
    def __init__(self, retriever: RAGRetriever, logger: Logger):
        self.retriever = retriever
        self.logger = logger

    async def query(
        self,
        user_id: str,
        query: str,
        *,
        mode: SearchMode = "hybrid",
    ) -> QueryResponseData:
        self.logger.info(
            "ChatService query start user_id=%s mode=%s", user_id, mode
        )
        result = await self.retriever.answer(
            user_id,
            query,
            mode=mode,
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
