
import sys
from pathlib import Path
from typing import Any
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv
load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from app.core.vector_store import VectorStore
from app.core.embedding import EmbeddingManager


class RAGRetriever:
    def __init__(
        self,
        vector_store: VectorStore,
        embedding_manager: EmbeddingManager,
    ):
        self.vector_store = vector_store
        self.embedding_manager = embedding_manager
        self.model = ChatGoogleGenerativeAI(
            model="gemini-3.1-flash-lite",
            temperature=0.2,
            max_tokens=1024,
            max_retries=3,
        )

    def initiate_retriever_pipeline(
        self,
        query: str,
        top_k: int = 2,
        score_threshold: float = 0.0,
    ) -> list[dict[str, Any]]:
        results = self._retrieve(
            query=query,
            top_k=top_k,
            score_threshold=score_threshold,
        )
        context = "\n\n".join([result["document"]
                              for result in results]) if results else ""
        if not context:
            return "No relevant context found for the query"

        prompt = """
          You are a helpful assistant. Use the following context to answer the question:
          Context: {context}

          Question: {query}
          Answer:
        """
        response = self.model.invoke([prompt.format(
            context=context,
            query=query
        )])
        print(f"Response: {response.content}")
        return response.content

    def _retrieve(
        self,
        query: str,
        top_k: int = 10,
        score_threshold: float = 0.0,
    ) -> list[dict[str, Any]]:
        try:
            results = self.vector_store.collection.query(
                query_texts=[query],
                n_results=top_k,
            )
            retrieved_docs: list[dict[str, Any]] = []

            if results["documents"] and results["documents"][0]:
                documents = results["documents"][0]
                metadatas = results["metadatas"][0]
                distances = results["distances"][0]
                ids = results["ids"][0]

                for i, (document, metadata, distance, doc_id) in enumerate(
                    zip(documents, metadatas, distances, ids)
                ):
                    similarity_score = 1 - distance
                    if similarity_score >= score_threshold:
                        retrieved_docs.append(
                            {
                                "id": doc_id,
                                "rank": i + 1,
                                "document": document,
                                "similarity_score": similarity_score,
                                "metadata": metadata,
                            }
                        )

            retrieved_docs.sort(
                key=lambda x: x["similarity_score"], reverse=True)
            print(
                f"Retrieved {len(retrieved_docs)} documents "
                f"with score >= {score_threshold}"
            )
            return retrieved_docs

        except Exception as e:
            print(f"Error retrieving documents: {e}")
            return []


def print_results(results: list[dict[str, Any]], limit: int = 3) -> None:
    for result in results[:limit]:
        source = result["metadata"].get("source", "unknown")
        page = result["metadata"].get("page", "?")
        score = result["similarity_score"]
        preview = result["document"].replace("\n", " ")
        print(f"\n[{result['rank']}] score={score:.3f} | page {page} | {source}")
        print(f"    {preview}...")


if __name__ == "__main__":
    vector_store = VectorStore()
    embedding_manager = EmbeddingManager()
    retriever = RAGRetriever(vector_store, embedding_manager)
    results = retriever.initiate_retriever_pipeline(
        "Write a summary about multi agent systems", top_k=10, score_threshold=0.5
    )
