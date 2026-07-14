from logging import Logger

from app.core.ingest_pipeline import IngestPipeline
from app.core.vector_store import VectorStore
from app.system.models.documents import DocumentModel
from app.system.repository.document import DocumentRepository
from app.system.schemas.document import (
    CreateDocumentRequest,
    DocumentResponse,
    IngestDocumentRequest,
    PatchDocumentRequest,
    UpdateDocumentRequest,
)
from app.utils.errors import DocumentCreateError


class DocumentService:
    def __init__(
        self,
        repository: DocumentRepository,
        logger: Logger,
        ingest_pipeline: IngestPipeline,
        vector_store: VectorStore,
    ):
        self.repository = repository
        self.logger = logger
        self.vector_store = vector_store
        self.ingest_pipeline = ingest_pipeline

    async def create_documents(
        self,
        requests: list[CreateDocumentRequest],
        user_id: str,
    ) -> list[DocumentResponse]:
        documents = [
            DocumentModel.from_request(request, user_id) for request in requests
        ]
        results = await self.repository.create(documents)

        ingest_payload = [
            IngestDocumentRequest(
                file_name=request.file_name,
                category=result.category,
                name=result.name,
                file=request.file,
                user_id=user_id,
                document_id=result.id,
            )
            for request, result in zip(requests, results)
        ]

        try:
            await self.ingest_pipeline.initiate_ingest_pipeline(ingest_payload)
        except Exception:
            self.logger.exception(
                "Ingest failed; rolling back documents ids=%s",
                [result.id for result in results],
            )
            for result in results:
                await self.repository.delete(result.id)
            raise DocumentCreateError("Failed to ingest documents")

        return [result.to_response() for result in results]

    async def get_document_by_id(
        self,
        document_id: str,
        user_id: str,
    ) -> DocumentResponse:
        document = await self._get_owned_document(document_id, user_id)
        return document.to_response()

    async def get_documents_by_user_id(
        self,
        user_id: str,
    ) -> list[DocumentResponse]:
        documents = await self.repository.get_by_user_id(user_id)
        return [document.to_response() for document in documents]

    async def update_document(
        self,
        document_id: str,
        request: UpdateDocumentRequest,
        user_id: str,
    ) -> DocumentResponse:
        document = await self._get_owned_document(document_id, user_id)
        document.update_from_request(request)
        result = await self.repository.update(document)
        return result.to_response()

    async def patch_document(
        self,
        document_id: str,
        request: PatchDocumentRequest,
        user_id: str,
    ) -> DocumentResponse:
        document = await self._get_owned_document(document_id, user_id)
        document.patch_from_request(request)
        result = await self.repository.update(document)
        return result.to_response()

    async def delete_document(self, document_id: str, user_id: str) -> bool:
        await self._get_owned_document(document_id, user_id)
        deleted = await self.repository.delete(document_id)
        if not deleted:
            raise ValueError(f"Document not found: {document_id}")
        return True

    async def _get_owned_document(
        self,
        document_id: str,
        user_id: str,
    ) -> DocumentModel:
        document = await self.repository.get_by_id(document_id)
        if document is None or document.user_id != user_id:
            raise ValueError(f"Document not found: {document_id}")
        return document
