from typing import Literal, TypedDict

from app.agent.study_cards_agent.schema import ChapterResult, Critique, StudyCardsResult
from app.core.elasticsearch_schema import IndexedRecord


class StudyCardsState(TypedDict):
    document_id: str
    document_sections: dict[str, list[IndexedRecord]]
    user_id: str
    chapter_keys: list[str]
    generated_chapters: dict[str, ChapterResult]
    approved_chapters: list[str]
    pending_chapters: list[str]
    missing_chapters: list[str]
    retry_count: dict[Literal["generate", "critique"], int]
    final_result: StudyCardsResult
    critique: dict[str, Critique]
