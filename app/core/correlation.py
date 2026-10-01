import asyncio
from collections.abc import Awaitable, Coroutine, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any
from uuid import uuid4

import sentry_sdk

CORRELATION_HEADER = "X-Correlation-ID"
CORRELATION_AMQP_HEADER = "x-correlation-id"

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")


def get_correlation_id() -> str:
    return _correlation_id.get()


def set_correlation_id(value: str) -> Token[str]:
    return _correlation_id.set(value)


def reset_correlation_id(token: Token[str]) -> None:
    _correlation_id.reset(token)


def new_correlation_id() -> str:
    return uuid4().hex


def read_correlation_id(headers: Mapping[str, Any] | None) -> str | None:
    """Read a correlation id from AMQP message headers, if present."""
    if not headers:
        return None
    raw = headers.get(CORRELATION_AMQP_HEADER)
    if isinstance(raw, bytes):
        raw = raw.decode()
    if not raw or not isinstance(raw, str):
        return None
    value = raw.strip()
    return value or None


@contextmanager
def correlation_id_scope(value: str | None = None) -> Iterator[str]:
    """Bind a correlation id (given or newly generated), then restore the previous one."""
    cid = value or new_correlation_id()
    token = set_correlation_id(cid)
    try:
        yield cid
    finally:
        reset_correlation_id(token)


def spawn_task(
    coro: Coroutine[Any, Any, Any] | Awaitable[Any],
    *,
    name: str | None = None,
) -> asyncio.Task[Any]:
    """Schedule a background task that keeps the current correlation id."""
    cid = get_correlation_id()

    async def _runner() -> Any:
        token = set_correlation_id(cid)
        try:
            return await coro
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            raise
        finally:
            reset_correlation_id(token)

    return asyncio.create_task(_runner(), name=name)
