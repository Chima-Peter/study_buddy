"""RAG retriever: embed → Elasticsearch search → deduplicate → LLM answer."""

from collections.abc import Awaitable, Callable
from logging import Logger
from typing import Any, AsyncGenerator, Literal

from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.elasticsearch import Elasticsearch, FusedResult
from app.core.embedding import EmbeddingManager
from app.system.schemas.chat import TOP_K

SearchMode = Literal["hybrid", "vector", "bm25"]
OnComplete = Callable[..., Awaitable[None]]


def _deduplicate_by_document(results: list[FusedResult]) -> list[FusedResult]:
    """Keep only the highest-scoring chunk per chunk_id."""
    seen: dict[str, FusedResult] = {}
    for r in results:
        doc_id = r.document.metadata.get("chunk_id")
        if doc_id is None:
            continue
        if doc_id not in seen or r.score > seen[doc_id].score:
            seen[doc_id] = r
    return list(seen.values())


class RAGRetriever:
    def __init__(
        self,
        elasticsearch: Elasticsearch,
        embedding_manager: EmbeddingManager,
        logger: Logger,
        *,
        google_api_key: str | None = None,
        model_name: str = "gemini-3.1-flash-lite",
    ):
        self.elasticsearch = elasticsearch
        self.embedding_manager = embedding_manager
        self.logger = logger
        self.model = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0.2,
            max_tokens=1024,
            max_retries=3,
            google_api_key=google_api_key,
        )

    async def retrieve(
        self,
        user_id: str,
        query: str,
        *,
        mode: SearchMode = "hybrid",
    ) -> tuple[list[FusedResult], list[float]]:
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
        return results, embedding

    async def answer(
        self,
        user_id: str,
        query: str,
        *,
        mode: SearchMode = "hybrid",
        on_complete: OnComplete | None = None,
    ) -> AsyncGenerator[str, Any]:
        self.logger.info(
            "Retriever pipeline start user_id=%s mode=%s top_k=%s",
            user_id,
            mode,
            TOP_K,
        )
        results, embedding = await self.retrieve(user_id, query, mode=mode)
        deduped: list[FusedResult] = []
        context = ""
        if not results:
            self.logger.info(
                "No relevant context found for the query. user_id=%s", user_id
            )
        else:
            deduped = _deduplicate_by_document(results)
            self.logger.info(
                "Retriever dedupe user_id=%s before=%s after=%s",
                user_id,
                len(results),
                len(deduped),
            )
            context = "\n\n".join(r.document.content for r in deduped)
            self.logger.info(
                "Retriever LLM invoke user_id=%s context_chars=%s sources=%s",
                user_id,
                len(context),
                len(deduped),
            )

        prompt = (
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
            f"Context:\n{context}\n\n"
            f"Question: {query}\n"
            "Answer:"
        )

        answer = ""
        async for chunk in self.model.astream(prompt):
            # Gemini often returns content as list blocks; .text normalizes to str.
            text = chunk.text
            if not text:
                continue
            yield text
            answer += text

        sources = [
            {
                "content": r.document.content,
                "metadata": r.document.metadata,
                "rrf_score": r.score,
            }
            for r in deduped
        ]
        self.logger.info(
            "Retriever pipeline done user_id=%s answer_chars=%s sources=%s",
            user_id,
            len(answer),
            len(sources),
        )
        if on_complete is not None:
            await on_complete(
                user_id=user_id,
                query=query,
                conversation=answer,
                embedding=embedding,
                source=sources,
                context=context,
            )
