from app.core.elasticsearch_schema import FusedResult, IndexedRecord
from app.core.semantic_cache import CacheHit


def format_history(
    messages: list | None,
    *,
    limit: int | None = None,
) -> str:
    """Format completed turns as User:/Assistant: text. Drops a trailing human query."""
    msgs = list(messages or [])
    if msgs and getattr(msgs[-1], "type", None) == "human":
        msgs = msgs[:-1]
    if limit is not None:
        msgs = msgs[-(limit * 2) :]

    parts: list[str] = []
    user: str | None = None
    for message in msgs:
        if message.type == "human":
            user = str(message.content)
        elif message.type == "ai" and user is not None:
            assistant = str(message.content)
            parts.append(f"User: {user}\nAssistant: {assistant}")
            user = None

    return "\n\n".join(parts)


def format_rag_chunk(result: FusedResult) -> str:
    meta = result.document.metadata or {}
    labels: list[str] = []

    chapter_number = meta.get("chapter_number")
    chapter = meta.get("chapter") or meta.get("chapter_key")
    page = meta.get("page")

    if chapter_number is not None and chapter:
        labels.append(f"Chapter {chapter_number}: {chapter}")
    elif chapter_number is not None:
        labels.append(f"Chapter {chapter_number}")
    elif chapter:
        labels.append(f"Chapter: {chapter}")

    if page is not None:
        labels.append(f"Page {page}")

    if not labels:
        return result.document.content
    return f"[{' | '.join(labels)}]\n{result.document.content}"


def format_rag_context(rag_documents: list[FusedResult]) -> str:
    return "\n\n".join(format_rag_chunk(result) for result in rag_documents)


def cache_hit_to_fused(hit: CacheHit) -> FusedResult:
    return FusedResult(
        document=IndexedRecord(
            content=hit.context,
            metadata={
                "document_id": hit.document_id,
                "id": ",".join(hit.chunk_ids),
            },
            embedding=[],
        ),
        score=max(0.0, 1.0 - hit.distance),
    )
