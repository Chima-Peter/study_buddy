from logging import Logger

from app.core.rabbitmq import RabbitMQ
from app.system.document.service import DocumentService
from app.system.study_cards.model import StudyCardsModel
from app.system.study_cards.repository import StudyCardsRepository
from app.system.study_cards.schema import (
    StudyCardsGenerateAccepted,
    StudyCardsGenerateRequest,
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
        await self.document_service.get_document_by_id(document_id, user_id)

        await self.repository.create(
            StudyCardsModel.pending(document_id=document_id, user_id=user_id)
        )

        payload = StudyCardsGenerateRequest(
            document_id=document_id,
            user_id=user_id,
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
