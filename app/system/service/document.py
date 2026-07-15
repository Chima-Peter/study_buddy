from logging import Logger

from app.core.ingest_pipeline import IngestPipeline
from app.core.rabbitmq import RabbitMQ
from app.core.vector_store import VectorStore
from app.system.models.documents import DocumentModel
from app.system.repository.document import DocumentRepository
from app.system.schemas.document import (
    CreateDocumentRequest,
    DocumentResponse,
    DocumentStatus,
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
        rabbitmq: RabbitMQ,
    ):
        self.repository = repository
        self.logger = logger
        self.vector_store = vector_store
        self.ingest_pipeline = ingest_pipeline
        self.rabbitmq = rabbitmq

    async def create_document(
        self,
        request: CreateDocumentRequest,
        user_id: str,
    ) -> DocumentResponse:
        document = DocumentModel.from_request(request, user_id)
        result = await self.repository.create(document)
        if result is None:
            raise DocumentCreateError(
                "Failed to create document",
                file_name=request.file_name,
            )

        ingest_payload = IngestDocumentRequest(
            name=request.name,
            file_name=request.file_name,
            category=request.category,
            path=request.path,
            user_id=user_id,
            document_id=result.id,
        )

        # send message to queue
        self.rabbitmq.publish_message(
          "document_queue",
          ingest_payload.model_dump()
        )
        self.logger.info(f"Sent message to document_queue: {ingest_payload.model_dump()}")

        return result.to_response()

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

    async def get_document_by_hash(
        self, hash: str, user_id: str
    ) -> DocumentResponse | None:
        document = await self.repository.get_by_hash(hash, user_id)
        if document is None:
            return None
        return document.to_response()

    async def claim_for_processing(
        self,
        document_id: str,
        user_id: str,
    ) -> DocumentResponse | None:
        result = await self.repository.transition_status(
            document_id,
            user_id,
            "processing",
            ("pending", "processing"),
        )
        return result.to_response() if result else None

    async def update_status(
        self,
        document_id: str,
        status: DocumentStatus,
        user_id: str,
        *,
        from_statuses: tuple[DocumentStatus, ...] = ("pending", "processing"),
    ) -> DocumentResponse | None:
        result = await self.repository.transition_status(
            document_id,
            user_id,
            status,
            from_statuses,
        )
        return result.to_response() if result else None

    async def complete_document(
        self,
        document_id: str,
        user_id: str,
        file_hash: str,
    ) -> DocumentResponse | None:
        result = await self.repository.transition_status(
            document_id,
            user_id,
            "completed",
            ("processing",),
            file_hash=file_hash,
        )
        return result.to_response() if result else None

    async def _get_owned_document(
        self,
        document_id: str,
        user_id: str,
    ) -> DocumentModel:
        document = await self.repository.get_by_id(document_id, user_id)
        if document is None:
            raise ValueError(f"Document not found: {document_id}")
        return document
