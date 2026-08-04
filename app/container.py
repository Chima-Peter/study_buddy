import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from logging import Logger

import aio_pika
from app.core.mappings import DOCUMENTS_INDEX_MAPPINGS, USER_MEMORIES_INDEX_MAPPINGS
from langchain_google_genai import ChatGoogleGenerativeAI
import redis
from dependency_injector import containers, providers
from redis.asyncio import Redis
from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from sqlalchemy.orm import sessionmaker
from supabase import AsyncClient, create_async_client, create_client, Client
from elasticsearch import AsyncElasticsearch

from app.agent.chat_agent.graph import AgentGraph
from app.authentication.repository import UserRepository
from app.authentication.services import AuthService
from app.config import Settings
from app.core.elasticsearch import Elasticsearch
from app.core.elasticsearch_schema import FusedResult, IndexedRecord
from app.core.embedding import EmbeddingManager
from app.core.rabbitmq import RabbitMQ, RabbitMQConsumer, retry_queue_name
from app.core.redis import RedisClient
from app.core.supabase import Supabase
from app.handlers.index import Handlers
from app.logging_config import init_logging
from app.rag.chapter_splitter import ChapterSplitter
from app.rag.ingest_pipeline import IngestPipeline
from app.rag.rag_retriever import RAGRetriever
from app.memory.repository import MemoryRepository
from app.memory.service import MemoryService
from app.system.conversation.repository import ConversationRepository
from app.system.document.repository import DocumentRepository
from app.system.chat.repository import ChatRepository
from app.system.notification.repository import NotificationRepository
from app.system.chat.schema import ChatResponse
from app.system.chat.service import ChatService
from app.system.conversation.service import ConversationService
from app.system.document.service import DocumentService
from app.system.notification.service import NotificationService


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

async def init_checkpointer(database_url: str) -> AsyncIterator[AsyncPostgresSaver]:
    checkpoint_pool = AsyncConnectionPool(
        conninfo=database_url,
        max_size=5,
        min_size=1,
        open=False,
        # setup() runs CREATE INDEX CONCURRENTLY, which cannot run in a transaction.
        kwargs={"autocommit": True, "prepare_threshold": 0},
    )
    await checkpoint_pool.open()
    # Agent state types must be allowlisted or deserialization breaks on future versions.
    serde = JsonPlusSerializer(
        allowed_msgpack_modules=(ChatResponse, FusedResult, IndexedRecord),
    )
    checkpointer = AsyncPostgresSaver(checkpoint_pool, serde=serde)
    try:
        await checkpointer.setup()
        yield checkpointer
    finally:
        await checkpoint_pool.close()


def init_sync_redis(redis_url: str) -> Iterator[redis.Redis]:
    """Create the sync Redis client and close it on shutdown."""
    client: redis.Redis = redis.from_url(redis_url, decode_responses=True)
    try:
        yield client
    finally:
        client.close()


async def init_async_redis() -> AsyncIterator[Redis]:
    """Create the async Redis client and close it on shutdown."""
    client = Redis(
        host="localhost",
        port=6379,
        socket_timeout=10,
        decode_responses=True,
    )
    try:
        yield client
    finally:
        await client.aclose()


@dataclass
class RabbitMQResources:
    channel: aio_pika.Channel
    llm_channel: aio_pika.Channel
    email_queue: aio_pika.Queue
    email_dlq_queue: aio_pika.Queue
    document_queue: aio_pika.Queue
    document_dlq_queue: aio_pika.Queue
    memory_extract_queue: aio_pika.Queue
    memory_extract_dlq_queue: aio_pika.Queue
    retry_queues: dict[str, dict[int, aio_pika.Queue]]


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


async def init_retry_queues(
    channel: aio_pika.Channel,
    *,
    target_queue: str,
    delay_tiers_ms: list[int],
) -> dict[int, aio_pika.Queue]:
    """Classic TTL queues that dead-letter back onto the target main queue."""
    queues: dict[int, aio_pika.Queue] = {}
    for delay_ms in delay_tiers_ms:
        queues[delay_ms] = await channel.declare_queue(
            name=retry_queue_name(target_queue, delay_ms),
            durable=True,
            arguments={
                "x-message-ttl": delay_ms,
                "x-dead-letter-exchange": "",
                "x-dead-letter-routing-key": target_queue,
                "x-max-length-bytes": MAX_QUEUE_BYTES,
            },
        )
    return queues


