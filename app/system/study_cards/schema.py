from typing import Literal, Optional

from pydantic import BaseModel

StudyCardsStatus = Literal["pending", "failed", "success"]

DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 50


class StudyCardsAlreadyExistsError(Exception):
    def __init__(self, document_id: str):
        self.document_id = document_id
        super().__init__(
            "Study cards already exist for this document. "
            "Retrieve the existing study cards instead of generating again."
        )


class StudyCardsInProgressError(Exception):
    def __init__(self, document_id: str):
        self.document_id = document_id
        super().__init__(
            "Study cards generation is already in progress for this document. "
            "Please wait for it to finish."
        )


class StudyCardsGenerateRequest(BaseModel):
    """RabbitMQ payload for async study-card generation."""

    document_id: str
    user_id: str
    name: str


class StudyCardsGenerateAccepted(BaseModel):
    document_id: str


class StudyCardsResultResponse(BaseModel):
    id: str
    document_id: str
    document_name: str | None = None
    status: StudyCardsStatus
    result: dict | None
    question_count: int
    chapter_count: int
    reason: Optional[str] = None
    created_at: str
    updated_at: str


class StudyCardsListItem(BaseModel):
    id: str
    document_id: str
    document_name: str | None = None
    status: StudyCardsStatus
    question_count: int
    chapter_count: int
    created_at: str


class StudyCardsGenerateApiResponse(BaseModel):
    data: StudyCardsGenerateAccepted | None = None
    success: bool = True
    message: str | None = None
    error: str | None = None


class StudyCardsGetApiResponse(BaseModel):
    data: StudyCardsResultResponse | None = None
    success: bool = True
    message: str | None = None
    error: str | None = None


class StudyCardsListResponseData(BaseModel):
    items: list[StudyCardsListItem]
    next_cursor: Optional[str] = None
    has_more: bool = False
    limit: int


class StudyCardsListApiResponse(BaseModel):
    data: StudyCardsListResponseData | None = None
    success: bool = True
    message: str | None = None
    error: str | None = None
