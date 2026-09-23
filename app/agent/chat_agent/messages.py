def format_history(
    messages: list | None,
    *,
    limit: int | None = None,
    truncate_ai: int | None = None,
) -> str:
    """Format completed turns as User:/Assistant: text. Drops a trailing human query."""
    msgs = list(messages or [])
    if msgs and getattr(msgs[-1], "type", None) == "human":
        msgs = msgs[:-1]
    if limit is not None:
        msgs = msgs[-(limit * 2):]

    parts: list[str] = []
    user: str | None = None
    for message in msgs:
        if message.type == "human":
            user = str(message.content)
        elif message.type == "ai" and user is not None:
            assistant = str(message.content)
            if truncate_ai is not None:
                assistant = assistant[:truncate_ai]
            parts.append(f"User: {user}\nAssistant: {assistant}")
            user = None

    return "\n\n".join(parts)
