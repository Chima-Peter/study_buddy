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
        top_k: int = 5,
        mode: SearchMode = "hybrid",
    ) -> QueryResponseData:
        result = await self.retriever.answer(
            user_id,
            query,
            top_k=top_k,
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
