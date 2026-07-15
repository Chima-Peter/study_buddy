import tempfile
from logging import Logger
from pathlib import Path

from langchain_community.document_loaders import (
    DirectoryLoader,
    Docx2txtLoader,
    PyMuPDFLoader,
    TextLoader,
    UnstructuredImageLoader,
)
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_unstructured import UnstructuredLoader

from app.core.document_parsers import parse_csv, parse_json
from app.core.embedding import EmbeddingManager, SentenceTransformerEmbeddings
from app.core.supabase import Supabase
from app.core.vector_store import VectorStore
from app.system.schemas.document import IngestDocumentRequest
from app.utils.errors.rabbitmq import NonRetryableIngestError

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


class IngestPipeline:
    def __init__(
        self,
        logger: Logger,
        embedding_manager: EmbeddingManager = None,
        supabase: Supabase = None,
        semantic_embeddings: SentenceTransformerEmbeddings = None,
        vector_store: VectorStore = None,
    ):
        self.embedding_manager = embedding_manager
        self.semantic_embeddings = semantic_embeddings
        self.vector_store = vector_store
        self.logger = logger
        self.supabase = supabase

    async def initiate_ingest_pipeline(
        self,
        payload: IngestDocumentRequest,
    ):
        suffix = Path(payload.file_name).suffix or Path(payload.path).suffix
        with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
            await self.supabase.download_file_to(payload.path, tmp)
            tmp.flush()
            tmp.seek(0)
            chunks = self.process_file(payload, tmp.name)
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
            return {
                "documents": chunks,
                "chunks": chunks,
                "embeddings": embeddings,
            }

    def _load_and_split(
        self,
        loader,
        *,
        loader_name: str,
        file_path: str,
        **extra_context,
    ) -> list[Document]:
        filename = Path(file_path).name
        documents = loader.load()
        self.logger.info(
            "Loaded file=%s loader=%s documents=%s",
            filename,
            loader_name,
            len(documents),
        )
        chunks = self.split_documents(documents)
        self.logger.info(
            "Split file=%s loader=%s chunks=%s",
            filename,
            loader_name,
            len(chunks),
        )
        return chunks

    def load_text_file(self, file_path: str) -> list[Document]:
        return self._load_and_split(
            TextLoader(str(file_path)),
            loader_name="TextLoader",
            file_path=file_path,
        )

    def load_pdf_file(self, file_path: str) -> list[Document]:
        return self._load_and_split(
            PyMuPDFLoader(
                str(file_path),
                extract_images=True,
                extract_tables=True,
            ),
            loader_name="PyMuPDFLoader",
            file_path=file_path,
            extract_images=True,
            extract_tables=True,
        )

    def load_image_file(self, file_path: str) -> list[Document]:
        return self._load_and_split(
            UnstructuredImageLoader(str(file_path)),
            loader_name="UnstructuredImageLoader",
            file_path=file_path,
        )

    def load_json_file(self, file_path: str) -> list[Document]:
        documents = parse_json(file_path)
        chunks = self.split_documents(documents)
        self.logger.info(
            "Loaded and splitfile=%s loader=%s chunks=%s",
            Path(file_path).name,
            "parse_json",
            len(chunks),
        )
        return chunks

    def load_word_file(self, file_path: str) -> list[Document]:
        return self._load_and_split(
            Docx2txtLoader(str(file_path)),
            loader_name="Docx2txtLoader",
            file_path=file_path,
        )

    def load_csv_file(self, file_path: str) -> list[Document]:
        documents = parse_csv(file_path)
        chunks = self.split_documents(documents)
        self.logger.info(
            "Loaded and split file=%s loader=%s chunks=%s",
            Path(file_path).name,
            "parse_csv",
            len(chunks),
        )
        return chunks


    def load_file(
        self,
        filename: str,
        file_path: str,
        hi_res_strategy: str = "fast",
    ) -> list[Document]:
        context = {
            "loader": "UnstructuredLoader",
            "file_path": file_path,
            "strategy": hi_res_strategy,
        }
        loader = UnstructuredLoader(
            file_path=file_path,
            mode="elements",
            strategy=hi_res_strategy,
            metadata_filename=filename,
            chunking_strategy="by_title",
            max_characters=1500,
            new_after_n_chars=1000,
            combine_text_under_n_chars=500,
        )
        documents = loader.load()
        self.logger.info(
            "Loaded and split file=%s loader=%s chunks=%s",
            len(documents),
            context,
        )
        return documents

    def process_file(
        self,
        payload: IngestDocumentRequest,
        file_path: str,
    ) -> list[Document]:
        try:
            self.logger.info(f"Processing {payload.file_name}")
            suffix = Path(file_path).suffix.lower()
            used_unstructured = False

            match suffix:
                case ".pdf":
                    used_unstructured = True
                    documents = self.load_file(
                        payload.file_name, file_path, "fast")
                case ".docx":
                    documents = self.load_word_file(file_path)
                case ".txt":
                    documents = self.load_text_file(file_path)
                case ".json":
                    documents = self.load_json_file(file_path)
                case ".csv":
                    documents = self.load_csv_file(file_path)
                case _:
                    used_unstructured = True
                    documents = self.load_file(
                        payload.file_name, file_path, "fast"
                    )

            if not documents and used_unstructured:
                self.logger.warning(
                    "No document found for %s, trying hi_res strategy",
                    payload.file_name,
                )
                documents = self.load_file(
                    payload.file_name, file_path, "hi_res"
                )
            elif not documents:
                self.logger.warning(
                    "No document found for %s",
                    payload.file_name,
                )
                return []

            for i, doc in enumerate(documents):
                doc.metadata["source"] = payload.file_name
                doc.metadata["chunk_index"] = i
                doc.metadata["category"] = payload.category
                doc.metadata["name"] = payload.name
                doc.metadata["user_id"] = payload.user_id
                doc.metadata["document_id"] = payload.document_id

            return documents
        except NonRetryableIngestError:
            raise
        except Exception as e:
            self.logger.exception(f"Error loading {payload.file_name}: {e}")
            raise NonRetryableIngestError(
                f"Error loading {payload.file_name}: {e}"
            ) from e

    def split_documents(
        self,
        documents: list[Document],
        # suffix: str
    ) -> list[Document]:
        if not documents:
            self.logger.warning("No documents to split")
            return []
        if self.semantic_embeddings is None:
            raise NonRetryableIngestError(
                "semantic_embeddings is not configured"
            )

        chunks = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            separators=["\n\n", "\n", " ", ""]
        ).split_documents(documents)

        return chunks

    def _add_chunk_overlap(
        self, chunks: list[Document], overlap: int = 50
    ) -> list[Document]:
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
                Document(page_content=text, metadata=chunk.metadata)
            )
        return overlapped_chunks
