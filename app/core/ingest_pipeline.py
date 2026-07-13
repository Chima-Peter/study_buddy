
import sys
from pathlib import Path

from langchain_community.document_loaders import DirectoryLoader, PyMuPDFLoader, TextLoader
from langchain_core.documents import Document
from langchain_experimental.text_splitter import SemanticChunker
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv
load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from app.core.vector_store import VectorStore
from app.core.embedding import EmbeddingManager, SentenceTransformerEmbeddings


DATA_DIR = PROJECT_ROOT / "data" / "langchain"


class IngestPipeline:
    def __init__(
        self,
        embedding_manager: EmbeddingManager,
        semantic_embeddings: SentenceTransformerEmbeddings,
        vector_store: VectorStore = None,
        data_dir: Path = DATA_DIR,
    ):
        self.data_dir = data_dir
        self.embedding_manager = embedding_manager
        self.semantic_embeddings = semantic_embeddings
        self.vector_store = vector_store

    def initiate_ingest_pipeline(self) -> None:
        documents = self.process_pdf_files()
        chunks = self.split_documents(documents)
        embeddings = self.embedding_manager.embed_documents(chunks)
        self.vector_store.add_documents(chunks, embeddings)

    def load_text_file(self, filename: str = "sample_text_2.txt") -> list:
        loader = TextLoader(str(self.data_dir / filename))
        return loader.load()

    def load_pdf_file(self, filename: str = "sample_pdf_1.pdf") -> list:
        loader = PyMuPDFLoader(str(self.data_dir / filename))
        return loader.load()

    def load_directory(self, directory: Path = DATA_DIR) -> list[Document]:
        dir_loader = DirectoryLoader(
            str(directory),
            glob="**/*.txt",
            loader_cls=TextLoader,
            loader_kwargs={"encoding": "utf-8"},
        )
        return dir_loader.load()

    def process_pdf_files(self) -> list[Document]:
        all_documents: list[Document] = []
        pdf_files = list(DATA_DIR.glob("*.pdf"))

        print(f"Found {len(pdf_files)} PDF file(s)")

        for pdf_file in pdf_files:
            try:
                document = self.load_pdf_file(pdf_file.name)

                for doc in document:
                    doc.metadata["source"] = str(pdf_file)
                    doc.metadata["file_type"] = "pdf"
                all_documents.extend(document)
            except Exception as e:
                print(f"Error loading {pdf_file}: {e}")
                continue

        print(f"Loaded {len(all_documents)} documents")
        return all_documents

    def split_documents(
        self,
        documents: list[Document],
    ) -> list[Document]:
        if not documents:
            print("No documents to split")
            return []

        semantic_chunker = SemanticChunker(embeddings=self.semantic_embeddings)
        chunks = semantic_chunker.split_documents(documents)
        chunks = self._add_chunk_overlap(chunks)
        print(f"Split {len(documents)} documents into {len(chunks)} chunks")
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


if __name__ == "__main__":
    embedding_manager = EmbeddingManager()
    vector_store = VectorStore()
    langchain_embeddings = embedding_manager.get_langchain_embeddings()
    ingest_pipeline = IngestPipeline(
      embedding_manager=embedding_manager,
      semantic_embeddings=langchain_embeddings,
      vector_store=vector_store,
    )
    ingest_pipeline.initiate_ingest_pipeline()
