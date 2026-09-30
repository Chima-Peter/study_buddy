from logging import Logger

from app.agent.chat_agent.state import AgentState
from app.core.elasticsearch_schema import FusedResult, IndexedRecord
from app.core.embedding import EmbeddingManager
from app.core.semantic_cache import CacheHit, SemanticCache
from app.rag.rag_retriever import RAGRetriever


class RetrieveDocumentsNode:
    def __init__(
        self,
        retriever: RAGRetriever,
        semantic_cache: SemanticCache,
        embedding_manager: EmbeddingManager,
        logger: Logger,
    ):
        self.retriever = retriever
        self.semantic_cache = semantic_cache
        self.embedding_manager = embedding_manager
        self.logger = logger

    async def __call__(self, state: AgentState) -> AgentState:
        if not state["retrieve_rag"]:
            self.logger.info(
                "Retrieve documents node skipped user_id=%s",
                state["user_id"],
            )
            return {
                "rag_documents": [],
                "semantic_cache_hit": False,
                "query_embedding": None,
            }

        document_id = state.get("document_id")
        rag_query = state["rewritten_query"]
        cache_query = (state.get("cache_query") or "").strip() or rag_query
        self.logger.info(
            "Retrieve documents node started user_id=%s chapter_keys=%s",
            state["user_id"],
            state.get("chapter_keys"),
        )

        cache_embedding = self.embedding_manager.embed_query(cache_query)
        cache_embedding_list = cache_embedding.tolist()

        if document_id and cache_query:
            cached = await self.semantic_cache.lookup(
                cache_embedding, document_id=document_id
            )
            if isinstance(cached, CacheHit):
                self.logger.info(
                    "Semantic cache hit user_id=%s document_id=%s "
                    "distance=%.3f chunks=%s",
                    state["user_id"],
                    document_id,
                    cached.distance,
                    len(cached.chunk_ids),
                )
                return {
                    "rag_documents": [_hit_to_fused(cached)],
                    "semantic_cache_hit": True,
                    "query_embedding": None,
                }

        results = await self.retriever.retrieve(
            user_id=state["user_id"],
            query=rag_query,
            document_ids=[document_id] if document_id else None,
            chapter_keys=state.get("chapter_keys"),
        )

        self.logger.info(
            "Retrieve documents node completed user_id=%s count=%s",
            state["user_id"],
            len(results),
        )
        return {
            "rag_documents": results,
            "semantic_cache_hit": False,
            "query_embedding": cache_embedding_list,
        }


def _hit_to_fused(hit: CacheHit) -> FusedResult:
    return FusedResult(
        document=IndexedRecord(
            content=hit.context,
            metadata={
                "document_id": hit.document_id,
                "id": ",".join(hit.chunk_ids),
            },
            embedding=[],
        ),
        score=max(0.0, 1.0 - hit.distance),
    )
