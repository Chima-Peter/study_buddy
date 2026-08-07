from typing import Literal

from app.agent.study_cards_agent.schema import MAX_CRITIQUE_RETRIES, MAX_GENERATE_RETRIES
from app.agent.study_cards_agent.state import StudyCardsState

RouteTarget = Literal[
    "retrieve_chapter_keys",
    "retrieve_sessions",
    "retrieve_memories",
    "generate",
    "critique",
    "consolidate",
    "save",
    "END",
]


def route_from_checkpoint(state: StudyCardsState) -> RouteTarget | list[str]:
    """Resume-aware router: pick the next step from current/checkpointed state."""
    if state.get("saved"):
        return "END"
    if state.get("final_result") is not None:
        return "save"

    if (
        state.get("chapter_keys") is None
        or state.get("document_sections") is None
        or state.get("memories") is None
    ):
        return ["retrieve_memories", "retrieve_chapter_keys"]

    return decide_generation_or_critique(state)


def decide_generation_or_critique(
    state: StudyCardsState,
) -> Literal["generate", "critique", "consolidate"]:
    retry_count = state.get("retry_count") or {"generate": 0, "critique": 0}
    generate_count = retry_count.get("generate", 0)
    critique_count = retry_count.get("critique", 0)
    if check_for_generation(generate_count, critique_count, state):
        return "generate"
    if check_for_critique(generate_count, critique_count, state):
        return "critique"
    return "consolidate"


def check_for_generation(
    generate_count: int,
    critique_count: int,
    state: StudyCardsState,
) -> bool:
    if generate_count > MAX_GENERATE_RETRIES:
        return False
    if generate_count > critique_count:
        return False
    undone = set(state.get("undone_critique_chapters") or [])
    return any(
        chapter_key not in undone
        for chapter_key in (
            *(state.get("pending_chapters") or []),
            *(state.get("missing_chapters") or []),
        )
    )


def check_for_critique(
    generate_count: int,
    critique_count: int,
    state: StudyCardsState,
) -> bool:
    if critique_count > MAX_CRITIQUE_RETRIES:
        return False

    undone = state.get("undone_critique_chapters") or []
    if critique_count >= generate_count and not undone:
        return False

    approved = set(state.get("approved_chapters") or [])
    unapproved = [
        chapter_key
        for chapter_key in (state.get("generated_chapters") or {})
        if chapter_key not in approved
    ]
    if unapproved or undone:
        return True

    return generate_count > critique_count and bool(
        (state.get("pending_chapters") or [])
        or (state.get("missing_chapters") or [])
    )
