from logging import Logger

from sqlalchemy.exc import IntegrityError

from app.core.rabbitmq import RabbitMQ
from app.system.document.service import DocumentService
from app.system.study_cards.model import StudyCardsModel
from app.system.study_cards.repository import StudyCardsRepository
from app.system.study_cards.schema import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    StudyCardsAlreadyExistsError,
    StudyCardsGenerateAccepted,
    StudyCardsGenerateRequest,
    StudyCardsInProgressError,
    StudyCardsListResponseData,
    StudyCardsStatus,
)


class StudyCardsService:
    def __init__(
        self,
        repository: StudyCardsRepository,
        document_service: DocumentService,
        rabbitmq: RabbitMQ,
        logger: Logger,
    ):
        self.repository = repository
        self.document_service = document_service
        self.rabbitmq = rabbitmq
        self.logger = logger

    async def enqueue_generate(
        self,
        document_id: str,
        user_id: str,
    ) -> StudyCardsGenerateAccepted:
        document = await self.document_service.get_document_by_id(
            document_id, user_id
        )

        existing = await self.repository.get_by_document(document_id, user_id)
        if existing is not None:
            if existing.status == "success":
                raise StudyCardsAlreadyExistsError(document_id)
            if existing.status == "pending":
                raise StudyCardsInProgressError(document_id)
            if existing.status == "failed":
                await self.repository.delete_by_document(document_id, user_id)
                self.logger.info(
                    "Deleted failed study cards before regenerate "
                    "document_id=%s user_id=%s",
                    document_id,
                    user_id,
                )

        try:
            await self.repository.create(
                StudyCardsModel.pending(document_id=document_id, user_id=user_id)
            )
        except IntegrityError as e:
            raise StudyCardsAlreadyExistsError(document_id) from e

        payload = StudyCardsGenerateRequest(
            document_id=document_id,
            user_id=user_id,
            name=document.name,
        )
        await self.rabbitmq.publish_message(
            "study_cards_generate_queue",
            payload.model_dump(),
        )
        self.logger.info(
            "Queued study cards generate document_id=%s user_id=%s",
            document_id,
            user_id,
        )
        return StudyCardsGenerateAccepted(document_id=document_id)

    async def update_result(
        self,
        document_id: str,
        user_id: str,
        result: dict,
    ) -> StudyCardsModel:
        self.logger.info(
            "Updating study cards result document_id=%s user_id=%s",
            document_id,
            user_id,
        )
        study_card = await self.repository.update_result(
            document_id,
            user_id,
            result,
            status="success",
        )
        if study_card is None:
            raise ValueError("Study cards not found")
        self.logger.info(
            "Study cards result updated document_id=%s user_id=%s status=success",
            document_id,
            user_id,
        )
        return study_card

    async def mark_failed(
        self,
        document_id: str,
        user_id: str,
    ) -> StudyCardsModel | None:
        self.logger.info(
            "Marking study cards failed document_id=%s user_id=%s",
            document_id,
            user_id,
        )
        return await self.repository.update_status(
            document_id,
            user_id,
            status="failed",
        )

    async def get_by_document(
        self,
        document_id: str,
        user_id: str,
    ) -> StudyCardsModel:
        self.logger.info(
            "Getting study cards by document id=%s user_id=%s",
            document_id,
            user_id,
        )
        study_card = await self.repository.get_by_document(document_id, user_id)
        if study_card is None:
            raise ValueError("Study cards not found")
        self.logger.info(
            "Study cards found id=%s status=%s user_id=%s",
            study_card.id,
            study_card.status,
            user_id,
        )
        return study_card

    async def list_by_user(
        self,
        user_id: str,
        *,
        limit: int = DEFAULT_LIST_LIMIT,
        cursor: str | None = None,
        status: StudyCardsStatus | None = None,
    ) -> StudyCardsListResponseData:
        self.logger.info(
            "Listing study cards user_id=%s limit=%s cursor=%s status=%s",
            user_id,
            limit,
            cursor,
            status,
        )
        items, next_cursor, has_more = await self.repository.list_by_user(
            user_id,
            limit=limit,
            cursor=cursor,
            status=status,
        )

        self.logger.info(
            "Study cards listed user_id=%s count=%s has_more=%s",
            user_id,
            len(items),
            has_more,
        )
        return StudyCardsListResponseData(
            items=[
                item.to_response(document_name=document_name)
                for item, document_name in items
            ],
            next_cursor=next_cursor,
            has_more=has_more,
            limit=min(max(limit, 1), MAX_LIST_LIMIT),
        )
