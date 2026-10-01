import re

from app.core.elasticsearch_schema import FusedResult, IndexedRecord
from app.core.semantic_cache import CacheHit
from app.rag.schema import normalize_chapter_key

_CH_ABBREV_RE = re.compile(
    r"^ch(?:apter)?\.?\s*([0-9]+|[ivxlcdm]+)\b(.*)$",
    re.IGNORECASE,
)


def coerce_chapter_mention(raw: str) -> str:
    text = (raw or "").strip()
    match = _CH_ABBREV_RE.match(text)
    if match:
        rest = (match.group(2) or "").strip(" :.-—–")
        base = f"chapter {match.group(1)}"
        return f"{base}: {rest}" if rest else base
    return text


def match_section_keys(
    mentions: list[str] | None,
    available: list[str],
) -> list[str] | None:
    """Map model mentions onto chapter_splitter section keys only."""
    if not mentions or not available:
        return None

    by_lower = {key.lower(): key for key in available}
    matched: list[str] = []
    seen: set[str] = set()

    def _add(key: str) -> None:
        if key not in seen:
            seen.add(key)
            matched.append(key)

    for raw in mentions:
        text = (raw or "").strip()
        if not text:
            continue

        exact = by_lower.get(text.lower())
        if exact is not None:
            _add(exact)
            continue

        normalized = normalize_chapter_key(coerce_chapter_mention(text))
        if normalized in by_lower:
            _add(by_lower[normalized])

    return matched or None


def flatten_section_keys(
    document_id: str | None,
    document_sections: dict[str, list[str]],
) -> list[str]:
    if not document_id:
        return []
    keys: list[str] = []
    seen: set[str] = set()
    for key in document_sections.get(document_id, []):
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


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
        title = str(chapter).strip()
        # Avoid "Chapter 1: 1 Python Primer"
        stripped = re.sub(
            rf"^(?:chapter\s+)?{int(chapter_number)}(?:\.\d+)*[.:\s—–-]*",
            "",
            title,
            flags=re.IGNORECASE,
        ).strip()
        label_title = stripped or title
        labels.append(f"Chapter {chapter_number}: {label_title}")
    elif chapter_number is not None:
        labels.append(f"Chapter {chapter_number}")
    elif chapter:
        labels.append(str(chapter))

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
