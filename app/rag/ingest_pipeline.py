import tempfile
from logging import Logger
from pathlib import Path
from typing import cast

from langchain_community.document_loaders import (
    Docx2txtLoader,
    PyMuPDFLoader,
    TextLoader,
    UnstructuredEPubLoader,
    UnstructuredHTMLLoader,
    UnstructuredMarkdownLoader,
    UnstructuredODTLoader,
    UnstructuredRTFLoader,
    UnstructuredWordDocumentLoader,
)
from langchain_core.documents import Document
from langchain_text_splitters import (
    MarkdownTextSplitter,
    RecursiveCharacterTextSplitter,
    RecursiveJsonSplitter,
)
from langchain_unstructured import UnstructuredLoader

from app.core.elasticsearch import Elasticsearch
from app.core.elasticsearch_schema import DocumentMetadata, IndexedRecord
from app.core.embedding import EmbeddingManager
from app.core.supabase import Supabase
from app.rag.document_parsers import parse_csv
from app.rag.ocr_cleanup import clean_ocr_documents
from app.rag.schema import ALLOWED_FILE_TYPES
from app.rag.unstructured_api import normalize_unstructured_base_url
from app.system.document.schema import IngestDocumentRequest
from app.utils.errors.rabbitmq import NonRetryableIngestError