async def init_async_rabbitmq(
    rabbitmq_url: str,
    logger: Logger,
    max_retries: int,
    retry_base_ms: int,
    retry_max_ms: int,
) -> AsyncIterator[RabbitMQResources]:
    from app.core.rabbitmq import retry_delay_tiers_ms

    try:
        connection = await aio_pika.connect_robust(rabbitmq_url)
        channel = await connection.channel(
            publisher_confirms=True,
            on_return_raises=True,
        )
        llm_channel = await connection.channel(
            publisher_confirms=True,
            on_return_raises=True,
        )
    except Exception as e:
        logger.exception("Error connecting to RabbitMQ")
        raise e
    await channel.set_qos(prefetch_count=5)
    await llm_channel.set_qos(prefetch_count=20)

    email_queue, email_dlq_queue = await init_async_rabbitmq_queue(channel, "mail_queue")
    document_queue, document_dlq_queue = await init_async_rabbitmq_queue(
        channel, "document_queue"
    )
    # Declare on llm_channel so consume uses that channel's prefetch=20.
    memory_extract_queue, memory_extract_dlq_queue = await init_async_rabbitmq_queue(
        llm_channel, "memory_extract_queue"
    )

    tiers = retry_delay_tiers_ms(retry_base_ms, retry_max_ms, max_retries)
    retry_targets = ("document_queue", "memory_extract_queue")
    retry_queues: dict[str, dict[int, aio_pika.Queue]] = {}
    for target in retry_targets:
        retry_queues[target] = await init_retry_queues(
            channel,
            target_queue=target,
            delay_tiers_ms=tiers,
        )
        logger.info(
            "Declared retry TTL queues target=%s delays_ms=%s",
            target,
            tiers,
        )

    try:
        yield RabbitMQResources(
            channel=channel,
            llm_channel=llm_channel,
            email_queue=email_queue,
            email_dlq_queue=email_dlq_queue,
            document_queue=document_queue,
            document_dlq_queue=document_dlq_queue,
            memory_extract_queue=memory_extract_queue,
            memory_extract_dlq_queue=memory_extract_dlq_queue,
            retry_queues=retry_queues,
        )
    finally:
        for ch in (llm_channel, channel):
            try:
                await asyncio.wait_for(ch.close(), timeout=2.0)
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
        memory_extract_callback=handlers.handle_memory_extract,
        mail_dlq_callback=handlers.handle_mail_dead_letter_queue,
        document_dlq_callback=handlers.handle_document_dead_letter_queue,
        memory_extract_dlq_callback=handlers.handle_memory_extract_dead_letter_queue,
    )
    try:
        yield active_consumers
    finally:
        await rabbitmq.stop_consumers(active_consumers)


def init_supabase(supabase_url: str, supabase_key: str) -> Client:
    return create_client(
        supabase_url=supabase_url,
        supabase_key=supabase_key,
    )


async def init_async_supabase(supabase_url: str, supabase_key: str) -> AsyncClient:
    return await create_async_client(
        supabase_url=supabase_url,
        supabase_key=supabase_key,
    )


