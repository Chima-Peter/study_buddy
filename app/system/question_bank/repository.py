from datetime import datetime, timezone
from logging import Logger

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import select

from app.system.document.model import DocumentDBModel
from app.system.question_bank.model import QuestionBankDBModel, QuestionBankModel
from app.system.question_bank.schema import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    QuestionBankListItem,
    QuestionBankStatus,
)


class QuestionBankRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        logger: Logger,
    ):
        self.session_factory = session_factory
        self.logger = logger

    async def create(
        self, question_bank: QuestionBankModel
    ) -> QuestionBankModel:
        async with self.session_factory() as session:
            db_row = QuestionBankDBModel(**question_bank.model_dump_for_db())
            session.add(db_row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                self.logger.exception(
                    "Error creating question bank id=%s", question_bank.id
                )
                raise

            await session.refresh(db_row)
            self.logger.info("Question bank created id=%s", db_row.id)
            return QuestionBankModel(**db_row.model_dump())

    async def get_by_document(
        self,
        document_id: str,
        user_id: str,
    ) -> QuestionBankModel | None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(QuestionBankDBModel)
                .where(
                    QuestionBankDBModel.document_id == document_id,
                    QuestionBankDBModel.user_id == user_id,
                )
                .order_by(QuestionBankDBModel.created_at.desc())
                .limit(1)
            )
            db_row = result.scalar_one_or_none()
            if db_row is None:
                return None
            return QuestionBankModel(**db_row.model_dump())

    async def list_by_user(
        self,
        user_id: str,
        *,
        limit: int = DEFAULT_LIST_LIMIT,
        cursor: str | None = None,
        status: QuestionBankStatus | None = None,
    ) -> tuple[list[QuestionBankListItem], str | None, bool]:
        limit = min(max(limit, 1), MAX_LIST_LIMIT)

        async with self.session_factory() as session:
            filters = [QuestionBankDBModel.user_id == user_id]
            if status is not None:
                filters.append(QuestionBankDBModel.status == status)
            if cursor is not None:
                filters.append(QuestionBankDBModel.id < cursor)

            result = await session.execute(
                select(
                    QuestionBankDBModel.id,
                    QuestionBankDBModel.document_id,
                    QuestionBankDBModel.status,
                    QuestionBankDBModel.created_at,
                    DocumentDBModel.name,
                )
                .outerjoin(
                    DocumentDBModel,
                    QuestionBankDBModel.document_id == DocumentDBModel.id,
                )
                .where(*filters)
                .order_by(QuestionBankDBModel.id.desc())
                .limit(limit + 1)
            )
            db_rows = list(result.all())

            has_more = len(db_rows) > limit
            page = db_rows[:limit]
            next_cursor = page[-1][0] if has_more and page else None

            self.logger.info(
                "Question banks listed user_id=%s count=%s has_more=%s",
                user_id,
                len(page),
                has_more,
            )
            return (
                [
                    QuestionBankListItem(
                        id=str(row_id),
                        document_id=str(document_id),
                        document_name=document_name,
                        status=row_status,
                        created_at=(
                            created_at.isoformat()
                            if hasattr(created_at, "isoformat")
                            else str(created_at)
                        ),
                    )
                    for (
                        row_id,
                        document_id,
                        row_status,
                        created_at,
                        document_name,
                    ) in page
                ],
                str(next_cursor) if next_cursor is not None else None,
                has_more,
            )

    async def delete_by_document(
        self,
        document_id: str,
        user_id: str,
    ) -> bool:
        async with self.session_factory() as session:
            row = await session.execute(
                select(QuestionBankDBModel).where(
                    QuestionBankDBModel.document_id == document_id,
                    QuestionBankDBModel.user_id == user_id,
                )
            )
            db_row = row.scalar_one_or_none()
            if db_row is None:
                return False
            await session.delete(db_row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                self.logger.exception(
                    "Error deleting question bank document_id=%s", document_id
                )
                raise
            self.logger.info(
                "Question bank deleted document_id=%s user_id=%s",
                document_id,
                user_id,
            )
            return True

    async def update_result(
        self,
        document_id: str,
        user_id: str,
        result: dict,
        status: QuestionBankStatus = "success",
        reason: str | None = None,
    ) -> QuestionBankModel | None:
        async with self.session_factory() as session:
            row = await session.execute(
                select(QuestionBankDBModel).where(
                    QuestionBankDBModel.document_id == document_id,
                    QuestionBankDBModel.user_id == user_id,
                )
            )
            db_row = row.scalar_one_or_none()
            if db_row is None:
                return None

            db_row.result = result
            db_row.status = status
            db_row.reason = reason
            db_row.updated_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(db_row)
            self.logger.info(
                "Question bank updated document_id=%s status=%s",
                document_id,
                status,
            )
            return QuestionBankModel(**db_row.model_dump())

    async def update_status(
        self,
        document_id: str,
        user_id: str,
        status: QuestionBankStatus,
        reason: str | None = None,
    ) -> QuestionBankModel | None:
        async with self.session_factory() as session:
            row = await session.execute(
                select(QuestionBankDBModel).where(
                    QuestionBankDBModel.document_id == document_id,
                    QuestionBankDBModel.user_id == user_id,
                )
            )
            db_row = row.scalar_one_or_none()
            if db_row is None:
                return None

            db_row.status = status
            db_row.reason = reason
            db_row.updated_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(db_row)
            self.logger.info(
                "Question bank status updated document_id=%s status=%s",
                document_id,
                status,
            )
            return QuestionBankModel(**db_row.model_dump())
