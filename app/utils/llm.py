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
