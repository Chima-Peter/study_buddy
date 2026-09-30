from logging import Logger
from typing import TYPE_CHECKING

import numpy as np

from app.agent.chat_agent.state import AgentState
from app.agent.chat_agent.utils import format_rag_context

from app.core.semantic_cache import SemanticCache

if TYPE_CHECKING:
    from app.system.document.service import DocumentService


class CleanupNode:
    """Clears transient state and caches important information for later turns."""

    def __init__(
        self,
        logger: Logger,
        document_service: "DocumentService",
        semantic_cache: SemanticCache,
    ):
        self.logger = logger
        self.document_service = document_service
        self.semantic_cache = semantic_cache

    async def __call__(self, state: AgentState) -> AgentState:
        self.logger.info(
            "Cleanup node started id=%s user_id=%s",
            state["conversation_id"],
            state["user_id"],
        )

        document_sections = dict(state.get("document_sections") or {})
        document_id = state.get("document_id")
        if document_id and document_id not in document_sections:
            try:
                fetched = await self.document_service.get_sections_by_document(
                    [document_id],
                    state["user_id"],
                )
                document_sections.update(fetched)
            except Exception:
                self.logger.exception(
                    "Cleanup failed caching section keys id=%s user_id=%s "
                    "document_id=%s",
                    state["conversation_id"],
                    state["user_id"],
                    document_id,
                )

        await self._cache_rag_chunks(state)

        self.logger.info(
            "Cleanup node completed id=%s user_id=%s "
            "document_sections=%s",
            state["conversation_id"],
            state["user_id"],
            {doc_id: keys for doc_id, keys in document_sections.items()},
        )
        return {
            "query": "",
            "rewritten_query": "",
            "cache_query": None,
            "rag_documents": [],
            "tavily_results": [],
            "retrieve_rag": False,
            "retrieve_conversation_history": False,
            "retrieve_memory": False,
            "is_academic_discussion": True,
            "memory_query": None,
            "memories": [],
            "response": "",
            "chapter_keys": None,
            "document_sections": document_sections,
            "semantic_cache_hit": False,
            "query_embedding": None,
        }

    async def _cache_rag_chunks(self, state: AgentState) -> None:
        if state.get("semantic_cache_hit"):
            return

        document_id = state.get("document_id")
        query = state.get("cache_query")
        rag_documents = state.get("rag_documents") or []
        embedding = state.get("query_embedding")
        if not document_id or not query or not rag_documents or not embedding:
            return

        try:
            context = format_rag_context(rag_documents)
            chunk_ids = [
                str(cid)
                for r in rag_documents
                if (cid := r.document.metadata.get("id"))
            ]
            await self.semantic_cache.put(
                query=query,
                embedding=np.asarray(embedding, dtype=np.float32),
                context=context,
                document_id=document_id,
                chunk_ids=chunk_ids,
            )
            self.logger.info(
                "Semantic cache put id=%s user_id=%s document_id=%s "
                "chunks=%s",
                state["conversation_id"],
                state["user_id"],
                document_id,
                len(chunk_ids),
            )
        except Exception:
            self.logger.exception(
                "Semantic cache put failed id=%s user_id=%s document_id=%s",
                state["conversation_id"],
                state["user_id"],
                document_id,
            )
