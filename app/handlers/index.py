import asyncio
from collections.abc import Awaitable, Coroutine
from logging import Logger
from typing import Any

from aio_pika.abc import AbstractIncomingMessage

from app.core.elasticsearch import Elasticsearch
from app.core.embedding import EmbeddingManager
from app.core.rabbitmq import RabbitMQ
from app.core.redis import RedisClient
from app.core.supabase import Supabase
from app.handlers.document import (
    handle_document,
    handle_document_dead_letter_queue,
)
from app.handlers.mail import handle_mail, handle_mail_dead_letter_queue
from app.handlers.memory_extract import (
    handle_memory_extract,
    handle_memory_extract_dead_letter_queue,
)
from app.agent.study_cards_agent.graph import StudyCardsGraph
from app.handlers.study_cards_generate import (
    handle_study_cards_generate,
    handle_study_cards_generate_dead_letter_queue,
)
from app.memory.service import MemoryService
from app.rag.chapter_splitter import ChapterSplitter
from app.rag.ingest_pipeline import IngestPipeline
from app.system.document.service import DocumentService
from app.system.notification.service import NotificationService
from app.system.study_cards.service import StudyCardsService


class Handlers:
    def __init__(
        self,
        logger: Logger,
        ingest_pipeline: IngestPipeline,
        chapter_splitter: ChapterSplitter,
        supabase: Supabase,
        document_service: DocumentService,
        embedding_manager: EmbeddingManager,
        elasticsearch: Elasticsearch,
        rabbitmq: RabbitMQ,
        redis: RedisClient,
        notification_service: NotificationService,
        memory_service: MemoryService,
        study_cards_graph: StudyCardsGraph,
        study_cards_service: StudyCardsService,
    ):
        self._logger = logger
        self._ingest_pipeline = ingest_pipeline
        self._chapter_splitter = chapter_splitter
        self._supabase = supabase
        self._document_service = document_service
        self._embedding_manager = embedding_manager
        self._elasticsearch = elasticsearch
        self._rabbitmq = rabbitmq
        self._redis = redis
        self._notification_service = notification_service
        self._memory_service = memory_service
        self._study_cards_graph = study_cards_graph
        self._study_cards_service = study_cards_service
        self._background_tasks: set[asyncio.Task[Any]] = set()

    def _fire_and_forget(
        self,
        coro: Coroutine[Any, Any, Any] | Awaitable[Any],
        *,
        label: str,
    ) -> None:
        """Schedule work without blocking the RabbitMQ consumer callback."""
        task = asyncio.create_task(coro, name=label)
        self._background_tasks.add(task)

        def _on_done(done: asyncio.Task[Any]) -> None:
            self._background_tasks.discard(done)
            if done.cancelled():
                self._logger.warning("Handler cancelled label=%s", label)
                return
            exc = done.exception()
            if exc is not None:
                self._logger.error(
                    "Handler failed label=%s",
                    label,
                    exc_info=exc,
                )
                return
            self._logger.debug("Handler completed label=%s", label)

        task.add_done_callback(_on_done)

    async def handle_mail(self, message: AbstractIncomingMessage) -> None:
        self._fire_and_forget(handle_mail(message), label="handle_mail")

    async def handle_document(self, message: AbstractIncomingMessage) -> None:
        self._fire_and_forget(
            handle_document(
                message,
                self._ingest_pipeline,
                self._chapter_splitter,
                self._logger,
                self._supabase,
                self._document_service,
                self._embedding_manager,
                self._elasticsearch,
                self._rabbitmq,
                self._redis,
                self._notification_service,
            ),
            label="handle_document",
        )

    async def handle_memory_extract(
        self, message: AbstractIncomingMessage
    ) -> None:
        self._fire_and_forget(
            handle_memory_extract(
                message,
                memory_service=self._memory_service,
                logger=self._logger,
                rabbitmq=self._rabbitmq,
            ),
            label="handle_memory_extract",
        )

    async def handle_study_cards_generate(
        self, message: AbstractIncomingMessage
    ) -> None:
        self._fire_and_forget(
            handle_study_cards_generate(
                message,
                logger=self._logger,
                rabbitmq=self._rabbitmq,
                study_cards_graph=self._study_cards_graph,
                study_cards_service=self._study_cards_service,
                redis=self._redis,
                notification_service=self._notification_service,
            ),
            label="handle_study_cards_generate",
        )

    async def handle_mail_dead_letter_queue(
        self, message: AbstractIncomingMessage
    ) -> None:
        self._fire_and_forget(
            handle_mail_dead_letter_queue(message, self._logger),
            label="handle_mail_dead_letter_queue",
        )

    async def handle_document_dead_letter_queue(
        self, message: AbstractIncomingMessage
    ) -> None:
        self._fire_and_forget(
            handle_document_dead_letter_queue(
                message,
                self._logger,
                self._document_service,
                self._redis,
                self._notification_service,
            ),
            label="handle_document_dead_letter_queue",
        )

    async def handle_memory_extract_dead_letter_queue(
        self, message: AbstractIncomingMessage
    ) -> None:
        self._fire_and_forget(
            handle_memory_extract_dead_letter_queue(message, self._logger),
            label="handle_memory_extract_dead_letter_queue",
        )

    async def handle_study_cards_generate_dead_letter_queue(
        self, message: AbstractIncomingMessage
    ) -> None:
        self._fire_and_forget(
            handle_study_cards_generate_dead_letter_queue(
                message,
                self._logger,
            ),
            label="handle_study_cards_generate_dead_letter_queue",
        )
