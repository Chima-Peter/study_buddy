import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from logging import Logger

import aio_pika
import redis
from dependency_injector import containers, providers
from redis.asyncio import Redis, from_url
from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker

from app.authentication.repository import UserRepository
from app.authentication.services import AuthService
from app.config import Settings
from app.core.embedding import EmbeddingManager, SentenceTransformerEmbeddings
from app.core.handlers import Handlers
from app.core.ingest_pipeline import IngestPipeline
from app.core.rabbitmq import RabbitMQ, RabbitMQConsumer
from app.core.redis import RedisClient
from app.core.vector_store import VectorStore
from app.logging_config import init_logging
from app.system.repository.document import DocumentRepository
from app.system.service.document import DocumentService


def init_sync_engine(database_url: str) -> Iterator[Engine]:
    """Create the sync SQLAlchemy engine and dispose it on shutdown."""
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


def init_sync_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)


async def init_async_engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    """Create the async SQLAlchemy engine and dispose it on shutdown."""
    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        await engine.dispose()


def init_async_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(bind=engine, expire_on_commit=False)


def init_sync_redis(redis_url: str) -> Iterator[redis.Redis]:
    """Create the sync Redis client and close it on shutdown."""
    client: redis.Redis = redis.from_url(redis_url, decode_responses=True)
    try:
        yield client
    finally:
        client.close()


async def init_async_redis(redis_url: str) -> AsyncIterator[Redis]:
    """Create the async Redis client and close it on shutdown."""
    client: Redis = from_url(redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@dataclass
class RabbitMQResources:
    channel: aio_pika.Channel
    email_queue: aio_pika.Queue
    email_dlq_queue: aio_pika.Queue
    document_queue: aio_pika.Queue
    document_dlq_queue: aio_pika.Queue


MAX_QUEUE_BYTES = 10 * 1024 * 1024  # 10 MB


async def init_async_rabbitmq_queue(
    channel: aio_pika.Channel, queue_name: str
) -> tuple[aio_pika.Queue, aio_pika.Queue]:
    dlq = await channel.declare_queue(
        name=f"{queue_name}_dlq",
        durable=True,
        arguments={
            "x-queue-type": "quorum",
            "x-max-length": 10000,
            "x-max-length-bytes": MAX_QUEUE_BYTES,
            "x-message-ttl": 604800000,
        },
    )
    queue = await channel.declare_queue(
        name=queue_name,
        durable=True,
        arguments={
            "x-queue-type": "quorum",
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": f"{queue_name}_dlq",
            "x-delivery-limit": 3,
            "x-max-length-bytes": MAX_QUEUE_BYTES,
        },
    )
    return queue, dlq


async def init_async_rabbitmq(rabbitmq_url: str, logger: Logger) -> AsyncIterator[RabbitMQResources]:
    try:
        connection = await aio_pika.connect_robust(rabbitmq_url)
        channel = await connection.channel(
            publisher_confirms=True,
            on_return_raises=True,
        )
    except Exception as e:
        logger.exception("Error connecting to RabbitMQ")
        raise e
    await channel.set_qos(prefetch_count=10)

    email_queue, email_dlq_queue = await init_async_rabbitmq_queue(channel, "mail_queue")
    document_queue, document_dlq_queue = await init_async_rabbitmq_queue(channel, "document_queue")

    try:
        yield RabbitMQResources(
            channel=channel,
            email_queue=email_queue,
            email_dlq_queue=email_dlq_queue,
            document_queue=document_queue,
            document_dlq_queue=document_dlq_queue,
        )
    finally:
        try:
            await asyncio.wait_for(channel.close(), timeout=2.0)
        except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
            pass
        try:
            await asyncio.wait_for(connection.close(), timeout=2.0)
        except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
            pass


async def init_rabbitmq_consumers(
    rabbitmq: RabbitMQ,
    handlers: Handlers,
) -> AsyncIterator[list[RabbitMQConsumer]]:
    active_consumers = await rabbitmq.start_consumers(
        email_callback=handlers.handle_mail,
        document_callback=handlers.handle_document,
        dlq_callback=handlers.handle_dead_letter_queue,
    )
    try:
        yield active_consumers
    finally:
        await rabbitmq.stop_consumers(active_consumers)


class Container(containers.DeclarativeContainer):
    """Application dependency container."""

    settings = providers.Singleton(Settings)

    logger = providers.Resource(
        init_logging,
        log_level=settings.provided.log_level,
    )

    sync_redis = providers.Resource(
        init_sync_redis,
        redis_url=settings.provided.redis_url,
    )

    async_redis = providers.Resource(
        init_async_redis,
        redis_url=settings.provided.redis_url,
    )

    sync_engine = providers.Resource(
        init_sync_engine,
        database_url=settings.provided.sync_database_url,
    )

    sync_session_factory = providers.Singleton(
        init_sync_session_factory,
        engine=sync_engine,
    )

    async_engine = providers.Resource(
        init_async_engine,
        database_url=settings.provided.database_url,
    )

    async_session_factory = providers.Singleton(
        init_async_session_factory,
        engine=async_engine,
    )

    rabbitmq_resources = providers.Resource(
        init_async_rabbitmq,
        rabbitmq_url=settings.provided.rabbitmq_url,
        logger=logger,
    )

    user_repository = providers.Factory(
        UserRepository,
        session_factory=async_session_factory,
        logger=logger,
    )

    redis_client = providers.Factory(
        RedisClient,
        redis=async_redis,
        logger=logger,
    )

    rabbitmq = providers.Factory(
        RabbitMQ,
        channel=rabbitmq_resources.provided.channel,
        email_queue=rabbitmq_resources.provided.email_queue,
        email_dlq_queue=rabbitmq_resources.provided.email_dlq_queue,
        document_queue=rabbitmq_resources.provided.document_queue,
        document_dlq_queue=rabbitmq_resources.provided.document_dlq_queue,
        logger=logger,
    )

    handlers = providers.Factory(
        Handlers,
        logger=logger,
    )

    rabbitmq_consumers = providers.Resource(
        init_rabbitmq_consumers,
        rabbitmq=rabbitmq,
        handlers=handlers,
    )

    auth_service = providers.Factory(
        AuthService,
        repository=user_repository,
        redis=redis_client,
        settings=settings,
        logger=logger,
    )

    embedding_manager = providers.Singleton(
      EmbeddingManager,
      model_name="all-MiniLM-L6-v2",
      logger=logger,
    )

    langchain_embeddings = providers.Singleton(
      SentenceTransformerEmbeddings,
      model=embedding_manager.provided.model,
    )

    vector_store = providers.Resource(
      VectorStore,
      logger=logger,
      collection_name="pdf_store",
    )

    ingest_pipeline_service = providers.Factory(
      IngestPipeline,
      logger=logger,
      embedding_manager=embedding_manager,
      semantic_embeddings=langchain_embeddings,
      vector_store=vector_store,
    )

    document_repository = providers.Factory(
        DocumentRepository,
        session_factory=async_session_factory,
        logger=logger,
    )

    document_service = providers.Factory(
        DocumentService,
        repository=document_repository,
        logger=logger,
        ingest_pipeline=ingest_pipeline_service,
        vector_store=vector_store,
    )
