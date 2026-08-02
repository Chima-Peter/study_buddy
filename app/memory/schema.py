from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, model_validator

CONFIDENCE_BUMP = 0.01

MEMORY_CATEGORY = Literal[
    "personal",
    "academic",
    "learning",
]

CATEGORY_DESCRIPTIONS: dict[MEMORY_CATEGORY, str] = {
    "personal": (
        "Use when the fact is about identity or life logistics: name, gender, "
        "availability/schedule, life goals, constraints. "
        "Not school/course details and not strengths, weaknesses, or learning style."
    ),
    "academic": (
        "Use when the fact is about their school/course context: university, "
        "programme, subjects, modules, syllabus, exams, study resources. "
        "Not personal identity and not how well they learn a topic."
    ),
    "learning": (
        "Use when the fact is about ability or teaching fit: strengths, "
        "weaknesses, learning style, pace, topic mastery, assessment results, "
        "milestones, how they want material explained. "
        "Not identity/schedule and not which school/subject they take."
    ),
}

MEMORY_STATUS = Literal[
    "active", "candidate", "superseded", "expired", "archived"
]

MEMORY_SOURCE = Literal["conversation", "inference"]


def taxonomy_description() -> str:
    return "\n".join(
        f"- {category}: {description}"
        for category, description in CATEGORY_DESCRIPTIONS.items()
    )


class ExtractedMemory(BaseModel):
    """LLM-facing candidate memory. System fields are filled after extraction."""

    content: str = Field(
        description=(
            "One complete fact about the user, written as a full sentence "
            "starting with 'The user' or 'The user's'. "
            "Examples: 'The user's name is Peter.', "
            "'The user Peter likes CSC.', "
            "'The user prefers short worked examples.'"
        ),
    )
    category: MEMORY_CATEGORY = Field(
        description=(
            "Exact category for this fact. Choose one of: personal, academic, "
            "learning. Follow the category conditions in the taxonomy."
        ),
    )
    importance: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Importance of this memory for future tutoring (0-1): high for "
            "core profile/goals/constraints; medium for useful preferences "
            "or habits; low for minor details."
        ),
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Confidence that this fact is true (0-1): high for explicit clear "
            "statements; medium for strong implications; low for tentative "
            "or ambiguous wording."
        ),
    )
    expires_at: datetime | None = Field(
        default=None,
        description=(
            "UTC expiry datetime for temporary memories when the student "
            "gives a time bound (e.g. next week, next month, tomorrow). "
            "Null for durable memories with no expiry."
        ),
    )


class MemoryExtractionResult(BaseModel):
    """Structured LLM output for memory extraction."""

    memories: list[ExtractedMemory] = Field(
        default_factory=list,
        description=(
            "Durable memories extracted from the conversation. "
            "Return an empty list when nothing worth storing was said."
        ),
    )


class MemoryRetrievalQuery(BaseModel):
    """LLM-facing memory search intent before embedding."""

    content: str = Field(
        description=(
            "A short simple question to ask the memory store, e.g. "
            "'What is the user's name?', "
            "'Which university does the user attend?', "
            "'What subjects does the user like?'."
        ),
    )
    category: MEMORY_CATEGORY = Field(
        description=(
            "Exact category to search. Choose one of: personal, academic, "
            "learning. Follow the category conditions in the taxonomy."
        ),
    )


# Always kept in agent state; fetched from the memory index when missing.
CORE_NAME_QUERY = MemoryRetrievalQuery(
    content="What is the user's name?",
    category="personal",
)
CORE_GENDER_QUERY = MemoryRetrievalQuery(
    content="What is the user's gender?",
    category="personal",
)
CORE_PROFILE_QUERIES = (CORE_NAME_QUERY, CORE_GENDER_QUERY)


class MemorySearch(BaseModel):
    user_id: str
    content: str
    embedding: list[float]
    category: MEMORY_CATEGORY
    status: MEMORY_STATUS = "active"


class MemoryDuplicateSearch(BaseModel):
    user_id: str
    content: str
    embedding: list[float]
    category: MEMORY_CATEGORY


class IdenticalDecision(BaseModel):
    candidate_id: str = Field(description="ID of the candidate memory.")
    existing_id: str = Field(description="ID of the matching existing memory.")
    verified: bool = Field(
        description=(
            "True only after you verify both memories state the same fact. "
            "If not verified, do not list this pair under identical."
        ),
    )


class UpdatedDecision(BaseModel):
    candidate_id: str = Field(
        description="ID of the candidate memory that will be stored.",
    )
    existing_id: str = Field(
        description="ID of the existing memory that will be superseded.",
    )


class DifferentDecision(BaseModel):
    candidate_id: str = Field(
        description="ID of a candidate that can coexist with existing memories.",
    )


class ContradictDecision(BaseModel):
    candidate_id: str = Field(description="ID of the candidate memory.")
    existing_id: str = Field(
        description="ID of the existing memory it contradicts.",
    )


class MemoryDeduplicationDecision(BaseModel):
    """Structured LLM output for memory deduplication."""

    identical: list[IdenticalDecision] = Field(
        default_factory=list,
        description=(
            "Candidate and existing state the same fact. Keep existing; "
            "system will raise its confidence slightly when verified is true."
        ),
    )
    updated: list[UpdatedDecision] = Field(
        default_factory=list,
        description=(
            "Candidate revises an existing memory. The existing memory will be "
            "superseded; the candidate will be stored."
        ),
    )
    different: list[DifferentDecision] = Field(
        default_factory=list,
        description=(
            "Candidate is a distinct fact that can coexist; store the candidate."
        ),
    )
    contradict: list[ContradictDecision] = Field(
        default_factory=list,
        description=(
            "Candidate conflicts with an existing memory. Existing will be "
            "archived; the candidate will be stored as the new fact."
        ),
    )


class Memory(BaseModel):
    id: str
    user_id: str
    content: str
    embedding: list[float]
    category: MEMORY_CATEGORY
    status: MEMORY_STATUS = "active"
    importance: float
    confidence: float
    usage_count: int = 0
    last_used_at: datetime | None = None
    source: MEMORY_SOURCE
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime | None = None
    expires_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    @model_validator(mode="after")
    def check_validity_window(self) -> "Memory":
        if (
            self.valid_from is not None
            and self.valid_to is not None
            and self.valid_from > self.valid_to
        ):
            raise ValueError("valid_from must be before or equal to valid_to")
        return self


class MemoryDeduplicationResult(BaseModel):
    identical: list[Memory]
    superseded: list[Memory]
    archived: list[Memory]
    updated: list[Memory]
    different: list[Memory]
    contradict: list[Memory]
