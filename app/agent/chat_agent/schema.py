from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

SUMMARY_EVERY = 5
SUMMARY_MAX_CHARS = 1500

NON_ACADEMIC_FALLBACK = (
    "I'm sorry, I can't help with that. This is a study buddy, "
    "not a general purpose chatbot. Please ask me something related "
    "to your studies!"
)

class DeciderResponse(BaseModel):
    decision: Literal["rag", "history", "both", "none"] = Field(
        description=(
            "rag: academic/study question answered from uploaded study "
            "documents; "
            "history: non-academic question that refers only to prior chat, "
            "or a question that can be accurately answered from prior chat "
            "turns alone; "
            "both: academic/study question needing documents and prior chat; "
            "none: non-academic/general question needing neither. "
            "Academic questions must not be classified as none just because "
            "the answer is common general knowledge—use rag to ground in "
            "study documents."
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
    is_academic_discussion: bool = Field(
        description=(
            "True only for genuine study/academic content (concepts, "
            "homework, exams, documents, courses, study plans, clarifying "
            "questions about the material). False for jokes, banter, small "
            "talk, thanks-only messages, greetings, entertainment, general "
            "life advice, or any non-academic request. Completely block "
            "jokes and unacademic talk—never classify them as true even if "
            "they continue a study session. Prefer true only when unsure "
            "whether a study-related query is academic; never prefer true "
            "for jokes or off-topic chat."
        ),
    )
    response: str | None = Field(
        default=None,
        description=(
            "When is_academic_discussion is false, a brief friendly reply "
            "that declines the joke or off-topic request and redirects the "
            "user back to studying without engaging with that content. "
            "Required when is_academic_discussion is false. "
            "Null when is_academic_discussion is true."
        ),
    )

    @model_validator(mode="after")
    def clear_response_when_academic(self) -> Self:
        if self.is_academic_discussion:
            self.response = None
        return self


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
