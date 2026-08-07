from typing import Literal

from app.agent.question_bank.schema import (
    MAX_CRITIQUE_RETRIES,
    MAX_GENERATE_RETRIES,
    QuestionBankCritique,
)
from app.agent.question_bank.state import QuestionBankState

RouteTarget = Literal[
    "retrieve_chapter_keys",
    "retrieve_chapter_records",
    "generate",
    "critique",
    "consolidate",
    "save",
    "END",
]


def route_from_checkpoint(state: QuestionBankState) -> RouteTarget | list[str]:
    """Resume-aware router: pick the next step from current/checkpointed state."""
    if state.get("saved"):
        return "END"
    if state.get("final_question_bank") is not None:
        return "save"

    if state.get("chapter_keys") is None:
        return "retrieve_chapter_keys"
    if state.get("chapter_records") is None:
        return "retrieve_chapter_records"

    return decide_generation_or_critique(state)


def decide_generation_or_critique(
    state: QuestionBankState,
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
    state: QuestionBankState,
) -> bool:
    if generate_count > MAX_GENERATE_RETRIES:
        return False
    if generate_count > critique_count:
        return False

    skipped_critique = set(state.get("skipped_critique_chapters") or [])
    return any(
        chapter_key not in skipped_critique
        for chapter_key in chapters_needing_generation(state)
    )


def check_for_critique(
    generate_count: int,
    critique_count: int,
    state: QuestionBankState,
) -> bool:
    if critique_count > MAX_CRITIQUE_RETRIES:
        return False

    skipped_critique = state.get("skipped_critique_chapters") or []
    if critique_count >= generate_count and not skipped_critique:
        return False

    approved = set(state.get("approved_chapters") or [])
    unapproved = [
        chapter_key
        for chapter_key in (state.get("generated_chapters") or {})
        if chapter_key not in approved
    ]
    if unapproved or skipped_critique:
        return True

    return generate_count > critique_count and bool(
        chapters_needing_generation(state)
    )


def chapters_needing_generation(state: QuestionBankState) -> list[str]:
    """Chapters that failed gen, were never generated, or were rejected."""
    approved = set(state.get("approved_chapters") or [])
    generated = state.get("generated_chapters") or {}
    critique = state.get("critique") or {}
    skipped_generated = set(state.get("skipped_generated_chapters") or [])
    chapter_keys = state.get("chapter_keys") or list(
        (state.get("chapter_records") or {}).keys()
    )

    needing: list[str] = []
    for chapter_key in chapter_keys:
        if chapter_key in approved:
            continue
        if chapter_key in skipped_generated or chapter_key not in generated:
            needing.append(chapter_key)
            continue
        if _has_rejection(critique.get(chapter_key)):
            needing.append(chapter_key)
    return needing


def _has_rejection(entry: QuestionBankCritique | None) -> bool:
    if entry is None:
        return False
    return any(item.critique for item in entry.questions)
