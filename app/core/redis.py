import json
from logging import Logger

import uuid_utils
from redis.asyncio import Redis

from app.system.notification.schema import EventPayload

CONNECTION_TTL_SECONDS = 5 * 60
CONNECTION_COUNT_TTL_SECONDS = 24 * 60 * 60
CHAT_LOCK_TTL_SECONDS = 5 * 60
SSE_PING_INTERVAL_MS = 120_000

_RELEASE_CHAT_LOCK_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
  return redis.call("del", KEYS[1])
end
return 0
"""


class RedisClient:
    """Thin async wrapper around a Redis connection for app-level use."""

    def __init__(self, redis: Redis, logger: Logger):
        self._redis = redis
        self._logger = logger

    @staticmethod
    def _connection_key(user_id: str) -> str:
        return f"connection_id:{user_id}"

    @staticmethod
    def _connection_count_key(user_id: str) -> str:
        return f"connection_count:{user_id}"

    @staticmethod
    def _chat_lock_key(user_id: str, conversation_id: str) -> str:
        return f"chat_lock:{user_id}:{conversation_id}"

    @staticmethod
    def _stream_key(stream_id: str) -> str:
        if stream_id.startswith("stream_"):
            return stream_id
        return f"stream_{stream_id}"

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        self._logger.debug("Redis SET key=%s ttl=%s", key, ttl)
        await self._redis.set(key, value, ex=ttl)

    async def set_nx(
        self,
        key: str,
        value: str,
        *,
        ttl: int,
    ) -> bool:
        """SET key only if it does not exist. Returns True if this caller owns it."""
        self._logger.debug("Redis SET NX key=%s ttl=%s", key, ttl)
        result = await self._redis.set(key, value, nx=True, ex=ttl)
        return result is True

    async def get(self, key: str) -> str | None:
        self._logger.debug("Redis GET key=%s", key)
        return await self._redis.get(key)

    async def delete(self, key: str) -> None:
        self._logger.debug("Redis DELETE key=%s", key)
        await self._redis.delete(key)

    async def exists(self, key: str) -> bool:
        self._logger.debug("Redis EXISTS key=%s", key)
        return await self._redis.exists(key) == 1

    async def extend_ttl(self, key: str, ttl: int) -> None:
        self._logger.debug("Redis EXTEND TTL key=%s ttl=%s", key, ttl)
        await self._redis.expire(key, ttl)

    async def remove_ttl(self, key: str) -> None:
        self._logger.debug("Redis REMOVE TTL key=%s", key)
        await self._redis.persist(key)

    async def acquire_chat_lock(
        self,
        user_id: str,
        conversation_id: str,
    ) -> str | None:
        """Acquire a per-conversation lock via SET NX. Returns token or None."""
        token = str(uuid_utils.uuid7())
        key = self._chat_lock_key(user_id, conversation_id)
        acquired = await self.set_nx(key, token, ttl=CHAT_LOCK_TTL_SECONDS)
        if not acquired:
            self._logger.info(
                "Chat lock busy user_id=%s conversation_id=%s",
                user_id,
                conversation_id,
            )
            return None
        self._logger.debug(
            "Chat lock acquired user_id=%s conversation_id=%s",
            user_id,
            conversation_id,
        )
        return token

    async def release_chat_lock(
        self,
        user_id: str,
        conversation_id: str,
        token: str,
    ) -> None:
        """Release lock only if ``token`` still owns it."""
        key = self._chat_lock_key(user_id, conversation_id)
        try:
            await self._redis.eval(_RELEASE_CHAT_LOCK_LUA, 1, key, token)
            self._logger.debug(
                "Chat lock released user_id=%s conversation_id=%s",
                user_id,
                conversation_id,
            )
        except Exception:
            self._logger.exception(
                "Chat lock release failed user_id=%s conversation_id=%s",
                user_id,
                conversation_id,
            )

    async def create_stream(self, user_id: str) -> str:
        stream_id = str(uuid_utils.uuid7())[:8]
        stream_name = self._stream_key(stream_id)
        await self.set(self._connection_key(user_id), stream_name)
        self._logger.debug("Redis CREATE STREAM key=%s", stream_name)
        await self._redis.xadd(
            stream_name,
            {
                "type": "ping",
                "data": "{}",
            },
        )
        return stream_name

    async def read_stream(
        self,
        stream_name: str,
        last_event_id: str = "0",
        *,
        count: int = 10,
        block_ms: int = SSE_PING_INTERVAL_MS,
    ) -> list[tuple[str, dict[str, str]]]:
        self._logger.debug(
            "Redis READ STREAM key=%s last_event_id=%s",
            stream_name,
            last_event_id,
        )
        events = await self._redis.xread(
            streams={stream_name: last_event_id},
            count=count,
            block=block_ms,
        )
        if not events:
            return []

        messages: list[tuple[str, dict[str, str]]] = []
        for _name, entries in events:
            for message_id, fields in entries:
                messages.append((message_id, fields))
        self._logger.debug("events=%s", messages)
        return messages

    async def write_stream(self, stream_name: str, event: EventPayload) -> str:
        self._logger.debug(
            "Redis WRITE STREAM key=%s event=%s", stream_name, event)
        message_id = await self._redis.xadd(
            stream_name,
            {
                "type": event.type,
                "data": json.dumps(event.data),
            },
        )
        self._logger.debug("event=%s", message_id)
        return message_id

    async def publish_to_user(
        self, user_id: str, event: EventPayload
    ) -> str | None:
        stream_name = await self.get(self._connection_key(user_id))
        if not stream_name:
            self._logger.debug(
                "No active stream for user_id=%s; skip publish type=%s",
                user_id,
                event.type,
            )
            return None
        return await self.write_stream(self._stream_key(stream_name), event)

    async def delete_message_from_stream(
        self, stream_name: str, message_id: str
    ) -> None:
        self._logger.debug(
            "Redis DELETE MESSAGE FROM STREAM key=%s message_id=%s",
            stream_name,
            message_id,
        )
        await self._redis.xdel(stream_name, message_id)
        self._logger.debug("message_id=%s deleted", message_id)

    async def expire_connection(self, user_id: str) -> None:
        connection_key = self._connection_key(user_id)
        stream_name = await self.get(connection_key)
        await self.extend_ttl(connection_key, CONNECTION_TTL_SECONDS)
        if stream_name:
            await self.extend_ttl(
                self._stream_key(stream_name),
                CONNECTION_TTL_SECONDS,
            )

    async def orchestrate_stream(self, user_id: str) -> str:
        connection_key = self._connection_key(user_id)
        stream_name = await self.get(connection_key)
        if stream_name:
            stream_name = self._stream_key(stream_name)
            await self.remove_ttl(connection_key)
            await self.remove_ttl(stream_name)
            if await self.exists(stream_name):
                return stream_name
        return await self.create_stream(user_id)

    async def incr_connection_count(self, user_id: str) -> int:
        key = self._connection_count_key(user_id)
        count = await self._redis.incr(key)
        await self._redis.expire(key, CONNECTION_COUNT_TTL_SECONDS)
        return count

    async def decr_connection_count(self, user_id: str) -> int:
        key = self._connection_count_key(user_id)
        count = await self._redis.decr(key)
        if count <= 0:
            await self._redis.delete(key)
            return 0
        return count

    async def get_connection_count(self, user_id: str) -> int:
        key = self._connection_count_key(user_id)
        count = await self._redis.get(key)
        return int(count) if count else 0
