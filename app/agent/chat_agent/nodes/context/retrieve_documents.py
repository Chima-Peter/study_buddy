from logging import Logger

from app.agent.chat_agent.state import AgentState
from app.agent.chat_agent.utils import cache_hit_to_fused
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
        if not state.get("retrieve_rag"):
            self.logger.info(
                "Retrieve documents node skipped user_id=%s",
                state.get("user_id"),
            )
            return {
                "rag_documents": [],
                "semantic_cache_hit": False,
                "query_embedding": None,
            }

        document_id = state.get("document_id")
        rag_query = state.get("rewritten_query")
        cache_query = (state.get("cache_query") or "").strip() or rag_query
        self.logger.info(
            "Retrieve documents node started user_id=%s chapter_keys=%s",
            state.get("user_id"),
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
                    state.get("user_id"),
                    document_id,
                    cached.distance,
                    len(cached.chunk_ids),
                )
                return {
                    "rag_documents": [cache_hit_to_fused(cached)],
                    "semantic_cache_hit": True,
                    "query_embedding": None,
                }

        results = await self.retriever.retrieve(
            user_id=state.get("user_id"),
            query=rag_query,
            document_ids=[document_id] if document_id else None,
            chapter_keys=state.get("chapter_keys"),
        )

        self.logger.info(
            "Retrieve documents node completed user_id=%s count=%s",
            state.get("user_id"),
            len(results),
        )
        return {
            "rag_documents": results,
            "semantic_cache_hit": False,
            "query_embedding": cache_embedding_list,
        }
