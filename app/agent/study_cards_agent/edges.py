from typing import Literal

from app.agent.study_cards_agent.schema import MAX_CRITIQUE_RETRIES, MAX_GENERATE_RETRIES
from app.agent.study_cards_agent.state import StudyCardsState


def decide_generation_or_critique(
    state: StudyCardsState,
) -> Literal["generate", "critique", "consolidate"]:
    generate_count = state["retry_count"]["generate"]
    critique_count = state["retry_count"]["critique"]
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
        for chapter_key in (*state["pending_chapters"], *state["missing_chapters"])
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

    approved = set(state["approved_chapters"])
    unapproved = [
        chapter_key
        for chapter_key in state["generated_chapters"]
        if chapter_key not in approved
    ]
    if unapproved or undone:
        return True

    return generate_count > critique_count and bool(
        state["pending_chapters"] or state["missing_chapters"]
    )
