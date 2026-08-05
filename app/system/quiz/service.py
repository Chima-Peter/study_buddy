from logging import Logger

from app.core.rabbitmq import RabbitMQ
from app.system.document.service import DocumentService
from app.system.quiz.model import QuizResultModel
from app.system.quiz.repository import QuizRepository
from app.system.quiz.schema import QuizGenerateAccepted, QuizGenerateRequest


class QuizService:
    def __init__(
        self,
        repository: QuizRepository,
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
    ) -> QuizGenerateAccepted:
        await self.document_service.get_document_by_id(document_id, user_id)

        await self.repository.create(
            QuizResultModel.pending(document_id=document_id, user_id=user_id)
        )

        payload = QuizGenerateRequest(
            document_id=document_id,
            user_id=user_id,
        )
        await self.rabbitmq.publish_message(
            "quiz_generate_queue",
            payload.model_dump(),
        )
        self.logger.info(
            "Queued quiz generate document_id=%s user_id=%s",
            document_id,
            user_id,
        )
        return QuizGenerateAccepted(document_id=document_id)
