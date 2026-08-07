import operator
from typing import Annotated, TypedDict

from app.agent.question_bank.schema import ChapterQuestionBank, QuestionBankCritique, QuestionBankResult
from app.core.elasticsearch_schema import IndexedRecord


class QuestionBankState(TypedDict):
    user_id: str
    document_id: str
    chapter_keys: list[str]
    chapter_records: dict[str, list[IndexedRecord]]
    generated_chapters: dict[str, ChapterQuestionBank]
    approved_chapters: Annotated[list[str], operator.add]
    skipped_critique_chapters: list[str]
    critique: dict[str, QuestionBankCritique]
    final_question_bank: QuestionBankResult
    saved: bool