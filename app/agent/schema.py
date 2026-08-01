from typing import Literal

from pydantic import BaseModel, Field

from app.memory.schema import MemoryRetrievalQuery

SUMMARY_EVERY = 5


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
            "True when answering needs durable student memories from the "
            "memory taxonomy (profile, preferences, goals, academic context, "
            "learning style, progress, resources, habits, or achievements). "
            "False for pure document lookup, general knowledge, or chat that "
            "does not depend on stored student facts. "
            "Name and gender are always loaded separately when missing."
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
    memory_queries: list[MemoryRetrievalQuery] = Field(
        default_factory=list,
        description=(
            "One or more memory-index searches, each with its own query, "
            "category, and type. Use multiple entries when the question "
            "touches distinct memory slices (e.g. preferences and weaknesses). "
            "Empty when memory retrieval is not needed. "
            "Do not include name/gender profile lookups; those are fetched "
            "automatically."
        ),
    )
