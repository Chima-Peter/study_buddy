
from logging import Logger
from pathlib import Path
from typing import IO

from fastapi import HTTPException, status
from langchain_community.document_loaders import CSVLoader, DirectoryLoader, Docx2txtLoader, JSONLoader, PyMuPDFLoader, TextLoader, UnstructuredImageLoader
from langchain_unstructured import UnstructuredLoader
from langchain_core.documents import Document
from langchain_experimental.text_splitter import SemanticChunker

from app.core.embedding import EmbeddingManager, SentenceTransformerEmbeddings
from app.core.vector_store import VectorStore


class IngestPipeline:
    def __init__(
        self,
        logger: Logger,
        embedding_manager: EmbeddingManager = None,
        semantic_embeddings: SentenceTransformerEmbeddings = None,
        vector_store: VectorStore = None,
    ):
        self.embedding_manager = embedding_manager
        self.semantic_embeddings = semantic_embeddings
        self.vector_store = vector_store
        self.logger = logger

    async def initiate_ingest_pipeline(
        self,
        files: dict[str, IO[bytes]],
        user_id: str,
    ):
        chunks = await self.process_files(files, user_id)
        if chunks is None or len(chunks) == 0:
            self.logger.warning("No documents to process")
            return {
                "documents": [],
                "chunks": [],
                "embeddings": [],
            }
        embeddings = self.embedding_manager.embed_documents(chunks)
        if embeddings is None or len(embeddings) == 0:
            self.logger.warning("No embeddings to process")
            return {
                "documents": [],
                "chunks": chunks,
                "embeddings": [],
            }
        self.vector_store.add_documents(chunks, embeddings)

        return

    def load_text_file(self, filename: str = "sample_text_2.txt") -> list:
        loader = TextLoader(str(filename))
        return loader.load()

    def load_pdf_file(self, filename: str = "sample_pdf_1.pdf") -> list:
        loader = PyMuPDFLoader(str(filename),
                               extract_images=True, extract_tables=True)
        return loader.load()

    def load_image_file(self, filename: str = "sample_image_1.png") -> list:
        loader = UnstructuredImageLoader(str(filename))
        return loader.load()

    def load_json_file(self, filename: str = "sample_json_1.json") -> list:
        loader = JSONLoader(str(filename),
                            jq_schema="*.quiz", text_content=False)
        return loader.load()

    def load_word_file(self, filename: str = "sample_word_1.docx") -> list:
        loader = Docx2txtLoader(str(filename))
        return loader.load()

    def load_csv_file(self, filename: str = "sample_csv_1.csv") -> list:
        loader = CSVLoader(str(filename))
        return loader.load()

    def load_directory(self, directory: Path) -> list[Document]:
        dir_loader = DirectoryLoader(
            str(directory),
            glob="**/*.pdf",
            loader_cls=PyMuPDFLoader,
            loader_kwargs={"encoding": "utf-8"},
        )
        return dir_loader.load()

    async def load_file(self, filename: str, file: IO[bytes], hi_res_strategy: str = "fast") -> list[Document]:
        self.logger.info(f"Loading {filename}")
        loader = UnstructuredLoader(
            file=file,
            mode="elements",
            strategy=hi_res_strategy,
            metadata_filename=filename,
            chunking_strategy="by_title",
            max_characters=1500,
            new_after_n_chars=1000,
            combine_text_under_n_chars=500,
        )
        return await loader.aload()

    async def process_files(self, files: dict[str, IO[bytes]], user_id: str) -> list[Document]:
        all_documents: list[Document] = []

        self.logger.info(f"Found {len(files)} file(s)")

        for filename, file in files.items():
            try:
                hi_res_strategy = "hi_res" if filename.endswith(
                    (".png", ".jpg", ".jpeg")) else "fast"

                file.seek(0)
                document = await self.load_file(filename, file, hi_res_strategy)

                for doc in document:
                    doc.metadata["source"] = filename
                    doc.metadata["user_id"] = user_id

                all_documents.extend(document)

                self.logger.info(
                    f"Loaded {len(document)} chunks from {filename}")
            except Exception as e:
                self.logger.exception(f"Error loading {filename}: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Error loading {filename}: {e}")

        self.logger.info(f"Loaded {len(all_documents)} documents")
        return all_documents

    def split_documents(
        self,
        documents: list[Document],
    ) -> list[Document]:
        if not documents:
            self.logger.warning("No documents to split")
            return []

        semantic_chunker = SemanticChunker(embeddings=self.semantic_embeddings)
        chunks = semantic_chunker.split_documents(documents)
        chunks = self._add_chunk_overlap(chunks)
        self.logger.info(
            f"Split {len(documents)} documents into {len(chunks)} chunks")
        return chunks

    def _add_chunk_overlap(self, chunks: list[Document], overlap: int = 50) -> list[Document]:
        if overlap <= 0:
            return chunks
        overlapped_chunks = []
        for i, chunk in enumerate(chunks):
            text = chunk.page_content
            if i > 0:
                prefix = chunks[i - 1].page_content[-overlap:]
                text = f"{prefix} {text}"
            if i < len(chunks) - 1:
                suffix = chunks[i + 1].page_content[:overlap]
                text = f"{text} {suffix}"
            overlapped_chunks.append(
                Document(page_content=text, metadata=chunk.metadata))
        return overlapped_chunks
