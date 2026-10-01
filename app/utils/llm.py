import asyncio
from collections.abc import Awaitable, Callable
from logging import Logger
from typing import TypeVar

T = TypeVar("T")

LLM_RATE_LIMIT_MAX_RETRIES = 3
LLM_RATE_LIMIT_DELAY_SECONDS = 10.0


def is_rate_limit_error(exc: BaseException) -> bool:
    """True when a Gemini/LangChain call failed due to HTTP 429 / quota exhaustion."""
    current: BaseException | None = exc
    while current is not None:
        if getattr(current, "code", None) == 429:
            return True
        if getattr(current, "status", None) == "RESOURCE_EXHAUSTED":
            return True
        current = current.__cause__ or current.__context__
    text = str(exc)
    return "429" in text or "RESOURCE_EXHAUSTED" in text


async def with_rate_limit_retry(
    call: Callable[[], Awaitable[T]],
    *,
    logger: Logger,
    label: str,
    max_retries: int = LLM_RATE_LIMIT_MAX_RETRIES,
    delay_seconds: float = LLM_RATE_LIMIT_DELAY_SECONDS,
) -> T:
    """Run an async LLM call, sleeping and retrying on rate-limit errors."""
    attempt = 0
    while True:
        try:
            return await call()
        except Exception as e:
            if not is_rate_limit_error(e):
                raise
            attempt += 1
            if attempt > max_retries:
                logger.warning(
                    "Rate limit retries exhausted (%s/%s) for %s",
                    max_retries,
                    max_retries,
                    label,
                )
                raise
            delay = delay_seconds * attempt
            logger.warning(
                "Rate limit on %s; retry %s/%s in %.0fs",
                label,
                attempt,
                max_retries,
                delay,
            )
            await asyncio.sleep(delay)
