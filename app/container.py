from collections.abc import AsyncIterator, Iterator

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

from app.config import Settings


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


class Container(containers.DeclarativeContainer):
    """Application dependency container."""

    wiring_config = containers.WiringConfiguration(
        packages=["app"],
    )

    settings = providers.Singleton(Settings)

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
