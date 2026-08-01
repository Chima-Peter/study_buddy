from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, model_validator

CONFIDENCE_BUMP = 0.01

MEMORY_CATEGORY = Literal[
    "personal",
    "academic",
    "learning",
    "progress",
    "resources",
    "habits",
    "achievements",
]

PERSONAL_TYPE = Literal["profile", "preferences", "goals", "schedule"]
ACADEMIC_TYPE = Literal[
    "education",
    "subjects",
    "modules",
    "syllabus",
    "examinations",
]
LEARNING_TYPE = Literal["strengths", "weaknesses", "learning_style", "pace"]
PROGRESS_TYPE = Literal["assessments", "topic_progress", "milestones"]
RESOURCES_TYPE = Literal["books", "notes", "videos", "websites"]
HABITS_TYPE = Literal[
    "study_habits",
    "revision_habits",
    "interaction_habits",
]
ACHIEVEMENTS_TYPE = Literal["completed_courses", "badges", "streaks"]

MEMORY_TYPE = (
    PERSONAL_TYPE
    | ACADEMIC_TYPE
    | LEARNING_TYPE
    | PROGRESS_TYPE
    | RESOURCES_TYPE
    | HABITS_TYPE
    | ACHIEVEMENTS_TYPE
)

CATEGORY_TYPES: dict[MEMORY_CATEGORY, frozenset[str]] = {
    "personal": frozenset({"profile", "preferences", "goals", "schedule"}),
    "academic": frozenset(
        {"education", "subjects", "modules", "syllabus", "examinations"}
    ),
    "learning": frozenset(
        {"strengths", "weaknesses", "learning_style", "pace"}
    ),
    "progress": frozenset({"assessments", "topic_progress", "milestones"}),
    "resources": frozenset({"books", "notes", "videos", "websites"}),
    "habits": frozenset(
        {"study_habits", "revision_habits", "interaction_habits"}
    ),
    "achievements": frozenset({"completed_courses", "badges", "streaks"}),
}

MEMORY_STATUS = Literal[
    "active", "candidate", "superseded", "expired", "archived"
]

MEMORY_SOURCE = Literal["conversation", "inference"]


def validate_category_type(category: MEMORY_CATEGORY, type_: MEMORY_TYPE) -> None:
    allowed = CATEGORY_TYPES[category]
    if type_ not in allowed:
        raise ValueError(
            f"type {type_!r} is not valid for category {category!r}; "
            f"expected one of {sorted(allowed)}"
        )


def taxonomy_description() -> str:
    lines = [
        f"- {category}: {', '.join(sorted(types))}"
        for category, types in CATEGORY_TYPES.items()
    ]
    return "\n".join(lines)


class ExtractedMemory(BaseModel):
    """LLM-facing candidate memory. System fields are filled after extraction."""

    content: str = Field(
        description=(
            "Single atomic fact about the student, written as a concise "
            "statement (e.g. 'Prefers short worked examples')."
        ),
    )
    category: MEMORY_CATEGORY = Field(
        description="High-level memory category.",
    )
    type: MEMORY_TYPE = Field(
        description="Low-level type that must belong to the chosen category.",
    )
    importance: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Importance of this memory for future tutoring (0-1), scored from "
            "the memory itself: high for core profile/goals/constraints that "
            "should shape tutoring; medium for useful preferences or habits; "
            "low for minor or narrow details."
        ),
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Confidence that this fact is true (0-1), scored from how clearly "
            "the student stated it: high for explicit clear statements; medium "
            "for strong implications; low for tentative or ambiguous wording."
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

    @model_validator(mode="after")
    def check_category_type(self) -> "ExtractedMemory":
        validate_category_type(self.category, self.type)
        return self


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
            "Concise search query for the student memory index. "
            "Resolve references; do not answer the question."
        ),
    )
    category: MEMORY_CATEGORY = Field(
        description="Likely memory category to scope the search.",
    )
    type: MEMORY_TYPE = Field(
        description="Likely memory type that must belong to the chosen category.",
    )

    @model_validator(mode="after")
    def check_category_type(self) -> "MemoryRetrievalQuery":
        validate_category_type(self.category, self.type)
        return self


# Always kept in agent state; fetched from the memory index when missing.
CORE_NAME_QUERY = MemoryRetrievalQuery(
    content="student's name",
    category="personal",
    type="profile",
)
CORE_GENDER_QUERY = MemoryRetrievalQuery(
    content="student's gender",
    category="personal",
    type="profile",
)
CORE_PROFILE_QUERIES = (CORE_NAME_QUERY, CORE_GENDER_QUERY)


class MemorySearch(BaseModel):
    user_id: str
    content: str
    embedding: list[float]
    category: MEMORY_CATEGORY
    type: MEMORY_TYPE
    status: MEMORY_STATUS = "active"

    @model_validator(mode="after")
    def check_category_type(self) -> "MemorySearch":
        validate_category_type(self.category, self.type)
        return self


class MemoryDuplicateSearch(BaseModel):
    user_id: str
    content: str
    embedding: list[float]
    category: MEMORY_CATEGORY
    type: MEMORY_TYPE

    @model_validator(mode="after")
    def check_category_type(self) -> "MemoryDuplicateSearch":
        validate_category_type(self.category, self.type)
        return self


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
    type: MEMORY_TYPE
    status: MEMORY_STATUS = "candidate"
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
    def check_category_type(self) -> "Memory":
        validate_category_type(self.category, self.type)
        return self

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
