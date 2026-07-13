from typing import List

import numpy as np
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from sentence_transformers import SentenceTransformer


class SentenceTransformerEmbeddings(Embeddings):
    def __init__(self, model: SentenceTransformer):
        self.model = model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts).tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.model.encode(text).tolist()


class EmbeddingManager:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self.model = None
        self._load_model()

    def embed_documents(self, documents: List[Document]) -> np.ndarray:
        if not self.model:
            raise ValueError("Model not loaded")

        texts = [doc.page_content for doc in documents]
        embeddings = self.model.encode(texts)
        print(
            f"Embedded {len(texts)} texts with shape {embeddings.shape} "
            f"and type {type(embeddings)}"
        )
        return embeddings

    def embed_query(self, query: str) -> np.ndarray:
        return self.model.encode(query)

    def _load_model(self):
        try:
            self.model = SentenceTransformer(self.model_name)
        except Exception as e:
            print(f"Error loading model: {e}")
            raise

    def get_langchain_embeddings(self) -> SentenceTransformerEmbeddings:
        return SentenceTransformerEmbeddings(self.model)


if __name__ == "__main__":
    embedding_manager = EmbeddingManager()
    texts = ["Hello, world!", "This is a test", "This is another test"]
    documents = [Document(page_content=text) for text in texts]
    embeddings = embedding_manager.embed_documents(documents)
    print(embeddings)
