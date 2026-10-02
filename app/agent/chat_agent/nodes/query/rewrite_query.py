from logging import Logger
from typing import TYPE_CHECKING

from langchain_google_genai import ChatGoogleGenerativeAI

from app.agent.chat_agent.prompts import rewrite_query_prompt
from app.agent.chat_agent.utils import (
    flatten_section_keys,
    format_history,
    match_section_keys,
)
from app.agent.chat_agent.schema import MemoryRetrieval, RewriteQueryResponse
from app.agent.chat_agent.state import AgentState
from app.utils.llm import is_rate_limit_error

if TYPE_CHECKING:
    from app.system.document.service import DocumentService


class RewriteQueryNode:
    def __init__(
        self,
        logger: Logger,
        model: ChatGoogleGenerativeAI,
        document_service: "DocumentService",
    ):
        self.logger = logger
        self.model = model
        self.document_service = document_service

    async def __call__(self, state: AgentState) -> AgentState:
        retrieve_rag = state.get("retrieve_rag")
        retrieve_memory = state.get("retrieve_memory")
        conversation_id = state.get("conversation_id")
        user_id = state.get("user_id")
        query = state.get("query")

        if not retrieve_rag and not retrieve_memory:
            self.logger.info(
                "Rewrite query node skipped id=%s user_id=%s "
                "reason=no_retrieval",
                conversation_id,
                user_id,
            )
            return {
                "rewritten_query": query,
                "cache_query": None,
                "memory_queries": [],
                "chapter_keys": None,
            }

        document_sections = dict(state.get("document_sections") or {})
        if retrieve_rag:
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
        else:
            section_keys = []

        self.logger.info(
            "Rewrite query node started id=%s user_id=%s "
            "retrieve_rag=%s retrieve_memory=%s section_keys=%s",
            conversation_id,
            user_id,
            retrieve_rag,
            retrieve_memory,
            section_keys,
        )
        recent_history = format_history(state.get("messages"), limit=10)
        prompt = rewrite_query_prompt(
            query=query,
            conversation_summary=state.get("conversation_summary"),
            recent_history=recent_history or "(none)",
            retrieve_rag=retrieve_rag,
            retrieve_memory=retrieve_memory,
            section_keys=section_keys or None,
        )
        try:
            result: RewriteQueryResponse = (
                await self.model.with_structured_output(
                    RewriteQueryResponse
                ).ainvoke(prompt)
            )
        except Exception as e:
            if is_rate_limit_error(e):
                self.logger.warning(
                    "Rewrite query node rate limited id=%s user_id=%s",
                    conversation_id,
                    user_id,
                )
            else:
                self.logger.exception(
                    "Rewrite query node failed id=%s user_id=%s",
                    conversation_id,
                    user_id,
                )
            fallback_queries = (
                [MemoryRetrieval(query=query)] if retrieve_memory else []
            )
            return {
                "rewritten_query": query,
                "cache_query": query if retrieve_rag else None,
                "memory_queries": fallback_queries,
                "chapter_keys": None,
                "document_sections": document_sections,
            }

        rewritten = query
        cache_query = None
        chapter_keys = None
        if retrieve_rag:
            rewritten = (result.rag_query or "").strip() or query
            cache_query = (
                (result.cache_query or "").strip() or rewritten
            )
            chapter_keys = match_section_keys(result.chapters, section_keys)

        memory_queries: list[MemoryRetrieval] = []
        if retrieve_memory:
            memory_queries = [
                MemoryRetrieval(
                    query=item.query.strip(),
                    category=item.category,
                )
                for item in (result.memory_queries or [])
                if item.query and item.query.strip()
            ]
            if not memory_queries:
                memory_queries = [MemoryRetrieval(query=query)]

        self.logger.info(
            "Rewrite query node completed id=%s user_id=%s original=%r "
            "rewritten=%r cache_query=%r chapter_keys=%s memory_queries=%s",
            conversation_id,
            user_id,
            query,
            rewritten,
            cache_query,
            chapter_keys,
            [
                {"query": item.query, "category": item.category}
                for item in memory_queries
            ],
        )
        return {
            "rewritten_query": rewritten,
            "cache_query": cache_query,
            "memory_queries": memory_queries,
            "chapter_keys": chapter_keys,
            "document_sections": document_sections,
        }
