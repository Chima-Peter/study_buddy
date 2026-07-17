from datetime import datetime, timezone
from logging import Logger
from pathlib import Path

from app.core.elasticsearch import Elasticsearch
from app.core.ingest_pipeline import IngestPipeline
from app.core.rabbitmq import RabbitMQ
from app.core.supabase import Supabase
from app.core.vector_store import VectorStore
from app.system.models.documents import DocumentModel
from app.system.repository.document import DocumentRepository
from app.system.schemas.document import (
    DOCUMENT_STATUS_COMMENTS,
    CreateDocumentRequest,
    DocumentResponse,
    DocumentStatus,
    IngestDocumentRequest,
    PatchDocumentRequest,
    UpdateDocumentRequest,
)
from app.utils.errors.document import DocumentCreateError, DocumentNotRetryableError


class DocumentService:
    def __init__(
        self,
        repository: DocumentRepository,
        logger: Logger,
        ingest_pipeline: IngestPipeline,
        vector_store: VectorStore,
        rabbitmq: RabbitMQ,
        elasticsearch: Elasticsearch,
        supabase: Supabase,
    ):
        self.repository = repository
        self.logger = logger
        self.vector_store = vector_store
        self.ingest_pipeline = ingest_pipeline
        self.rabbitmq = rabbitmq
        self.elasticsearch = elasticsearch
        self.supabase = supabase

    async def create_document(
        self,
        request: CreateDocumentRequest,
        user_id: str,
        path: str,
    ) -> DocumentResponse:
        document = DocumentModel.from_request(request, user_id, path)
        result = await self.repository.create(document)
        if result is None:
            raise DocumentCreateError(
                "Failed to create document",
                file_name=request.file_name,
            )

        return result.to_response()

    async def start_ingestion(
        self,
        document_id: str,
        user_id: str,
    ) -> DocumentResponse:
        document = await self._get_owned_document(document_id, user_id)
        if not document.path:
            await self.repository.transition_status(
                document_id,
                user_id,
                "failed",
                ("pending",),
                comment=DOCUMENT_STATUS_COMMENTS["failed"],
            )
            raise ValueError(f"Document path not found: {document_id}")

        await self._enqueue_ingest(document, user_id)
        return document.to_response()

    async def retry_ingestion(
        self,
        document_id: str,
        user_id: str,
    ) -> DocumentResponse:
        document = await self._get_owned_document(document_id, user_id)
        if not document.path:
            raise ValueError(f"Document path not found: {document_id}")

        updated = await self.repository.transition_status(
            document_id,
            user_id,
            "pending",
            ("failed",),
        )
        if updated is None:
            raise DocumentNotRetryableError(document_id, document.status)

        try:
            await self._enqueue_ingest(updated, user_id)
        except Exception:
            await self.repository.transition_status(
                document_id,
                user_id,
                "failed",
                ("pending",),
            )
            raise

        return updated.to_response()

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
        document = await self._get_owned_document(document_id, user_id)

        deleted_chunks = await self.elasticsearch.delete_by_document_id(
            user_id, document_id
        )
        self.logger.info(
            "Deleted %s Elasticsearch chunks for document_id=%s",
            deleted_chunks,
            document_id,
        )

        if document.path:
            await self.supabase.delete_file(document.path)

        self.logger.info(
            "Deleted file from Supabase for document_id=%s",
            document_id,
        )

        deleted = await self.repository.delete(document_id)
        if not deleted:
            raise ValueError(f"Document not found: {document_id}")
        return True

    async def get_document_by_hash(
        self, file_hash: str, user_id: str
    ) -> DocumentResponse | None:
        document = await self.repository.get_by_hash(file_hash, user_id)
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

    async def cancel_duplicate(
        self,
        document_id: str,
        user_id: str,
        path: str,
    ) -> DocumentResponse:
        document = await self._get_owned_document(document_id, user_id)
        document.path = path
        document.status = "cancelled"
        document.comment = DOCUMENT_STATUS_COMMENTS["cancelled"]
        document.updated_at = datetime.now(timezone.utc)
        result = await self.repository.update(document)
        return result.to_response()

    async def _enqueue_ingest(
        self,
        document: DocumentModel,
        user_id: str,
    ) -> None:
        if not document.path:
            raise ValueError(f"Document path not found: {document.id}")

        file_name = document.file_name or Path(document.path).name
        ingest_payload = IngestDocumentRequest(
            name=document.name,
            file_name=file_name,
            category=document.category,
            path=document.path,
            user_id=user_id,
            document_id=document.id,
        )

        await self.rabbitmq.publish_message(
            "document_queue",
            ingest_payload.model_dump(),
        )
        self.logger.info(
            "Sent message to document_queue: %s",
            ingest_payload.model_dump(),
        )

    async def _get_owned_document(
        self,
        document_id: str,
        user_id: str,
    ) -> DocumentModel:
        document = await self.repository.get_by_id(document_id, user_id)
        if document is None:
            raise ValueError(f"Document not found: {document_id}")
        return document
