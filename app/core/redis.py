from logging import Logger

from redis.asyncio import Redis


class RedisClient:
    """Thin async wrapper around a Redis connection for app-level use."""

    def __init__(self, redis: Redis, logger: Logger):
        self._redis = redis
        self._logger = logger

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        self._logger.debug("Redis SET key=%s ttl=%s", key, ttl)
        await self._redis.set(key, value, ex=ttl)

    async def get(self, key: str) -> str | None:
        self._logger.debug("Redis GET key=%s", key)
        return await self._redis.get(key)

    async def delete(self, key: str) -> None:
        self._logger.debug("Redis DELETE key=%s", key)
        await self._redis.delete(key)

    async def exists(self, key: str) -> bool:
        self._logger.debug("Redis EXISTS key=%s", key)
        return await self._redis.exists(key) == 1
