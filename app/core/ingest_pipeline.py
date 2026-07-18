import tempfile
from logging import Logger
from pathlib import Path

from langchain_community.document_loaders import (
    UnstructuredMarkdownLoader,
    Docx2txtLoader,
    PyMuPDFLoader,
    TextLoader,
)
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownTextSplitter, RecursiveCharacterTextSplitter, RecursiveJsonSplitter
from langchain_unstructured import UnstructuredLoader

from app.core.document_parsers import parse_csv
from app.core.embedding import EmbeddingManager, SentenceTransformerEmbeddings
from app.core.ocr_cleanup import clean_ocr_documents
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

    def _ids(self, payload: IngestDocumentRequest) -> tuple[str, str, str]:
        return payload.file_name, payload.user_id, payload.document_id

    async def initiate_ingest_pipeline(
        self,
        payload: IngestDocumentRequest,
    ):
        file_name, user_id, document_id = self._ids(payload)
        suffix = Path(payload.file_name).suffix or Path(payload.path).suffix
        with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
            await self.supabase.download_file_to(payload.path, tmp)
            tmp.flush()
            tmp.seek(0)
            chunks = self.process_file(payload, tmp.name)
            if chunks is None or len(chunks) == 0:
                self.logger.warning(
                    "No documents to process file=%s user_id=%s document_id=%s",
                    file_name,
                    user_id,
                    document_id,
                )
                return {
                    "documents": [],
                    "chunks": [],
                    "embeddings": [],
                }
            embeddings = self.embedding_manager.embed_documents(chunks)
            if embeddings is None or len(embeddings) == 0:
                self.logger.warning(
                    "No embeddings to process file=%s user_id=%s document_id=%s",
                    file_name,
                    user_id,
                    document_id,
                )
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
        payload: IngestDocumentRequest,
    ) -> list[Document]:
        file_name, user_id, document_id = self._ids(payload)
        documents = loader.load()
        chunks = self.split_documents(documents, payload=payload)
        self.logger.info(
            "Loaded file=%s user_id=%s document_id=%s loader=%s chunks=%s",
            file_name,
            user_id,
            document_id,
            loader_name,
            len(chunks),
        )
        return chunks

    def load_text_file(
        self, payload: IngestDocumentRequest, file_path: str
    ) -> list[Document]:
        return self._load_and_split(
            TextLoader(str(file_path)),
            loader_name="TextLoader",
            payload=payload,
        )

    def load_markdown_file(
        self, payload: IngestDocumentRequest, file_path: str
    ) -> list[Document]:
        markdown_loader = UnstructuredMarkdownLoader(
            str(file_path), mode="elements")
        documents = markdown_loader.load()
        chunks = MarkdownTextSplitter(
            chunk_size=1000, chunk_overlap=200).split_documents(documents)
        self.logger.info(
            "Loaded and split markdown file=%s user_id=%s document_id=%s loader=%s chunks=%s",
            payload.file_name,
            payload.user_id,
            payload.document_id,
            "UnstructuredMarkdownLoader",
            len(chunks),
        )
        return chunks

    def load_pdf_file(
        self, payload: IngestDocumentRequest, file_path: str
    ) -> list[Document]:
        try:
            return self._load_and_split(
                PyMuPDFLoader(
                    str(file_path),
                    mode="page",
                    extract_images=True,
                ),
                loader_name="PyMuPDFLoader",
                payload=payload,
            )
        except Exception as e:
            self.logger.warning(
                "PyMuPDFLoader failed for file=%s, falling back to UnstructuredLoader: %s",
                payload.file_name,
                e,
            )
            return self.load_file(payload, file_path, "fast")

    def _pdf_needs_hi_res(self, file_path: str) -> bool:
        import fitz

        drawing_threshold = 30

        doc = fitz.open(file_path)
        try:
            for page in doc:
                for img in page.get_images(full=True):
                    xref = img[0]
                    pix = fitz.Pixmap(doc, xref)
                    if pix.width > 500 and pix.height > 500:
                        return True
                if len(page.get_drawings()) >= drawing_threshold:
                    return True
            return False
        finally:
            doc.close()

    def load_json_file(
        self, payload: IngestDocumentRequest, file_path: str
    ) -> list[Document]:
        import json as json_mod

        file_name, user_id, document_id = self._ids(payload)
        with open(file_path, encoding="utf-8") as f:
            data = json_mod.load(f)

        splitter = RecursiveJsonSplitter(max_chunk_size=1000)
        chunks = splitter.create_documents(
            texts=[data] if isinstance(data, dict) else data,
            convert_lists=True,
        )
        self.logger.info(
            "Loaded file=%s user_id=%s document_id=%s loader=%s chunks=%s",
            file_name,
            user_id,
            document_id,
            "RecursiveJsonSplitter",
            len(chunks),
        )
        return chunks

    def load_word_file(
        self, payload: IngestDocumentRequest, file_path: str
    ) -> list[Document]:
        return self._load_and_split(
            Docx2txtLoader(str(file_path)),
            loader_name="Docx2txtLoader",
            payload=payload,
        )

    def load_csv_file(
        self, payload: IngestDocumentRequest, file_path: str
    ) -> list[Document]:
        file_name, user_id, document_id = self._ids(payload)
        documents = parse_csv(file_path)
        chunks = self.split_documents(documents, payload=payload)
        self.logger.info(
            "Loaded file=%s user_id=%s document_id=%s loader=%s chunks=%s",
            file_name,
            user_id,
            document_id,
            "parse_csv",
            len(chunks),
        )
        return chunks

    def load_file(
        self,
        payload: IngestDocumentRequest,
        file_path: str,
        hi_res_strategy: str = "fast",
    ) -> list[Document]:
        file_name, user_id, document_id = self._ids(payload)
        loader = UnstructuredLoader(
            file_path=file_path,
            mode="elements",
            strategy=hi_res_strategy,
            metadata_filename=file_name,
            chunking_strategy="by_title",
            max_characters=1500,
            new_after_n_chars=1000,
            combine_text_under_n_chars=500,
        )
        documents = loader.load()
        self.logger.info(
            "Loaded file=%s user_id=%s document_id=%s loader=%s chunks=%s",
            file_name,
            user_id,
            document_id,
            "UnstructuredLoader",
            len(documents),
        )
        return documents

    def process_file(
        self,
        payload: IngestDocumentRequest,
        file_path: str,
    ) -> list[Document]:
        file_name, user_id, document_id = self._ids(payload)
        try:
            self.logger.info(
                "Processing file=%s user_id=%s document_id=%s",
                file_name,
                user_id,
                document_id,
            )
            suffix = Path(file_path).suffix.lower()
            used_unstructured = False

            match suffix:
                case ".pdf":
                    if self._pdf_needs_hi_res(file_path):
                        self.logger.info(
                            "PDF needs hi_res file=%s user_id=%s document_id=%s",
                            file_name,
                            user_id,
                            document_id,
                        )
                        used_unstructured = True
                        documents = self.load_file(
                            payload, file_path, "hi_res")
                    else:
                        self.logger.info(
                            "PDF text-only path file=%s user_id=%s document_id=%s",
                            file_name,
                            user_id,
                            document_id,
                        )
                        documents = self.load_pdf_file(payload, file_path)
                case ".docx":
                    documents = self.load_word_file(payload, file_path)
                case ".txt":
                    documents = self.load_text_file(payload, file_path)
                case ".md" | ".markdown":
                    documents = self.load_markdown_file(payload, file_path)
                case ".json":
                    documents = self.load_json_file(payload, file_path)
                case ".csv":
                    documents = self.load_csv_file(payload, file_path)
                case s if s in IMAGE_SUFFIXES:
                    used_unstructured = True
                    documents = self.load_file(payload, file_path, "hi_res")
                case _:
                    used_unstructured = True
                    documents = self.load_file(payload, file_path, "fast")

            if not documents and used_unstructured:
                self.logger.warning(
                    "No document found file=%s user_id=%s document_id=%s; trying hi_res",
                    file_name,
                    user_id,
                    document_id,
                )
                documents = self.load_file(payload, file_path, "hi_res")
            elif not documents:
                self.logger.warning(
                    "No document found file=%s user_id=%s document_id=%s",
                    file_name,
                    user_id,
                    document_id,
                )
                return []

            if used_unstructured and documents:
                pre_clean = len(documents)
                documents = clean_ocr_documents(documents)
                self.logger.info(
                    "OCR cleanup file=%s user_id=%s document_id=%s before=%s after=%s",
                    file_name,
                    user_id,
                    document_id,
                    pre_clean,
                    len(documents),
                )

            for i, doc in enumerate(documents):
                doc.metadata["source"] = payload.file_name
                doc.metadata["page"] = i
                doc.metadata["category"] = payload.category
                doc.metadata["name"] = payload.name
                doc.metadata["user_id"] = payload.user_id
                doc.metadata["document_id"] = payload.document_id
                doc.metadata["chunk_id"] = f"{payload.document_id}_{i}"

            self.logger.info(
                "Ready file=%s user_id=%s document_id=%s chunks=%s",
                file_name,
                user_id,
                document_id,
                len(documents),
            )
            return documents
        except NonRetryableIngestError:
            raise
        except Exception as e:
            self.logger.exception(
                "Error loading file=%s user_id=%s document_id=%s: %s",
                file_name,
                user_id,
                document_id,
                e,
            )
            raise NonRetryableIngestError(
                f"File could not be parsed ({payload.file_name}): {e}"
            ) from e

    def split_documents(
        self,
        documents: list[Document],
        payload: IngestDocumentRequest | None = None,
    ) -> list[Document]:
        if not documents:
            if payload is not None:
                file_name, user_id, document_id = self._ids(payload)
                self.logger.warning(
                    "No documents to split file=%s user_id=%s document_id=%s",
                    file_name,
                    user_id,
                    document_id,
                )
            else:
                self.logger.warning("No documents to split")
            return []
        if self.semantic_embeddings is None:
            raise NonRetryableIngestError(
                "embeddings could not be generated: semantic embeddings are not configured"
            )

        return RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            separators=["\n\n", "\n", " ", ""],
        ).split_documents(documents)

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
