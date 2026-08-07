from typing import Literal, Optional

from pydantic import BaseModel

QuestionBankStatus = Literal["pending", "failed", "success"]

DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 50


class QuestionBankAlreadyExistsError(Exception):
    def __init__(self, document_id: str):
        self.document_id = document_id
        super().__init__(
            "Question bank already exists for this document. "
            "Retrieve the existing question bank instead of generating again."
        )


class QuestionBankInProgressError(Exception):
    def __init__(self, document_id: str):
        self.document_id = document_id
        super().__init__(
            "Question bank generation is already in progress for this document. "
            "Please wait for it to finish."
        )


class QuestionBankGenerateRequest(BaseModel):
    """RabbitMQ payload for async question-bank generation."""

    document_id: str
    user_id: str
    name: str


class QuestionBankGenerateAccepted(BaseModel):
    document_id: str


class QuestionBankResultResponse(BaseModel):
    id: str
    document_id: str
    document_name: str | None = None
    status: QuestionBankStatus
    result: dict | None
    reason: Optional[str] = None
    created_at: str
    updated_at: str


class QuestionBankGenerateApiResponse(BaseModel):
    data: QuestionBankGenerateAccepted | None = None
    success: bool = True
    message: str | None = None
    error: str | None = None


class QuestionBankGetApiResponse(BaseModel):
    data: QuestionBankResultResponse | None = None
    success: bool = True
    message: str | None = None
    error: str | None = None


class QuestionBankListResponseData(BaseModel):
    items: list[QuestionBankResultResponse]
    next_cursor: Optional[str] = None
    has_more: bool = False
    limit: int


class QuestionBankListApiResponse(BaseModel):
    data: QuestionBankListResponseData | None = None
    success: bool = True
    message: str | None = None
    error: str | None = None
