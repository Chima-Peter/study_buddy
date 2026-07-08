from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass

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
from app.core.rabbitmq import RabbitMQ
from app.core.redis import RedisClient
from app.logging_config import init_logging


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
    document_queue: aio_pika.Queue


async def init_async_rabbitmq_queue(channel: aio_pika.Channel, queue_name: str) -> aio_pika.Queue:
    queue = await channel.declare_queue(name=queue_name, durable=True, arguments={"x-queue-type": "quorum"})
    return queue


async def init_async_rabbitmq(rabbitmq_url: str) -> AsyncIterator[RabbitMQResources]:
    connection = await aio_pika.connect_robust(rabbitmq_url)
    channel = await connection.channel(
        publisher_confirms=True,
        on_return_raises=True,
    )
    await channel.set_qos(prefetch_count=10)

    email_queue = await init_async_rabbitmq_queue(channel, "mail_queue")
    document_queue = await init_async_rabbitmq_queue(channel, "document_queue")

    try:
        yield RabbitMQResources(
            channel=channel,
            email_queue=email_queue,
            document_queue=document_queue,
        )
    finally:
        await channel.close()
        await connection.close()


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
        document_queue=rabbitmq_resources.provided.document_queue,
        logger=logger,
    )

    auth_service = providers.Factory(
        AuthService,
        repository=user_repository,
        redis=redis_client,
        settings=settings,
        logger=logger,
    )
