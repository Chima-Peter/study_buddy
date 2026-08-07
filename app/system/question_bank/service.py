from logging import Logger
import random

from sqlalchemy.exc import IntegrityError

from app.core.rabbitmq import RabbitMQ
from app.system.document.service import DocumentService
from app.system.question_bank.model import QuestionBankModel
from app.system.question_bank.repository import QuestionBankRepository
from app.system.question_bank.schema import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    QuestionBankAlreadyExistsError,
    QuestionBankGenerateAccepted,
    QuestionBankGenerateRequest,
    QuestionBankInProgressError,
    QuestionBankListResponseData,
    QuestionBankStatus,
)


class QuestionBankService:
    def __init__(
        self,
        repository: QuestionBankRepository,
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
    ) -> QuestionBankGenerateAccepted:
        document = await self.document_service.get_document_by_id(
            document_id, user_id
        )

        existing = await self.repository.get_by_document(document_id, user_id)
        if existing is not None:
            if existing.status == "success":
                raise QuestionBankAlreadyExistsError(document_id)
            if existing.status == "pending":
                raise QuestionBankInProgressError(document_id)
            if existing.status == "failed":
                await self.repository.delete_by_document(document_id, user_id)
                self.logger.info(
                    "Deleted failed question bank before regenerate "
                    "document_id=%s user_id=%s",
                    document_id,
                    user_id,
                )

        try:
            await self.repository.create(
                QuestionBankModel.pending(
                    document_id=document_id, user_id=user_id
                )
            )
        except IntegrityError as e:
            raise QuestionBankAlreadyExistsError(document_id) from e

        payload = QuestionBankGenerateRequest(
            document_id=document_id,
            user_id=user_id,
            name=document.name,
        )
        await self.rabbitmq.publish_message(
            "question_bank_generate_queue",
            payload.model_dump(),
        )
        self.logger.info(
            "Queued question bank generate document_id=%s user_id=%s",
            document_id,
            user_id,
        )
        return QuestionBankGenerateAccepted(document_id=document_id)

    async def update_result(
        self,
        document_id: str,
        user_id: str,
        result: list,
        reason: str | None = None,
    ) -> QuestionBankModel:
        self.logger.info(
            "Updating question bank result document_id=%s user_id=%s",
            document_id,
            user_id,
        )
        question_bank = await self.repository.update_result(
            document_id,
            user_id,
            result,
            status="success",
            reason=reason,
        )
        if question_bank is None:
            raise ValueError("Question bank not found")
        self.logger.info(
            "Question bank result updated document_id=%s user_id=%s "
            "status=success",
            document_id,
            user_id,
        )
        return question_bank

    async def mark_failed(
        self,
        document_id: str,
        user_id: str,
        reason: str | None = None,
    ) -> QuestionBankModel | None:
        self.logger.info(
            "Marking question bank failed document_id=%s user_id=%s",
            document_id,
            user_id,
        )
        return await self.repository.update_status(
            document_id,
            user_id,
            status="failed",
            reason=reason,
        )

    async def get_by_document(
        self,
        document_id: str,
        user_id: str,
    ) -> QuestionBankModel:
        self.logger.info(
            "Getting question bank by document id=%s user_id=%s",
            document_id,
            user_id,
        )
        question_bank = await self.repository.get_by_document(
            document_id, user_id
        )
        if question_bank is None:
            raise ValueError("Question bank not found")

        if isinstance(question_bank.result, list):
            shuffled = list(question_bank.result)
            random.shuffle(shuffled)
            question_bank = question_bank.model_copy(update={"result": shuffled})

        self.logger.info(
            "Question bank found id=%s status=%s user_id=%s",
            question_bank.id,
            question_bank.status,
            user_id,
        )
        return question_bank

    async def list_by_user(
        self,
        user_id: str,
        *,
        limit: int = DEFAULT_LIST_LIMIT,
        cursor: str | None = None,
        status: QuestionBankStatus | None = None,
    ) -> QuestionBankListResponseData:
        self.logger.info(
            "Listing question banks user_id=%s limit=%s cursor=%s status=%s",
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
            "Question banks listed user_id=%s count=%s has_more=%s",
            user_id,
            len(items),
            has_more,
        )
        return QuestionBankListResponseData(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
            limit=min(max(limit, 1), MAX_LIST_LIMIT),
        )
