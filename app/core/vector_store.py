from logging import Logger
import uuid
from pathlib import Path
from typing import List

import chromadb
import numpy as np
from langchain_core.documents import Document

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VECTOR_STORE_DIR = PROJECT_ROOT / "vector_store"


class VectorStore:
    def __init__(
        self,
        logger: Logger,
        collection_name: str = "pdf_store",
        persist_directory: Path = VECTOR_STORE_DIR,
    ):
        self.collection_name = collection_name
        self.persist_directory = persist_directory
        self.logger = logger
        self.client = None
        self.collection = None
        self._initialize_store()

    def _initialize_store(self):
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(
            path=str(self.persist_directory))
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={
                "hnsw:space": "cosine",
                "description": "Vector store for PDF documents",
            },
        )
        self.logger.info(
            f"Vector store initialized with collection: {self.collection_name}")

    def add_documents(self, documents: List[Document], embeddings: np.ndarray):
        if len(documents) != len(embeddings):
            raise ValueError(
                "Number of documents and embeddings must be the same")
        if not self.collection:
            raise ValueError("Collection not initialized")

        ids = []
        documents_text = []
        embeddings_list = []
        metadatas = []

        for i, (doc, embedding) in enumerate(zip(documents, embeddings)):
            doc_id = f"doc_{uuid.uuid4().hex[:8]}_{i}"
            ids.append(doc_id)

            metadata = dict(doc.metadata)
            metadata["doc_index"] = i
            metadata["content_length"] = len(doc.page_content)
            metadatas.append(metadata)

            documents_text.append(doc.page_content)
            embeddings_list.append(embedding.tolist())

        self.collection.add(
            ids=ids,
            documents=documents_text,
            embeddings=embeddings_list,
            metadatas=metadatas,
        )
        self.logger.info(f"Added {len(documents)} documents to vector store")
