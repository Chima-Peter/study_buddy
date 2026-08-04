from typing import TypedDict
from app.core.elasticsearch_schema import IndexedRecord

class QuizState(TypedDict):
    document_id: str
    document_sections: dict[str, list[IndexedRecord]]
    user_id: str
    chapter_keys: list[str]