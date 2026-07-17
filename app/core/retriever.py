from logging import Logger
from typing import Any, Literal

from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.elasticsearch import Elasticsearch, IndexedDocuments
from app.core.embedding import EmbeddingManager

SearchMode = Literal["hybrid", "vector", "bm25"]


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
        top_k: int = 10,
        mode: SearchMode = "hybrid",
    ) -> list[IndexedDocuments]:
        embedding = self.embedding_manager.embed_query(query).tolist()

        if mode == "bm25":
            docs = await self.elasticsearch.search_bm25(user_id, query, size=top_k)
        elif mode == "vector":
            docs = await self.elasticsearch.search_vector(
                user_id, embedding, k=top_k
            )
        else:
            docs = await self.elasticsearch.search_hybrid(
                user_id, query, embedding, k=top_k
            )

        self.logger.info(
            "Retrieved %s chunks user_id=%s mode=%s top_k=%s",
            len(docs),
            user_id,
            mode,
            top_k,
        )
        return docs

    async def answer(
        self,
        user_id: str,
        query: str,
        *,
        top_k: int = 5,
        mode: SearchMode = "hybrid",
    ) -> dict[str, Any]:
        documents = await self.retrieve(
            user_id, query, top_k=top_k, mode=mode
        )
        if not documents:
            return {
                "answer": "No relevant context found for the query.",
                "sources": [],
            }

        context = "\n\n".join(doc.content for doc in documents)
        prompt = (
            "You are a helpful study assistant. Use only the following context "
            "to answer the question. If the context is insufficient, say so by notifying the user to upload relevant documents.\n\n"
            f"Context:\n{context}\n\n"
            f"Question: {query}\n"
            "Answer:"
        )
        response = await self.model.ainvoke([prompt])
        answer = response.content if isinstance(response.content, str) else str(
            response.content
        )

        sources = [
            {
                "name": doc.metadata["name"],
                "category": doc.metadata["category"],
                "age": doc.metadata["chunk_id"],
            }
            for doc in documents
        ]
        return {"answer": answer, "sources": sources}
