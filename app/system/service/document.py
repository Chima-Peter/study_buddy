from logging import Logger

from app.core.vector_store import VectorStore
from app.system.models.documents import DocumentModel
from app.system.repository.document import DocumentRepository
from app.system.schemas.document import (
    CreateDocumentRequest,
    DocumentResponse,
    PatchDocumentRequest,
    UpdateDocumentRequest,
)


class DocumentService:
    def __init__(
        self,
        repository: DocumentRepository,
        logger: Logger,
        vector_store: VectorStore,
    ):
        self.repository = repository
        self.logger = logger
        self.vector_store = vector_store

    async def create_document(
        self,
        request: CreateDocumentRequest,
        user_id: str,
    ) -> DocumentResponse:
        document = DocumentModel.from_request(request, user_id)
        result = await self.repository.create(document)
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

    async def _get_owned_document(
        self,
        document_id: str,
        user_id: str,
    ) -> DocumentModel:
        document = await self.repository.get_by_id(document_id)
        if document is None or document.user_id != user_id:
            raise ValueError(f"Document not found: {document_id}")
        return document
