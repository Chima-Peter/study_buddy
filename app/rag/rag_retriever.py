"""RAG retriever: embed → Elasticsearch search."""

from logging import Logger

from app.core.elasticsearch import Elasticsearch
from app.core.elasticsearch_schema import FusedResult
from app.core.embedding import EmbeddingManager
from app.core.retriever import Retriever
from app.system.schemas.chat import TOP_K


class RAGRetriever(Retriever):
    def __init__(
        self,
        elasticsearch: Elasticsearch,
        embedding_manager: EmbeddingManager,
        logger: Logger,
    ):
        super().__init__(logger)
        self.elasticsearch = elasticsearch
        self.embedding_manager = embedding_manager

    async def retrieve(
        self,
        user_id: str,
        query: str,
        document_id: str | None = None,
    ) -> list[FusedResult]:
        self.logger.info(
            "Retriever retrieve start user_id=%s top_k=%s query=%r",
            user_id,
            TOP_K,
            query[:120],
        )
        embedding = self.embedding_manager.embed_query(query).tolist()
        self.logger.debug(
            "Retriever embed done user_id=%s dims=%s",
            user_id,
            len(embedding),
        )

        results_lists = await self.elasticsearch.search_hybrid(
            user_id,
            query,
            embedding,
            index="documents",
            min_score=0.5,
            document_id=document_id,
        )
        results = await super().reciprocal_rank_fusion(results_lists, k=TOP_K)

        self.logger.info(
            "Retriever retrieve done user_id=%s hits=%s",
            user_id,
            len(results),
        )
        return results
