from logging import Logger
from typing import TYPE_CHECKING

from app.agent.chat_agent.state import AgentState

if TYPE_CHECKING:
    from app.system.service.document import DocumentService


class CleanupNode:
    """Clears transient state and caches important information for later turns."""

    def __init__(
        self,
        logger: Logger,
        document_service: "DocumentService",
    ):
        self.logger = logger
        self.document_service = document_service

    async def __call__(self, state: AgentState) -> AgentState:
        self.logger.info(
            "Cleanup node started id=%s user_id=%s",
            state["conversation_id"],
            state["user_id"],
        )

        document_sections = dict(state.get("document_sections") or {})
        document_ids = state.get("document_ids") or []
        missing_ids = [
            document_id
            for document_id in document_ids
            if document_id not in document_sections
        ]
        if missing_ids:
            try:
                fetched = await self.document_service.get_sections_by_document(
                    missing_ids,
                    state["user_id"],
                )
                document_sections.update(fetched)
            except Exception:
                self.logger.exception(
                    "Cleanup failed caching section keys id=%s user_id=%s "
                    "document_ids=%s",
                    state["conversation_id"],
                    state["user_id"],
                    missing_ids,
                )

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
            "first_message": False,
            "rag_documents": [],
            "retrieve_rag": False,
            "retrieve_conversation_history": False,
            "retrieve_memory": False,
            "memory_query": None,
            "memories": [],
            "response": "",
            "messages": [],
            "chapter_keys": None,
            "document_sections": document_sections,
        }