class IngestPipeline:
    def __init__(
        self,
        logger: Logger,
        embedding_manager: EmbeddingManager = None,
        supabase: Supabase = None,
        elasticsearch: Elasticsearch = None,
        unstructured_api_url: str = "http://localhost:8001",
        unstructured_api_key: str = "",
    ):
        self.embedding_manager = embedding_manager
        self.logger = logger
        self.supabase = supabase
        self.elasticsearch = elasticsearch
        self.unstructured_api_url = normalize_unstructured_base_url(unstructured_api_url)
        self.unstructured_api_key = unstructured_api_key or ""

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

            es_payload = [
                IndexedRecord(
                    content=chunk.page_content,
                    metadata=cast(DocumentMetadata, chunk.metadata),
                    embedding=embedding.tolist()
                    if hasattr(embedding, "tolist")
                    else list(embedding),
                )
                for chunk, embedding in zip(chunks, embeddings)
            ]
            es_success, _es_failed = await self.elasticsearch.bulk_index(
                es_payload, index="documents"
            )
            if es_success == 0:
                raise NonRetryableIngestError(
                    "Document could not be indexed into search"
                )
            elif _es_failed > 0:
                raise NonRetryableIngestError(
                    f"Document could not be indexed into search: {_es_failed} failed"
                )
            else:
                self.logger.info(
                    "Document indexed into search success=%s failed=%s",
                    es_success,
                    _es_failed,
                )
            return {
                "success": True,
                "message": f"{len(chunks)} chunks processed"
            }

    def load_text_file(
        self, payload: IngestDocumentRequest, file_path: str
    ) -> list[Document]:
        try:
            self.logger.info(
                "Loading text file=%s user_id=%s document_id=%s",
                payload.file_name,
                payload.user_id,
                payload.document_id,
            )
            return self._load_and_split(
                TextLoader(str(file_path)),
                loader_name="TextLoader",
                payload=payload,
            )
        except Exception as e:
            self.logger.warning(
                "TextLoader failed for file=%s, falling back to UnstructuredLoader: %s",
                payload.file_name,
                e,
            )
            return self.load_file(payload, file_path, "fast")

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
        suffix = Path(file_path).suffix.lower()
        if suffix == ".doc":
            return self._load_and_split(
                UnstructuredWordDocumentLoader(
                    str(file_path),
                    mode="elements",
                    strategy="fast",
                ),
                loader_name="UnstructuredWordDocumentLoader",
                payload=payload,
            )
        return self._load_and_split(
            Docx2txtLoader(str(file_path)),
            loader_name="Docx2txtLoader",
            payload=payload,
        )

    def load_html_file(
        self, payload: IngestDocumentRequest, file_path: str
    ) -> list[Document]:
        return self._load_and_split(
            UnstructuredHTMLLoader(
                str(file_path),
                mode="elements",
                strategy="fast",
            ),
            loader_name="UnstructuredHTMLLoader",
            payload=payload,
        )

    def load_epub_file(
        self, payload: IngestDocumentRequest, file_path: str
    ) -> list[Document]:
        return self._load_and_split(
            UnstructuredEPubLoader(
                str(file_path),
                mode="elements",
                strategy="fast",
            ),
            loader_name="UnstructuredEPubLoader",
            payload=payload,
        )

    def load_rtf_file(
        self, payload: IngestDocumentRequest, file_path: str
    ) -> list[Document]:
        return self._load_and_split(
            UnstructuredRTFLoader(
                str(file_path),
                mode="elements",
                strategy="fast",
            ),
            loader_name="UnstructuredRTFLoader",
            payload=payload,
        )

    def load_odt_file(
        self, payload: IngestDocumentRequest, file_path: str
    ) -> list[Document]:
        return self._load_and_split(
            UnstructuredODTLoader(
                str(file_path),
                mode="elements",
                strategy="fast",
            ),
            loader_name="UnstructuredODTLoader",
            payload=payload,
        )

    def load_csv_file(
        self, payload: IngestDocumentRequest, file_path: str
    ) -> list[Document]:
        file_name, user_id, document_id = self._ids(payload)
        documents = parse_csv(file_path)
        chunks = self._split_documents(documents, payload=payload)
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
        """Partition via the self-hosted Unstructured API (docker compose)."""
        file_name, user_id, document_id = self._ids(payload)
        loader = UnstructuredLoader(
            file_path=file_path,
            partition_via_api=True,
            url=self.unstructured_api_url,
            api_key=self.unstructured_api_key,
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
            "Loaded file=%s user_id=%s document_id=%s loader=%s api=%s chunks=%s",
            file_name,
            user_id,
            document_id,
            "UnstructuredLoader",
            self.unstructured_api_url,
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
            supported = {f".{ext}" for ext in ALLOWED_FILE_TYPES} | {".markdown"}
            if suffix not in supported:
                raise NonRetryableIngestError(
                    f"Unsupported file type: {suffix}. "
                    f"Should be one of: {', '.join(ALLOWED_FILE_TYPES)}"
                )

            strategy = "fast"
            if suffix == ".pdf" and self._pdf_needs_hi_res(file_path):
                strategy = "hi_res"
                self.logger.info(
                    "PDF needs hi_res file=%s user_id=%s document_id=%s",
                    file_name,
                    user_id,
                    document_id,
                )

            documents = self.load_file(payload, file_path, strategy)
            if not documents and strategy != "hi_res" and suffix == ".pdf":
                self.logger.warning(
                    "No document found file=%s; retrying with hi_res via Unstructured API",
                    file_name,
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

            if strategy == "hi_res" and documents:
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
                doc.metadata["id"] = f"{payload.document_id}_{i}"

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

    
    def _ids(self, payload: IngestDocumentRequest) -> tuple[str, str, str]:
        return payload.file_name, payload.user_id, payload.document_id

    def _load_and_split(
        self,
        loader,
        *,
        loader_name: str,
        payload: IngestDocumentRequest,
    ) -> list[Document]:
        file_name, user_id, document_id = self._ids(payload)
        documents = loader.load()
        chunks = self._split_documents(documents, payload=payload)
        self.logger.info(
            "Loaded file=%s user_id=%s document_id=%s loader=%s chunks=%s",
            file_name,
            user_id,
            document_id,
            loader_name,
            len(chunks),
        )
        return chunks

    def _split_documents(
        self,
        documents: list[Document],
        *,
        payload: IngestDocumentRequest,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ) -> list[Document]:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        chunks = splitter.split_documents(documents)
        self.logger.info(
            "Split documents file=%s user_id=%s document_id=%s chunks=%s",
            payload.file_name,
            payload.user_id,
            payload.document_id,
            len(chunks),
        )
        return self._add_chunk_overlap(chunks, payload=payload)

    def _add_chunk_overlap(
        self, chunks: list[Document], *, payload: IngestDocumentRequest, overlap: int = 50
    ) -> list[Document]:
        if overlap <= 0:
            return chunks
            
        self.logger.info(
            "Adding chunk overlap file=%s user_id=%s document_id=%s overlap=%s",
            payload.file_name,
            payload.user_id,
            payload.document_id,
            overlap,
        )

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

        self.logger.info(
            "Added chunk overlap file=%s user_id=%s document_id=%s chunks=%s",
            payload.file_name,
            payload.user_id,
            payload.document_id,
            len(overlapped_chunks),
        )
        return overlapped_chunks
