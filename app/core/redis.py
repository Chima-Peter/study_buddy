from redis.asyncio import Redis


class RedisClient:
    """Thin async wrapper around a Redis connection for app-level use."""

    def __init__(self, redis: Redis):
        self._redis = redis

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        await self._redis.set(key, value, ex=ttl)

    async def get(self, key: str) -> str | None:
        return await self._redis.get(key)

    async def delete(self, key: str) -> None:
        await self._redis.delete(key)

    async def exists(self, key: str) -> bool:
        return await self._redis.exists(key) == 1
