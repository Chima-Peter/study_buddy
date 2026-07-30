"""RAG retriever: embed → Elasticsearch search → LLM answer."""

from logging import Logger
from typing import Any, AsyncGenerator, Literal

from langchain_google_genai import ChatGoogleGenerativeAI

from app.agent.prompts import chat_response_prompt
from app.agent.schema import SUMMARY_EVERY
from app.core.elasticsearch import Elasticsearch, FusedResult
from app.core.embedding import EmbeddingManager
from app.system.schemas.chat import TOP_K, ChatResponse

SearchMode = Literal["hybrid", "vector", "bm25"]


class RAGRetriever:
    def __init__(
        self,
        elasticsearch: Elasticsearch,
        embedding_manager: EmbeddingManager,
        logger: Logger,
        *,
        model: ChatGoogleGenerativeAI,
    ):
        self.elasticsearch = elasticsearch
        self.embedding_manager = embedding_manager
        self.logger = logger
        self.model = model

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

    async def generate_chat_response(
        self,
        user_id: str,
        query: str,
        retrieve_history: bool,
        rag_documents: list[FusedResult],
        conversation_summary: str,
        conversation_history: list[ChatResponse],
    ) -> AsyncGenerator[str, Any]:
        context = ""
        if not rag_documents:
            self.logger.info(
                "No relevant context found for the query. user_id=%s", user_id
            )
            context = ""
        else:
            context = "\n\n".join(r.document.content for r in rag_documents)

        if retrieve_history:
            if conversation_summary:
                unsummarized = len(conversation_history) % SUMMARY_EVERY
                recent = conversation_history[-unsummarized:] if unsummarized else []
            else:
                recent = conversation_history[-SUMMARY_EVERY:]

            history_text = "\n\n".join(
                f"User: {chat.query}\nAssistant: {chat.response}"
                for chat in recent
            )
        else:
            history_text = ""

        prompt = chat_response_prompt(
            context=context,
            conversation_history_prompt=history_text,
            conversation_summary=conversation_summary,
            query=query,
        )

        async for chunk in self.model.astream(prompt):
            text = chunk.text
            if not text:
                continue
            yield text
