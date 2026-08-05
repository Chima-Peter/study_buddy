from datetime import datetime, timezone
from logging import Logger

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import select

from app.system.quiz.model import QuizResultDBModel, QuizResultModel


class QuizRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        logger: Logger,
    ):
        self.session_factory = session_factory
        self.logger = logger

    async def create(self, quiz_result: QuizResultModel) -> QuizResultModel:
        async with self.session_factory() as session:
            db_row = QuizResultDBModel(**quiz_result.model_dump_for_db())
            session.add(db_row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                self.logger.exception(
                    "Error creating quiz result id=%s", quiz_result.id
                )
                raise

            await session.refresh(db_row)
            self.logger.info("Quiz result created id=%s", db_row.id)
            return QuizResultModel(**db_row.model_dump())

    async def get_by_document(
        self,
        document_id: str,
        user_id: str,
    ) -> QuizResultModel | None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(QuizResultDBModel).where(
                    QuizResultDBModel.document_id == document_id,
                    QuizResultDBModel.user_id == user_id,
                ).order_by(QuizResultDBModel.created_at.desc()).limit(1)
            )
            db_row = result.scalar_one_or_none()
            if db_row is None:
                return None
            return QuizResultModel(**db_row.model_dump())

    async def update_result(
        self,
        quiz_result_id: str,
        user_id: str,
        result: str,
    ) -> QuizResultModel | None:
        async with self.session_factory() as session:
            row = await session.execute(
                select(QuizResultDBModel).where(
                    QuizResultDBModel.id == quiz_result_id,
                    QuizResultDBModel.user_id == user_id,
                )
            )
            db_row = row.scalar_one_or_none()
            if db_row is None:
                return None

            db_row.result = result
            db_row.updated_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(db_row)
            self.logger.info("Quiz result updated id=%s", quiz_result_id)
            return QuizResultModel(**db_row.model_dump())
