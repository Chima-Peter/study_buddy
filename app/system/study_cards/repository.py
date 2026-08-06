from datetime import datetime, timezone
from logging import Logger

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import select

from app.system.study_cards.model import StudyCardsDBModel, StudyCardsModel


class StudyCardsRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        logger: Logger,
    ):
        self.session_factory = session_factory
        self.logger = logger

    async def create(self, study_cards: StudyCardsModel) -> StudyCardsModel:
        async with self.session_factory() as session:
            db_row = StudyCardsDBModel(**study_cards.model_dump_for_db())
            session.add(db_row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                self.logger.exception(
                    "Error creating study cards id=%s", study_cards.id
                )
                raise

            await session.refresh(db_row)
            self.logger.info("Study cards created id=%s", db_row.id)
            return StudyCardsModel(**db_row.model_dump())

    async def get_by_document(
        self,
        document_id: str,
        user_id: str,
    ) -> StudyCardsModel | None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(StudyCardsDBModel).where(
                    StudyCardsDBModel.document_id == document_id,
                    StudyCardsDBModel.user_id == user_id,
                ).order_by(StudyCardsDBModel.created_at.desc()).limit(1)
            )
            db_row = result.scalar_one_or_none()
            if db_row is None:
                return None
            return StudyCardsModel(**db_row.model_dump())

    async def update_result(
        self,
        document_id: str,
        user_id: str,
        result: dict,
    ) -> StudyCardsModel | None:
        async with self.session_factory() as session:
            row = await session.execute(
                select(StudyCardsDBModel).where(
                    StudyCardsDBModel.document_id == document_id,
                    StudyCardsDBModel.user_id == user_id,
                )
            )
            db_row = row.scalar_one_or_none()
            if db_row is None:
                return None

            db_row.result = result
            db_row.updated_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(db_row)
            self.logger.info("Study cards updated document_id=%s", document_id)
            return StudyCardsModel(**db_row.model_dump())
