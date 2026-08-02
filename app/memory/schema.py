from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

CONFIDENCE_BUMP = 0.001
IMPORTANCE_BUMP = 0.001

MEMORY_INDEX = "user_memories"
DUPLICATE_TOP_K = 10
DUPLICATE_MIN_SCORE = 0.5
SEARCH_TOP_K = 5

MEMORY_CATEGORY = Literal["personal", "study"]

# Map legacy categories so existing Elasticsearch docs still load.
_LEGACY_CATEGORY_MAP = {
    "academic": "study",
    "learning": "study",
}

CATEGORY_DESCRIPTIONS: dict[MEMORY_CATEGORY, str] = {
    "personal": (
        "Everything OUTSIDE school/studying: gender, work schedule, "
        "job, hobbies, family, life goals, constraints, other people's names. "
        "Never the user's own name (that's on their profile)."
    ),
    "study": (
        "Everything ABOUT school/studying: topics, interests, courses, "
        "exams, resources, strengths, weaknesses, learning style, pace, "
        "study schedule, how they want material explained."
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
            "Never store the user's own name. "
            "Other people's names are allowed when relevant. "
            "Examples: 'The user likes CSC.', "
            "'The user prefers short worked examples.', "
            "'The user's tutor is named Ada.'"
        ),
    )
    category: MEMORY_CATEGORY = Field(
        description=(
            "personal = everything OUTSIDE school/studying; "
            "study = everything ABOUT school/studying."
        ),
    )

    @field_validator("category", mode="before")
    @classmethod
    def coerce_legacy_category(cls, value: Any) -> Any:
        if isinstance(value, str):
            return _LEGACY_CATEGORY_MAP.get(value, value)
        return value

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


class MemoryExtractRequest(BaseModel):
    """RabbitMQ payload for async LLM memory extraction."""

    user_id: str
    context: str
    conversation_id: str | None = None
    known_memories: list[str] = Field(
        default_factory=list,
        description="Facts already retrieved/known this turn; do not re-extract.",
    )


class MemoryRetrievalQuery(BaseModel):
    """LLM-facing memory search intent before embedding."""

    content: str = Field(
        description=(
            "A single partial statement matching how memories are stored. "
            "Start with 'The user'. Combine aspects into one phrase. "
            "Example: 'The user is interested in and prefers'."
        ),
    )


class MemorySearch(BaseModel):
    user_id: str
    content: str
    embedding: list[float]
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

    @field_validator("category", mode="before")
    @classmethod
    def coerce_legacy_category(cls, value: Any) -> Any:
        if isinstance(value, str):
            return _LEGACY_CATEGORY_MAP.get(value, value)
        return value

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
