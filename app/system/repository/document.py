from collections.abc import Sequence
from datetime import datetime, timezone
from logging import Logger

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import select

from app.system.models.documents import DocumentDBModel, DocumentModel
from app.system.schemas.document import DocumentStatus
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

    async def create(self, document: DocumentModel) -> DocumentModel | None:
        if not document:
            return None

        async with self.session_factory() as session:
            db_document = DocumentDBModel(**document.model_dump_for_db())
            session.add(db_document)
            try:
                await session.commit()
            except IntegrityError as e:
                await session.rollback()
                user_id = document.user_id
                try:
                    handle_document_integrity_error(
                        e,
                        user_id=user_id,
                        document=document,
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
                        "Error creating document id=%s",
                        document.id,
                    )
                    raise

            await session.refresh(db_document)

            self.logger.info(
                "Document created id=%s",
                db_document.id,
            )
            return DocumentModel(**db_document.model_dump())

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

            db_documents = result.scalars().all()

            self.logger.info(f"Documents found: {len(db_documents)}")

            return [DocumentModel(**db_document.model_dump()) for db_document in db_documents]

    async def update(self,  document: DocumentModel) -> DocumentModel:
        async with self.session_factory() as session:
            db_document = await session.get(DocumentDBModel, document.id)
            if db_document is None:
                raise ValueError(f"Document not found: {document.id}")

            db_document.name = document.name
            db_document.description = document.description
            db_document.category = document.category
            db_document.status = document.status
            db_document.hash = (document.hash or "").strip() or None
            db_document.path = document.path
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

    async def get_by_hash(self, hash: str, user_id: str) -> DocumentModel | None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(DocumentDBModel).where(
                    DocumentDBModel.hash == hash,
                    DocumentDBModel.user_id == user_id,
                )
            )
            db_document = result.scalar_one_or_none()
            if db_document is None:
                return None
            return DocumentModel(**db_document.model_dump())

    async def transition_status(
        self,
        document_id: str,
        user_id: str,
        to_status: DocumentStatus,
        from_statuses: Sequence[DocumentStatus],
        *,
        file_hash: str | None = None,
    ) -> DocumentModel | None:
        """Atomically move status only if current status is in from_statuses."""
        values: dict = {
            "status": to_status,
            "updated_at": datetime.now(timezone.utc),
        }
        if file_hash is not None:
            values["hash"] = file_hash.strip() or None

        async with self.session_factory() as session:
            result = await session.execute(
                update(DocumentDBModel)
                .where(
                    DocumentDBModel.id == document_id,
                    DocumentDBModel.user_id == user_id,
                    DocumentDBModel.status.in_(from_statuses),
                )
                .values(**values)
                .returning(DocumentDBModel)
            )
            db_document = result.scalar_one_or_none()
            if db_document is None:
                await session.rollback()
                return None
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                self.logger.exception(
                    "Error transitioning document id=%s to %s",
                    document_id,
                    to_status,
                )
                raise
            self.logger.info(
                "Document status transitioned id=%s to=%s",
                document_id,
                to_status,
            )
            return DocumentModel(**db_document.model_dump())
