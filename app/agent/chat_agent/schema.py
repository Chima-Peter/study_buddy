from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.memory.schema import MEMORY_CATEGORY

SUMMARY_EVERY = 10
SUMMARY_MAX_CHARS = 1500

NON_ACADEMIC_FALLBACK = (
    "I'm sorry, I can't help with that. This is a study buddy, "
    "not a general purpose chatbot. Please ask me something related "
    "to your studies!"
)


class MemoryRetrieval(BaseModel):
    """One memory search intent for chat retrieval."""

    query: str = Field(
        description=(
            "Partial statement for the memory index, phrased like stored "
            "memories starting with 'The user'. "
            "Example: 'The user prefers visual explanations'."
        ),
    )
    category: MEMORY_CATEGORY | None = Field(
        default=None,
        description=(
            "Optional category filter: learning_preferences, "
            "academic_struggles, academic_progress, tests_exams, or "
            "user_personality. Null to search all categories."
        ),
    )


class DeciderResponse(BaseModel):
    """Decide retrieval needs and rewrite queries in one step."""

    decision: Literal["rag", "history", "both", "none"] = Field(
        description=(
            "rag: academic/study question answered from uploaded study "
            "documents; "
            "history: only a true repeat of a prior question whose prior "
            "answer can be reused as-is, or a non-academic recap of chat; "
            "both: academic/study question needing documents and prior chat "
            "(including deepen/expand follow-ups that resolve the topic "
            "from chat); "
            "none: non-academic/general question needing neither. "
            "When answer_from_history is true, use history. "
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
            "knowledge, chat that does not depend on stored student facts, "
            "or when answer_from_history is true. "
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
            "for jokes or off-topic chat. "
            "Repeated academic questions still count as true."
        ),
    )
    answer_from_history: bool = Field(
        description=(
            "True only for a true repeat: same intent and same depth as a "
            "question already asked, so the prior assistant answer can be "
            "reused. False for any request for more depth, detail, "
            "examples, a new angle, or fresh document/web retrieval "
            "(e.g. 'dive deeper', 'tell me more', 'explain further')."
        ),
    )
    response: str | None = Field(
        default=None,
        description=(
            "When is_academic_discussion is false: a brief friendly reply "
            "that declines the joke or off-topic request and redirects the "
            "user back to studying without engaging with that content. "
            "Required when is_academic_discussion is false. "
            "Null when is_academic_discussion is true or "
            "answer_from_history is true."
        ),
    )
    rag_query: str | None = Field(
        default=None,
        description=(
            "Rewritten query for hybrid document search when decision is "
            "rag or both. Null otherwise."
        ),
    )
    cache_query: str | None = Field(
        default=None,
        description=(
            "Context-rich query for semantic cache lookup when decision is "
            "rag or both. May include conversation context, resolved "
            "references, topic, chapter scope, and clarifying details. "
            "Null otherwise."
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
    memory_queries: list[MemoryRetrieval] = Field(
        default_factory=list,
        description=(
            "One or more memory retrieval intents when retrieve_memory is "
            "true. Each has a query (partial statement starting with "
            "'The user') and an optional category. Empty when memory "
            "retrieval is not needed. Do not include name/gender lookups; "
            "those come from profile."
        ),
    )
    tavily_query: str | None = Field(
        default=None,
        description=(
            "Search query for external YouTube and Google article results "
            "in the form: 'provide some articles and youtube videos on "
            "this: <topic>. stick only to youtube and google website urls'. "
            "Insert the student's topic; do not answer it. "
            "Null when the question (even with history/summary) lacks a "
            "clear topic worth searching for, when answer_from_history is "
            "true, or when is_academic_discussion is false."
        ),
    )

    @model_validator(mode="after")
    def clear_fields_by_decision(self) -> Self:
        if self.answer_from_history:
            self.decision = "history"
            self.response = None
            self.rag_query = None
            self.cache_query = None
            self.chapters = None
            self.memory_queries = []
            self.tavily_query = None
            self.retrieve_memory = False
            return self

        if self.is_academic_discussion:
            self.response = None
        else:
            self.rag_query = None
            self.cache_query = None
            self.chapters = None
            self.memory_queries = []
            self.tavily_query = None
            self.retrieve_memory = False
            return self

        if self.decision not in ("rag", "both"):
            self.rag_query = None
            self.cache_query = None
            self.chapters = None

        if not self.retrieve_memory:
            self.memory_queries = []

        return self
