from pydantic import BaseModel
from typing import Literal

StudyCardsStatus = Literal["pending", "failed", "success"]


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


class StudyCardsGenerateAccepted(BaseModel):
    document_id: str


class StudyCardsResultResponse(BaseModel):
    id: str
    document_id: str
    status: StudyCardsStatus
    result: dict | None
    created_at: str
    updated_at: str


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
