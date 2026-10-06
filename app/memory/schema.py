from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

MEMORY_INDEX = "user_memories"
SEARCH_TOP_K = 10
DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 20

MEMORY_CATEGORY = Literal[
    "learning_preferences",
    "academic_struggles",
    "academic_progress",
    "tests_exams",
    "user_personality",
]

CATEGORY_DESCRIPTIONS: dict[MEMORY_CATEGORY, str] = {
    "learning_preferences": (
        "How the user prefers to learn or study. "
        "Includes preferred explanation style, pace, format "
        "(examples, visuals, step-by-step), study habits, and "
        "scheduling preferences for studying. "
        "Examples: 'The user prefers step-by-step explanations.', "
        "'The user prefers learning with practical examples.', "
        "'The user prefers studying for two hours per day.' "
        "Do NOT use for a specific academic topic the user is "
        "struggling with or making progress on."
    ),
    "academic_struggles": (
        "Academic topics, concepts, or skills that the user finds "
        "difficult, does not understand, confuses, or needs extra "
        "help with. "
        "Examples: 'The user struggles with recursion.', "
        "'The user finds dynamic programming difficult.', "
        "'The user is confused about normalization in databases.' "
        "Use for an ongoing difficulty, not simply because the user "
        "asks a question about a topic."
    ),
    "academic_progress": (
        "The user's academic progress, status, or milestones. "
        "Includes topics started, currently studying, or finished; "
        "skills mastered; courses or units completed; academic "
        "milestones. "
        "Examples: 'The user is currently studying binary trees.', "
        "'The user has finished studying binary trees.', "
        "'The user understands recursion after previously struggling "
        "with it.', "
        "'The user has completed the database systems course.' "
        "When new information updates progress on an existing topic, "
        "PATCH the existing memory rather than creating a duplicate."
    ),
    "tests_exams": (
        "Specific tests, examinations, or exam-related milestones. "
        "Includes upcoming or past tests/exams, preparation status, "
        "scores, deadlines, exam-related goals, and explicit "
        "exam-related concerns. "
        "Examples: 'The user is preparing for the IELTS exam.', "
        "'The user has completed the IELTS exam.', "
        "'The user scored 8.0 in IELTS.', "
        "'The user's exam is scheduled for July 14.' "
        "Use for the exam itself and its associated status. "
        "General academic progress stays in academic_progress."
    ),
    "user_personality": (
        "Durable information about the user outside pure academic "
        "learning. "
        "Includes interests, personality traits explicitly described "
        "by the user, motivation, work or life context, constraints, "
        "hobbies, family-related information when relevant, and other "
        "people's names when relevant. "
        "Examples: 'The user is interested in fintech.', "
        "'The user prefers backend engineering roles.', "
        "'The user works remotely.', "
        "'The user's brother is studying medicine.' "
        "Never store the user's own name (already on their profile)."
    ),
}

CATEGORY_SELECTION_RULES = """
When multiple categories seem possible, classify by the primary meaning:
- How the user wants to learn → learning_preferences
- What the user finds difficult → academic_struggles
- What the user has started, completed, or mastered → academic_progress
- A specific test or exam and its status → tests_exams
- Other durable information about the user → user_personality

Do not create multiple memories for the same fact just because it could
relate to multiple categories. Examples:
- "The user struggles with recursion." → academic_struggles
- "The user finally understands recursion." → academic_progress
- "The user prefers recursion to be explained with diagrams."
  → learning_preferences
- "The user is preparing for a recursion exam." → tests_exams
- "The user enjoys studying computer science." → user_personality
""".strip()


DOCUMENT_SCOPED_CATEGORIES: frozenset[MEMORY_CATEGORY] = frozenset(
    {
        "learning_preferences",
        "academic_progress",
        "tests_exams",
    }
)


def taxonomy_description() -> str:
    categories = "\n".join(
        f"- {category}: {description}"
        for category, description in CATEGORY_DESCRIPTIONS.items()
    )
    return f"{categories}\n\n{CATEGORY_SELECTION_RULES}"


