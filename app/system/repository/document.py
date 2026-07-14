from logging import Logger

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import select

from app.system.models.documents import DocumentDBModel, DocumentModel
from app.utils.errors.document import (
    DocumentCreateError,
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

    async def create(self, document: DocumentModel) -> DocumentModel:
        async with self.session_factory() as session:
            db_document = DocumentDBModel(**document.model_dump_for_db())
            session.add(db_document)
            try:
                await session.commit()
            except IntegrityError as e:
                await session.rollback()
                try:
                    handle_document_integrity_error(
                        e, user_id=document.user_id, document_name=document.name
                    )
                except MissingUserForeignKeyError:
                    self.logger.warning(
                        "Missing user foreign key user_id=%s",
                        document.user_id,
                    )
                    raise
                except DocumentCreateError:
                    self.logger.exception(
                        "Error creating document id=%s",
                        document.id,
                    )
                    raise
            await session.refresh(db_document)
            self.logger.info("Document created id=%s", document.id)
            return DocumentModel(**db_document.model_dump())

    async def get_by_id(self, document_id: str) -> DocumentModel | None:
        async with self.session_factory() as session:
            db_document = await session.get(DocumentDBModel, document_id)
            if db_document is None:
                return None
            return DocumentModel(**db_document.model_dump())

    async def get_by_user_id(self, user_id: str) -> list[DocumentModel]:
        async with self.session_factory() as session:
            result = await session.execute(
                select(DocumentDBModel).where(DocumentDBModel.user_id == user_id)
            )
            return [
                DocumentModel(**db_document.model_dump())
                for db_document in result.scalars().all()
            ]

    async def update(self, document: DocumentModel) -> DocumentModel:
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
                self.logger.exception("Error updating document id=%s", document.id)
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
                self.logger.exception("Error deleting document id=%s", document_id)
                raise
            self.logger.info("Document deleted id=%s", document_id)
            return True
