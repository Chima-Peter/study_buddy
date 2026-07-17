from logging import Logger

from aio_pika.abc import AbstractIncomingMessage

from app.core.elasticsearch import Elasticsearch
from app.core.embedding import EmbeddingManager
from app.core.handlers.dead_letter_queue import handle_dead_letter_queue as process_dead_letter_queue
from app.core.handlers.document import handle_document
from app.core.handlers.mail import handle_mail
from app.core.ingest_pipeline import IngestPipeline
from app.core.rabbitmq import RabbitMQ
from app.core.supabase import Supabase
from app.system.service.document import DocumentService


class Handlers:
    def __init__(
        self,
        logger: Logger,
        ingest_pipeline: IngestPipeline,
        supabase: Supabase,
        document_service: DocumentService,
        embedding_manager: EmbeddingManager,
        elasticsearch: Elasticsearch,
        rabbitmq: RabbitMQ,
    ):
        self._logger = logger
        self._ingest_pipeline = ingest_pipeline
        self._supabase = supabase
        self._document_service = document_service
        self._embedding_manager = embedding_manager
        self._elasticsearch = elasticsearch
        self._rabbitmq = rabbitmq

    async def handle_mail(self, message: AbstractIncomingMessage) -> None:
        await handle_mail(message)

    async def handle_document(self, message: AbstractIncomingMessage) -> None:
        await handle_document(
            message,
            self._ingest_pipeline,
            self._logger,
            self._supabase,
            self._document_service,
            self._embedding_manager,
            self._elasticsearch,
            self._rabbitmq,
        )

    async def handle_dead_letter_queue(self, message: AbstractIncomingMessage) -> None:
        await process_dead_letter_queue(
            message,
            self._logger,
            self._document_service,
        )
