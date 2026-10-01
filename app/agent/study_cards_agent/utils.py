import re

from app.agent.study_cards_agent.schema import ChapterResult, Critique
from app.core.elasticsearch_schema import IndexedRecord
from app.memory.schema import Memory


def format_source_record(record: IndexedRecord) -> str:
    """Label a chapter chunk with chapter/page metadata for citations."""
    meta = record.metadata or {}
    labels: list[str] = []

    chapter_number = meta.get("chapter_number")
    chapter = meta.get("chapter") or meta.get("chapter_key")
    page = meta.get("page")

    if chapter_number is not None and chapter:
        title = str(chapter).strip()
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
        return record.content
    return f"[{' | '.join(labels)}]\n{record.content}"


def format_source_content(records: list[IndexedRecord]) -> str:
    return "\n\n".join(format_source_record(record) for record in records)


def format_tavily_results(hits: list[dict] | None, *, limit: int = 5) -> str:
    if not hits:
        return ""
    link_lines: list[str] = []
    for hit in hits[:limit]:
        if not isinstance(hit, dict):
            continue
        title = (hit.get("title") or "").strip() or "Resource"
        url = (hit.get("url") or "").strip()
        content = (hit.get("content") or "").strip()
        if not url:
            continue
        link_lines.append(f"- [{title}]: {url} -- {content}")
    return "\n".join(link_lines)


def critique_comment(
    critique: dict[str, Critique] | None, chapter_key: str
) -> str | None:
    if critique is None:
        return None
    entry = critique.get(chapter_key)
    if entry is None or entry.status != "rejected":
        return None
    return (
        entry.comment
        or "Rejected without detailed feedback. Revise against all "
        "ChapterResult requirements and quality rules."
    )


def previous_draft(
    generated_chapters: dict[str, ChapterResult], chapter_key: str
) -> str | None:
    chapter = generated_chapters.get(chapter_key)
    if chapter is None:
        return None
    return chapter.model_dump_json()


def extract_learning_preferences(
    memories: list[Memory] | list[dict] | None,
) -> list[str] | None:
    if not memories:
        return None
    prefs: list[str] = []
    for memory in memories:
        if isinstance(memory, dict):
            content = (memory.get("content") or "").strip()
        else:
            content = (getattr(memory, "content", None) or "").strip()
        if content:
            prefs.append(content)
    return prefs or None
