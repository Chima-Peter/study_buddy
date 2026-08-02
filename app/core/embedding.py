from logging import Logger
from typing import List

import numpy as np
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from sentence_transformers import SentenceTransformer

class EmbeddingManager:
    def __init__(self, logger: Logger, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self.logger = logger
        self._model = None
        self._load_model()

    def embed_documents(self, documents: List[Document]) -> np.ndarray:
        if not self.model:
            raise ValueError("Model not loaded")

        texts = [doc.page_content for doc in documents]
        embeddings = self._model.encode(texts, show_progress_bar=False)
        self.logger.debug(
            "Embedded %s texts shape=%s",
            len(texts),
            embeddings.shape,
        )
        return embeddings

    def embed_query(self, query: str) -> np.ndarray:
        return self._model.encode(query, show_progress_bar=False)

    def _load_model(self):
        try:
            self._model = SentenceTransformer(self.model_name)
            self.logger.info(f"Embedding model: {self.model_name} ready")
        except Exception as e:
            self.logger.exception("Error loading model")
            raise e

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            raise ValueError("Model not loaded")
        return self._model
