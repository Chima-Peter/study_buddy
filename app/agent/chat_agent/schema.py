from typing import Literal

from pydantic import BaseModel, Field

SUMMARY_EVERY = 5
SUMMARY_MAX_CHARS = 1500


class DeciderResponse(BaseModel):
    decision: Literal["rag", "history", "both", "none"] = Field(
        description=(
            "rag: retrieve study documents only; "
            "history: use conversation memory only; "
            "both: retrieve documents and conversation memory; "
            "none: general knowledge question, no document/history retrieval needed"
        ),
    )
    retrieve_memory: bool = Field(
        description=(
            "True when answering needs stored facts about the user "
            "(personal: life outside school; study: topics, courses, learning style). "
            "False for greetings/small talk, pure document lookup, general "
            "knowledge, or chat that does not depend on stored student facts. "
            "Name and gender come from the user profile automatically."
        ),
    )


class RewriteQueryResponse(BaseModel):
    """Structured rewrite for document and/or memory retrieval."""

    rag_query: str | None = Field(
        default=None,
        description=(
            "Rewritten query for hybrid document search. "
            "Null when document retrieval is not needed."
        ),
    )
    chapters: list[str] | None = Field(
        default=None,
        description=(
            "Section keys from the provided available section keys that the "
            "user explicitly scoped the question to "
            "(e.g. 'chapter_1', 'chapter_2'). "
            "Copy keys exactly from the available list. "
            "Empty or null when no specific sections are mentioned or when "
            "document retrieval is not needed."
        ),
    )
    memory_query: str | None = Field(
        default=None,
        description=(
            "One partial statement for the memory index, phrased like stored "
            "memories starting with 'The user'. Combine needed aspects into "
            "a single phrase, e.g. 'The user is interested in and prefers'. "
            "Null when memory retrieval is not needed. "
            "Do not include name/gender lookups; those come from profile."
        ),
    )
