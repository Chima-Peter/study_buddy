from logging import Logger

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import select

from app.system.models.documents import DocumentDBModel, DocumentModel
from app.utils.errors.document import (
    DocumentCreateError,
    DuplicateDocumentHashError,
    DuplicateDocumentNameError,
    MissingUserForeignKeyError,
    handle_document_integrity_error,
)


class DocumentRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        logger: Logger,
    ):
        self.session_factory = session_factory
        self.logger = logger

    async def create(self, documents: list[DocumentModel]) -> list[DocumentModel]:
        if not documents:
            return []

        self._guard_unique_hashes(documents)

        async with self.session_factory() as session:
            db_documents = [
                DocumentDBModel(**document.model_dump_for_db())
                for document in documents
            ]
            session.add_all(db_documents)
            try:
                await session.commit()
            except IntegrityError as e:
                await session.rollback()
                user_id = documents[0].user_id
                try:
                    handle_document_integrity_error(
                        e,
                        user_id=user_id,
                        documents=documents,
                    )
                except MissingUserForeignKeyError:
                    self.logger.warning(
                        "Missing user foreign key user_id=%s",
                        user_id,
                    )
                    raise
                except (DuplicateDocumentNameError, DuplicateDocumentHashError) as err:
                    self.logger.warning("%s", err)
                    raise
                except DocumentCreateError:
                    self.logger.exception(
                        "Error creating documents ids=%s",
                        [document.id for document in documents],
                    )
                    raise

            for db_document in db_documents:
                await session.refresh(db_document)

            self.logger.info(
                "Documents created ids=%s",
                [db_document.id for db_document in db_documents],
            )
            return [
                DocumentModel(**db_document.model_dump())
                for db_document in db_documents
            ]

    def _guard_unique_hashes(self, documents: list[DocumentModel]) -> None:
        seen: dict[tuple[str, str], str] = {}
        for document in documents:
            document_hash = (document.hash or "").strip()
            if not document_hash:
                continue
            key = (document_hash, document.user_id)
            if key in seen:
                raise DuplicateDocumentHashError(
                    document_hash,
                    file_names=[seen[key], document.display_file_name],
                )
            seen[key] = document.display_file_name

    async def get_by_id(self, document_id: str, user_id: str) -> DocumentModel | None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(DocumentDBModel).where(
                    DocumentDBModel.id == document_id,
                    DocumentDBModel.user_id == user_id,
                )
            )
            db_document = result.scalar_one_or_none()
            if db_document is None:
                return None
            return DocumentModel(**db_document.model_dump())

    async def get_by_user_id(self, user_id: str) -> list[DocumentModel]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(DocumentDBModel).where(
                    DocumentDBModel.user_id == user_id)
            )
            return [
                DocumentModel(**db_document.model_dump())
                for db_document in result.scalars().all()
            ]

    async def update(self,  document: DocumentModel) -> DocumentModel:
        async with self.session_factory() as session:
            db_document = await session.get(DocumentDBModel, document.id)
            if db_document is None:
                raise ValueError(f"Document not found: {document.id}")

            db_document.name = document.name
            db_document.description = document.description
            db_document.category = document.category
            db_document.updated_at = document.updated_at

            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                self.logger.exception(
                    "Error updating document id=%s", document.id)
                raise
            await session.refresh(db_document)
            self.logger.info("Document updated id=%s", document.id)
            return DocumentModel(**db_document.model_dump())

    async def delete(self, document_id: str) -> bool:
        async with self.session_factory() as session:
            db_document = await session.get(DocumentDBModel, document_id)
            if db_document is None:
                return False

            await session.delete(db_document)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                self.logger.exception(
                    "Error deleting document id=%s", document_id)
                raise
            self.logger.info("Document deleted id=%s", document_id)
            return True
