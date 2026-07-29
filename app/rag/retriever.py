"""RAG retriever: embed → Elasticsearch search → LLM answer."""

from logging import Logger
from typing import Any, AsyncGenerator, Literal

from langchain_google_genai import ChatGoogleGenerativeAI

from app.agent.state import SUMMARY_EVERY
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
        rag_documents: list[FusedResult],
        conversation_summary: str,
        conversation_history: list[ChatResponse],
    ) -> AsyncGenerator[str, Any]:
        context = ""
        if not rag_documents:
            self.logger.info(
                "No relevant context found for the query. user_id=%s", user_id
            )
        else:
            context = "\n\n".join(r.document.content for r in rag_documents)

        if conversation_summary:
            unsummarized = len(conversation_history) % SUMMARY_EVERY
            recent = conversation_history[-unsummarized:] if unsummarized else []
        else:
            recent = conversation_history[-SUMMARY_EVERY:]

        conversation_history_prompt = "\n\n".join(
            f"User: {chat.query}\nAssistant: {chat.response}"
            for chat in recent
        )

        query_prompt = (
            "You are a helpful study assistant.\n\n"
            "Use the provided context as the primary source of truth when "
            "answering questions about the user's documents or study materials.\n\n"
            "Rules:\n"
            "1. If the answer can be found in the provided context, answer using "
            "only that context.\n"
            "2. If the question is about the uploaded documents but the context "
            "does not contain enough information, say so clearly and ask the user "
            "to upload the relevant document(s) or provide additional context. Do "
            "not guess or fabricate information.\n"
            "3. If the question is a general knowledge question that is unrelated "
            'to the uploaded documents (e.g., "What is the capital of France?"), '
            "answer normally using your general knowledge.\n"
            "4. If it is unclear whether the question refers to the uploaded "
            "documents or general knowledge, answer from your general knowledge, "
            "but explicitly mention that you are answering from your general knowledge.\n"
            "5. When answering from the provided context, cite or reference the "
            "relevant sections if they are available.\n\n"
            f"External Context:\n{context}\n\n"
            f"Conversation Last 5 Messages:\n{conversation_history_prompt}\n\n"
            f"Conversation Summary:\n{conversation_summary}\n\n"
            f"Question: {query}\n"
            "Answer:"
        )

        async for chunk in self.model.astream(query_prompt):
            text = chunk.text
            if not text:
                continue
            yield text
