from app.core.elasticsearch_schema import FusedResult


def _format_rag_chunk(result: FusedResult) -> str:
    meta = result.document.metadata or {}
    labels: list[str] = []

    chapter_number = meta.get("chapter_number")
    chapter = meta.get("chapter") or meta.get("chapter_key")
    page = meta.get("page")

    if chapter_number is not None:
        labels.append(f"Chapter {chapter_number}")
    elif chapter:
        labels.append(f"Chapter: {chapter}")

    if page is not None:
        labels.append(f"Page {page}")

    if not labels:
        return result.document.content
    return f"[{' | '.join(labels)}]\n{result.document.content}"


def format_rag_context(rag_documents: list[FusedResult]) -> str:
    return "\n\n".join(_format_rag_chunk(result) for result in rag_documents)
