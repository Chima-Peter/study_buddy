import tempfile
from logging import Logger
from pathlib import Path

from fastapi import HTTPException, status
from langchain_community.document_loaders import CSVLoader, DirectoryLoader, Docx2txtLoader, JSONLoader, PyMuPDFLoader, TextLoader, UnstructuredImageLoader
from langchain_unstructured import UnstructuredLoader
from langchain_core.documents import Document
from langchain_experimental.text_splitter import SemanticChunker

from app.core.embedding import EmbeddingManager, SentenceTransformerEmbeddings
from app.core.supabase import Supabase
from app.core.vector_store import VectorStore
from app.system.schemas.document import IngestDocumentRequest


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
            chunks = await self.process_file(payload, tmp)
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

    async def load_file(self, filename: str, file_path: str, hi_res_strategy: str = "fast") -> list[Document]:
        self.logger.info(f"Loading {filename}")
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
        return await loader.aload()

    async def process_file(
        self,
        payload: IngestDocumentRequest,
        file_path: str,
    ) -> list[Document]:
        all_documents: list[Document] = []

        try:
            self.logger.info(f"Processing {payload.file_name}")
            hi_res_strategy = "hi_res" if payload.file_name.endswith(
                (".png", ".jpg", ".jpeg")) else "fast"

            document = await self.load_file(payload.file_name, file_path, hi_res_strategy)

            if document is None or len(document) == 0:
                self.logger.warning(
                    f"No document found for {payload.file_name}, trying hi_res strategy")
                document = await self.load_file(payload.file_name, file_path, "hi_res")

            for i, doc in enumerate(document):
                # fetch document details from database
                doc.metadata["source"] = payload.file_name
                doc.metadata["chunk_index"] = i
                doc.metadata["category"] = payload.category
                doc.metadata["name"] = payload.name
                doc.metadata["user_id"] = payload.user_id
                doc.metadata["document_id"] = payload.document_id

            all_documents.extend(document)

            self.logger.info(
                f"Loaded {len(document)} chunks from {payload.file_name}")
        except Exception as e:
            self.logger.exception(f"Error loading {payload.file_name}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error loading {payload.file_name}: {e}")

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
