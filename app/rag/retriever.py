"""RAG retriever: embed → Elasticsearch search."""

from logging import Logger
from typing import Literal

from app.core.elasticsearch import Elasticsearch, FusedResult
from app.core.embedding import EmbeddingManager
from app.system.schemas.chat import TOP_K

SearchMode = Literal["hybrid", "vector", "bm25"]


class RAGRetriever:
    def __init__(
        self,
        elasticsearch: Elasticsearch,
        embedding_manager: EmbeddingManager,
        logger: Logger,
    ):
        self.elasticsearch = elasticsearch
        self.embedding_manager = embedding_manager
        self.logger = logger

    async def retrieve(
        self,
        user_id: str,
        query: str,
        *,
        mode: SearchMode = "hybrid",
    ) -> list[FusedResult]:
        self.logger.info(
            "Retriever retrieve start user_id=%s mode=%s top_k=%s query=%r",
            user_id,
            mode,
            TOP_K,
            query[:120],
        )
        embedding = self.embedding_manager.embed_query(query).tolist()
        self.logger.info(
            "Retriever embed done user_id=%s dims=%s",
            user_id,
            len(embedding),
        )

        if mode == "bm25":
            docs = await self.elasticsearch.search_bm25(user_id, query, size=TOP_K)
            results = [FusedResult(document=doc, score=0.0) for doc in docs]
        elif mode == "vector":
            docs = await self.elasticsearch.search_vector(
                user_id, embedding, k=TOP_K
            )
            results = [FusedResult(document=doc, score=0.0) for doc in docs]
        else:
            results = await self.elasticsearch.search_hybrid(
                user_id, query, embedding, k=TOP_K
            )

        self.logger.info(
            "Retriever retrieve done user_id=%s mode=%s hits=%s",
            user_id,
            mode,
            len(results),
        )
        return results
