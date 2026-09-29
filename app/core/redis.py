import json
from logging import Logger
from typing import Any

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

# KEYS[1]=lock, KEYS[2]=queue, KEYS[3]=items hash
# ARGV[1]=item_id (lock token), ARGV[2]=item JSON, ARGV[3]=ttl seconds
# Returns 1 if lock acquired, 0 if enqueued.
_ARRIVAL_LUA = """
local lock = redis.call("get", KEYS[1])
redis.call("hset", KEYS[3], ARGV[1], ARGV[2])
if not lock then
  redis.call("set", KEYS[1], ARGV[1], "EX", tonumber(ARGV[3]))
  return 1
end
redis.call("rpush", KEYS[2], ARGV[1])
return 0
"""

# KEYS[1]=lock, KEYS[2]=queue, KEYS[3]=items hash
# ARGV[1]=expected lock token, ARGV[2]=ttl seconds
# Returns nil if lock released / mismatch, else next item JSON.
_COMPLETION_LUA = """
local lock = redis.call("get", KEYS[1])
if lock ~= ARGV[1] then
  return false
end

redis.call("hdel", KEYS[3], ARGV[1])

local next_id = redis.call("lpop", KEYS[2])
if not next_id then
  redis.call("del", KEYS[1])
  return false
end

redis.call("set", KEYS[1], next_id, "EX", tonumber(ARGV[2]))
local details = redis.call("hget", KEYS[3], next_id)
if not details then
  return false
end
return details
"""

# KEYS[1]=queue, KEYS[2]=items hash
# ARGV[1]=item_id
# Returns 1 if item was in the queue and hash and deleted, 0 otherwise.
_HASH_DELETE_LUA = """
if not redis.call("lpos", KEYS[1], ARGV[1]) then
  return 0
end
if redis.call("hexists", KEYS[2], ARGV[1]) == 0 then
  return 0
end
redis.call("lrem", KEYS[1], 1, ARGV[1])
return redis.call("hdel", KEYS[2], ARGV[1])
"""

# KEYS[1]=queue, KEYS[2]=items hash
# ARGV[1]=item_id, ARGV[2]=new JSON value
# Returns 1 if item was in the queue and hash and updated, 0 otherwise.
_HASH_EDIT_LUA = """
if not redis.call("lpos", KEYS[1], ARGV[1]) then
  return 0
end
if redis.call("hexists", KEYS[2], ARGV[1]) == 0 then
  return 0
end
redis.call("hset", KEYS[2], ARGV[1], ARGV[2])
return 1
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

    async def set_object(
        self,
        key: str,
        value: dict[str, Any],
        ttl: int | None = None,
    ) -> None:
        self._logger.debug("Redis SET OBJECT key=%s ttl=%s", key, ttl)
        await self._redis.set(key, json.dumps(value), ex=ttl)

    async def get_object(self, key: str) -> dict[str, Any] | None:
        self._logger.debug("Redis GET OBJECT key=%s", key)
        raw = await self._redis.get(key)
        if raw is None:
            return None
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise TypeError(f"Redis key={key} expected object, got {type(value).__name__}")
        return value

    async def set_list(
        self,
        key: str,
        value: list[Any],
        ttl: int | None = None,
    ) -> None:
        self._logger.debug("Redis SET LIST key=%s len=%s ttl=%s", key, len(value), ttl)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.delete(key)
            if value:
                pipe.rpush(key, *[json.dumps(item) for item in value])
                if ttl is not None:
                    pipe.expire(key, ttl)
            await pipe.execute()

    async def lpop(self, key: str) -> Any | None:
        """Remove and return the first (leftmost) element."""
        self._logger.debug("Redis LPOP key=%s", key)
        raw = await self._redis.lpop(key)
        if raw is None:
            return None
        return json.loads(raw)

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

    async def arrival(
        self,
        *,
        lock_key: str,
        queue_key: str,
        items_key: str,
        item_id: str,
        item: dict[str, Any],
        ttl: int = CHAT_LOCK_TTL_SECONDS,
    ) -> bool:
        """Acquire lock or enqueue. Returns True if lock acquired, False if enqueued."""
        self._logger.debug(
            "Redis ARRIVAL lock=%s queue=%s item_id=%s ttl=%s",
            lock_key,
            queue_key,
            item_id,
            ttl,
        )
        result = await self._redis.eval(
            _ARRIVAL_LUA,
            3,
            lock_key,
            queue_key,
            items_key,
            item_id,
            json.dumps(item),
            ttl,
        )
        acquired = result == 1
        self._logger.debug(
            "Redis ARRIVAL item_id=%s acquired=%s",
            item_id,
            acquired,
        )
        return acquired

    async def completion(
        self,
        *,
        lock_key: str,
        queue_key: str,
        items_key: str,
        lock_token: str,
        ttl: int = CHAT_LOCK_TTL_SECONDS,
    ) -> dict[str, Any] | None:
        """Hand off lock to next queued item, or release if queue empty.

        Returns the next item dict, or None if the lock was released / mismatched.
        """
        self._logger.debug(
            "Redis COMPLETION lock=%s queue=%s token=%s ttl=%s",
            lock_key,
            queue_key,
            lock_token,
            ttl,
        )
        result = await self._redis.eval(
            _COMPLETION_LUA,
            3,
            lock_key,
            queue_key,
            items_key,
            lock_token,
            ttl,
        )
        if result is None or result is False:
            return None
        value = json.loads(result)
        if not isinstance(value, dict):
            raise TypeError(
                f"Redis completion expected object, got {type(value).__name__}"
            )
        return value

    async def delete_hash_item(
        self,
        *,
        queue_key: str,
        items_key: str,
        item_id: str,
    ) -> bool:
        """Remove ``item_id`` from the queue and delete its hash field if both exist."""
        self._logger.debug(
            "Redis HASH DELETE queue=%s items=%s item_id=%s",
            queue_key,
            items_key,
            item_id,
        )
        result = await self._redis.eval(
            _HASH_DELETE_LUA,
            2,
            queue_key,
            items_key,
            item_id,
        )
        return result == 1

    async def edit_hash_item(
        self,
        *,
        queue_key: str,
        items_key: str,
        item_id: str,
        item: dict[str, Any],
    ) -> bool:
        """Update hash value only if ``item_id`` is in the queue and hash."""
        self._logger.debug(
            "Redis HASH EDIT queue=%s items=%s item_id=%s",
            queue_key,
            items_key,
            item_id,
        )
        result = await self._redis.eval(
            _HASH_EDIT_LUA,
            2,
            queue_key,
            items_key,
            item_id,
            json.dumps(item),
        )
        return result == 1

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
