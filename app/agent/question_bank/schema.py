from pydantic import BaseModel

class QuestionSchema(BaseModel):
    question: str
    options: list[str]
    correct_option_index: int
    explanation: str
    difficulty: str
    internal_references: list[str]
    external_references: list[str]

class ChapterQuestionBank(BaseModel):
    chapter_key: str
    questions: list[QuestionSchema]

class QuestionCritique(BaseModel):
    question: QuestionSchema
    critique: str

class QuestionBankCritique(BaseModel):
    questions: list[QuestionCritique]

class QuestionBankResult(BaseModel):
    chapters: list[ChapterQuestionBank]