class ExtractedMemory(BaseModel):
    """LLM-facing candidate memory. System fields are filled after extraction."""

    content: str = Field(
        description=(
            "One complete fact about the user, written as a full sentence "
            "starting with 'The user' or 'The user's'. "
            "Never store the user's own name. "
            "Other people's names are allowed when relevant. "
            "Examples: 'The user likes CSC.', "
            "'The user prefers short worked examples.', "
            "'The user's tutor is named Ada.'"
        ),
    )
    category: MEMORY_CATEGORY = Field(
        description=(
            "Pick exactly one. "
            "learning_preferences = how they prefer to learn/study; "
            "academic_struggles = ongoing difficulty with a topic/skill; "
            "academic_progress = started/studying/finished/mastered; "
            "tests_exams = a specific test/exam and its status; "
            "user_personality = durable non-academic facts about the user."
        ),
    )
    expires_at: datetime | None = Field(
        default=None,
        description=(
            "Absolute UTC expiry datetime for temporary memories when the "
            "student gives a time bound. Resolve relative or calendar phrases "
            "against the prompt's reference time "
            "(e.g. 'tomorrow', 'next week', '14th of July' → a concrete "
            "UTC ISO datetime). Null for durable memories with no expiry."
        ),
    )
    document_id: str | None = Field(
        default=None,
        description=(
            "Optional document this fact is about. Only for "
            "learning_preferences, academic_progress, or tests_exams. "
            "Null for global facts or other categories."
        ),
    )

    @model_validator(mode="after")
    def check_document_scope(self) -> "ExtractedMemory":
        if (
            self.document_id is not None
            and self.category not in DOCUMENT_SCOPED_CATEGORIES
        ):
            self.document_id = None
        return self


class MemoryRetrievalQuery(BaseModel):
    """LLM-facing memory search intent before embedding."""

    content: str = Field(
        description=(
            "A single partial statement matching how memories are stored. "
            "Start with 'The user'. Combine aspects into one phrase. "
            "Example: 'The user is interested in and prefers'."
        ),
    )
    category: MEMORY_CATEGORY | None = Field(
        default=None,
        description=(
            "Optional category filter for this search. "
            "learning_preferences, academic_struggles, academic_progress, "
            "tests_exams, or user_personality. Null to search all categories."
        ),
    )
    document_id: str | None = Field(
        default=None,
        description=(
            "Optional document filter. Only meaningful for "
            "learning_preferences, academic_progress, or tests_exams. "
            "Null to include memories not scoped to a document."
        ),
    )


class MemorySearchQueryResult(BaseModel):
    """Structured LLM output for memory search-query generation."""

    queries: list[MemoryRetrievalQuery] = Field(
        default_factory=list,
        description=(
            "Search queries for finding existing memories related to new "
            "facts in the conversation. Return an empty list when nothing "
            "memory-worthy was said."
        ),
    )


class MemoryExtractRequest(BaseModel):
    """RabbitMQ payload for async LLM memory extraction."""

    user_id: str
    context: str
    conversation_id: str | None = None
    document_id: str | None = None
    known_memories: list[str] = Field(
        default_factory=list,
        description="Facts already retrieved this turn; used for search queries only.",
    )


class MemorySearch(BaseModel):
    user_id: str
    content: str
    embedding: list[float]
    category: MEMORY_CATEGORY | None = None
    document_id: str | None = None


class Memory(BaseModel):
    id: str
    user_id: str
    content: str
    embedding: list[float]
    category: MEMORY_CATEGORY
    document_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime | None = None
    expires_at: datetime | None = None


    @model_validator(mode="after")
    def check_document_scope(self) -> "Memory":
        if (
            self.document_id is not None
            and self.category not in DOCUMENT_SCOPED_CATEGORIES
        ):
            self.document_id = None
        return self


class MemoryResponse(BaseModel):
    id: str
    content: str
    category: MEMORY_CATEGORY
    document_id: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    expires_at: datetime | None = None


class MemoryListResponseData(BaseModel):
    items: list[MemoryResponse]
    next_cursor: Optional[str] = None
    has_more: bool = False
    limit: int


class MemoryListApiResponse(BaseModel):
    data: Optional[MemoryListResponseData] = None
    success: bool = True
    message: Optional[str] = None
    error: Optional[str] = None