async def init_async_elasticsearch(
    elasticsearch_url: str,
) -> AsyncIterator[AsyncElasticsearch]:
    es = AsyncElasticsearch(
        elasticsearch_url,
        verify_certs=False,
        headers={
            "accept": "application/vnd.elasticsearch+json; compatible-with=8",
            "content-type": "application/vnd.elasticsearch+json; compatible-with=8",
        },
    )
    if not await es.indices.exists(index="documents"):
        await es.indices.create(
            index="documents",
            mappings=DOCUMENTS_INDEX_MAPPINGS,
        )
    if not await es.indices.exists(index="user_memories"):
        await es.indices.create(
            index="user_memories",
            mappings=USER_MEMORIES_INDEX_MAPPINGS,
        )
    try:
        yield es
    finally:
        await es.close()


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

    async_elasticsearch_resource = providers.Resource(
        init_async_elasticsearch,
        elasticsearch_url=settings.provided.elasticsearch_url,
    )

    elasticsearch = providers.Singleton(
        Elasticsearch,
        elasticsearch=async_elasticsearch_resource,
        logger=logger,
    )

    async_session_factory = providers.Singleton(
        init_async_session_factory,
        engine=async_engine,
    )

    sync_supabase_client = providers.Resource(
        init_supabase,
        supabase_url=settings.provided.supabase_url,
        supabase_key=settings.provided.supabase_key,
    )

    async_supabase_client = providers.Resource(
        init_async_supabase,
        supabase_url=settings.provided.supabase_url,
        supabase_key=settings.provided.supabase_key,
    )

    async_supabase = providers.Factory(
        Supabase,
        supabase=async_supabase_client,
        logger=logger,
    )

    rabbitmq_resources = providers.Resource(
        init_async_rabbitmq,
        rabbitmq_url=settings.provided.rabbitmq_url,
        logger=logger,
        max_retries=settings.provided.rabbitmq_max_retries,
        retry_base_ms=settings.provided.rabbitmq_retry_base_ms,
        retry_max_ms=settings.provided.rabbitmq_retry_max_ms,
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
        llm_channel=rabbitmq_resources.provided.llm_channel,
        email_queue=rabbitmq_resources.provided.email_queue,
        email_dlq_queue=rabbitmq_resources.provided.email_dlq_queue,
        document_queue=rabbitmq_resources.provided.document_queue,
        document_dlq_queue=rabbitmq_resources.provided.document_dlq_queue,
        memory_extract_queue=rabbitmq_resources.provided.memory_extract_queue,
        memory_extract_dlq_queue=rabbitmq_resources.provided.memory_extract_dlq_queue,
        retry_queues=rabbitmq_resources.provided.retry_queues,
        max_retries=settings.provided.rabbitmq_max_retries,
        retry_base_ms=settings.provided.rabbitmq_retry_base_ms,
        retry_max_ms=settings.provided.rabbitmq_retry_max_ms,
        logger=logger,
    )

    auth_service = providers.Factory(
        AuthService,
        repository=user_repository,
        redis=redis_client,
        settings=settings,
        logger=logger,
        elasticsearch=elasticsearch,
        supabase=async_supabase,
    )

    embedding_manager = providers.Singleton(
        EmbeddingManager,
        model_name="all-MiniLM-L6-v2",
        logger=logger,
    )

    ingest_pipeline_service = providers.Factory(
        IngestPipeline,
        logger=logger,
        embedding_manager=embedding_manager,
        supabase=async_supabase,
        unstructured_api_url=settings.provided.unstructured_api_url,
        unstructured_api_key=settings.provided.unstructured_api_key,
    )

    chapter_splitter = providers.Factory(
        ChapterSplitter,
        logger=logger,
        unstructured_api_url=settings.provided.unstructured_api_url,
        unstructured_api_key=settings.provided.unstructured_api_key,
    )

    document_repository = providers.Factory(
        DocumentRepository,
        session_factory=async_session_factory,
        logger=logger,
    )

    chat_repository = providers.Factory(
        ChatRepository,
        session_factory=async_session_factory,
        logger=logger,
    )

    conversation_repository = providers.Factory(
        ConversationRepository,
        session_factory=async_session_factory,
        logger=logger,
    )

    document_service = providers.Factory(
        DocumentService,
        repository=document_repository,
        logger=logger,
        ingest_pipeline=ingest_pipeline_service,
        rabbitmq=rabbitmq,
        elasticsearch=elasticsearch,
        supabase=async_supabase,
    )

    chat_model = providers.Singleton(
        ChatGoogleGenerativeAI,
        model=settings.provided.chat_model_name,
        temperature=0.7,
        max_tokens=4096,
        max_retries=3,
        google_api_key=settings.provided.google_api_key,
    )

    summarizer_model = providers.Singleton(
        ChatGoogleGenerativeAI,
        model=settings.provided.summarizer_model_name,
        temperature=0.2,
        max_tokens=1024,
        max_retries=3,
        google_api_key=settings.provided.google_api_key,
    )

    query_model = providers.Singleton(
        ChatGoogleGenerativeAI,
        model=settings.provided.query_model_name,
        temperature=0.2,
        max_tokens=512,
        max_retries=3,
        google_api_key=settings.provided.google_api_key,
    )

    rag_retriever = providers.Factory(
        RAGRetriever,
        elasticsearch=elasticsearch,
        embedding_manager=embedding_manager,
        logger=logger,
    )

    chat_service = providers.Factory(
        ChatService,
        repository=chat_repository,
        logger=logger,
    )

    memory_repository = providers.Factory(
        MemoryRepository,
        logger=logger,
        elasticsearch=elasticsearch,
    )

    memory_service = providers.Factory(
        MemoryService,
        logger=logger,
        model=summarizer_model,
        repository=memory_repository,
        embedding_manager=embedding_manager,
    )

    conversation_service = providers.Factory(
        ConversationService,
        repository=conversation_repository,
        logger=logger,
    )

    notification_repository = providers.Factory(
        NotificationRepository,
        session_factory=async_session_factory,
        logger=logger,
    )

    notification_service = providers.Factory(
        NotificationService,
        repository=notification_repository,
        logger=logger,
    )

    handlers = providers.Factory(
        Handlers,
        logger=logger,
        ingest_pipeline=ingest_pipeline_service,
        chapter_splitter=chapter_splitter,
        supabase=async_supabase,
        document_service=document_service,
        embedding_manager=embedding_manager,
        elasticsearch=elasticsearch,
        rabbitmq=rabbitmq,
        redis=redis_client,
        notification_service=notification_service,
        memory_service=memory_service,
    )

    rabbitmq_consumers = providers.Resource(
        init_rabbitmq_consumers,
        rabbitmq=rabbitmq,
        handlers=handlers,
    )

    checkpoint_saver = providers.Resource(
        init_checkpointer,
        database_url=settings.provided.checkpoint_database_url,
    )

    agent_graph = providers.Singleton(
        AgentGraph,
        retriever=rag_retriever,
        memory_service=memory_service,
        conversation_service=conversation_service,
        document_service=document_service,
        chat_service=chat_service,
        user_repository=user_repository,
        logger=logger,
        chat_model=chat_model,
        query_model=query_model,
        summarizer_model=summarizer_model,
        checkpointer=checkpoint_saver,
        rabbitmq=rabbitmq,
    )
