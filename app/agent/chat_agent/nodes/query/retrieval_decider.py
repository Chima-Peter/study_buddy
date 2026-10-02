from logging import Logger
from typing import TYPE_CHECKING

from langchain_google_genai import ChatGoogleGenerativeAI

from app.agent.chat_agent.utils import (
    flatten_section_keys,
    format_history,
    match_section_keys,
)
from app.agent.chat_agent.prompts import retrieval_decider_prompt
from app.agent.chat_agent.schema import (
    NON_ACADEMIC_FALLBACK,
    SUMMARY_EVERY,
    DeciderResponse,
    MemoryRetrieval,
)
from app.agent.chat_agent.state import AgentState
from app.utils.llm import is_rate_limit_error

if TYPE_CHECKING:
    from app.system.document.service import DocumentService


class RetrievalDeciderNode:
    def __init__(
        self,
        logger: Logger,
        model: ChatGoogleGenerativeAI,
        document_service: "DocumentService",
    ):
        self.logger = logger
        self.model = model.with_structured_output(DeciderResponse)
        self.document_service = document_service

    async def __call__(self, state: AgentState) -> AgentState:
        messages = state.get("messages") or []
        is_first_message = len(messages) <= 1
        conversation_id = state.get("conversation_id")
        user_id = state.get("user_id")
        query = state.get("query")
        self.logger.info(
            "Retrieval decider started id=%s user_id=%s first_message=%s",
            conversation_id,
            user_id,
            is_first_message,
        )

        if state.get("retry_count", 1) > 3:
            self.logger.warning(
                "Retrieval decider failed id=%s user_id=%s retry_count=%s",
                conversation_id,
                user_id,
                state.get("retry_count"),
            )
            return {
                "retrieve_rag": False,
                "retrieve_conversation_history": False,
                "retrieve_memory": False,
                "is_academic_discussion": False,
                "rag_documents": [],
                "rewritten_query": query,
                "cache_query": None,
                "memory_queries": [],
                "chapter_keys": None,
            }

        document_sections = dict(state.get("document_sections") or {})
        document_id = state.get("document_id")
        if document_id and document_id not in document_sections:
            try:
                fetched = await self.document_service.get_sections_by_document(
                    [document_id],
                    user_id,
                )
                document_sections.update(fetched)
            except Exception:
                self.logger.exception(
                    "Failed loading section keys id=%s user_id=%s",
                    conversation_id,
                    user_id,
                )
        section_keys = flatten_section_keys(document_id, document_sections)

        context = format_history(messages, limit=SUMMARY_EVERY)
        summary = state.get("conversation_summary") or ""
        prompt = retrieval_decider_prompt(
            query,
            context,
            summary,
            section_keys=section_keys or None,
        )

        decision: DeciderResponse | None = None
        try:
            decision = await self.model.ainvoke(prompt)
            result = decision.decision
            retrieve_memory = decision.retrieve_memory
            is_academic_discussion = decision.is_academic_discussion
            response = decision.response
        except Exception as e:
            if is_rate_limit_error(e):
                self.logger.warning(
                    "Retrieval decider rate limited id=%s user_id=%s",
                    conversation_id,
                    user_id,
                )
            else:
                self.logger.exception(
                    "Retrieval decider failed id=%s user_id=%s",
                    conversation_id,
                    user_id,
                )
            result = "both" if not is_first_message else "rag"
            retrieve_memory = False
            is_academic_discussion = True
            response = None

        if not is_academic_discussion:
            reply = (response or "").strip() or NON_ACADEMIC_FALLBACK
            self.logger.info(
                "Retrieval decider ended discussion early id=%s user_id=%s",
                conversation_id,
                user_id,
            )
            return {
                "retrieve_rag": False,
                "retrieve_conversation_history": False,
                "retrieve_memory": False,
                "is_academic_discussion": False,
                "response": reply,
                "rag_documents": [],
                "rewritten_query": query,
                "cache_query": None,
                "memory_queries": [],
                "chapter_keys": None,
                "document_sections": document_sections,
            }

        mapping = {
            "rag": (True, False),
            "history": (False, True),
            "both": (True, True),
            "none": (False, False),
        }
        retrieve_rag, retrieve_history = mapping.get(result, (False, False))
        if is_first_message:
            retrieve_history = False

        if not document_id:
            retrieve_rag = False

        rewritten = query
        cache_query = None
        chapter_keys = None
        memory_queries: list[MemoryRetrieval] = []

        if decision is not None:
            if retrieve_rag:
                rewritten = (decision.rag_query or "").strip() or query
                cache_query = (
                    (decision.cache_query or "").strip() or rewritten
                )
                chapter_keys = match_section_keys(
                    decision.chapters,
                    section_keys,
                )
            if retrieve_memory:
                memory_queries = [
                    MemoryRetrieval(
                        query=item.query.strip(),
                        category=item.category,
                    )
                    for item in (decision.memory_queries or [])
                    if item.query and item.query.strip()
                ]
                if not memory_queries:
                    memory_queries = [MemoryRetrieval(query=query)]
        else:
            if retrieve_rag:
                cache_query = query
            if retrieve_memory:
                memory_queries = [MemoryRetrieval(query=query)]

        self.logger.info(
            "Retrieval decider completed id=%s user_id=%s decision=%s "
            "retrieve_rag=%s retrieve_history=%s retrieve_memory=%s "
            "is_academic_discussion=%s rewritten=%r cache_query=%r "
            "chapter_keys=%s memory_queries=%s",
            conversation_id,
            user_id,
            result,
            retrieve_rag,
            retrieve_history,
            retrieve_memory,
            is_academic_discussion,
            rewritten,
            cache_query,
            chapter_keys,
            [
                {"query": item.query, "category": item.category}
                for item in memory_queries
            ],
        )

        return {
            "retrieve_rag": retrieve_rag,
            "retrieve_conversation_history": retrieve_history,
            "retrieve_memory": retrieve_memory,
            "is_academic_discussion": is_academic_discussion,
            "rewritten_query": rewritten,
            "cache_query": cache_query,
            "memory_queries": memory_queries,
            "chapter_keys": chapter_keys,
            "document_sections": document_sections,
        }
