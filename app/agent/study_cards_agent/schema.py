from typing import Literal
from pydantic import BaseModel

MAX_GENERATE_RETRIES = 3
MAX_CRITIQUE_RETRIES = 3

class Sections(BaseModel):
    title: str
    content: str 
    external_references: list[str]
    references: list[str]

class ChapterResult(BaseModel):
    chapter_key: str
    introduction: str
    sections: list[Sections]
    quiz: dict[str, str]

class StudyCardsResult(BaseModel):
    chapters: list[ChapterResult]

class Critique(BaseModel):
    chapter_key: str
    status: Literal["approved", "rejected"]
    comment: str | None