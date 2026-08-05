from pydantic import BaseModel


class StudyCardsGenerateRequest(BaseModel):
    """RabbitMQ payload for async study-card generation."""

    document_id: str
    user_id: str


class StudyCardsGenerateAccepted(BaseModel):
    document_id: str


class StudyCardsResultResponse(BaseModel):
    id: str
    document_id: str
    result: dict | None
    created_at: str
    updated_at: str


class StudyCardsGenerateApiResponse(BaseModel):
    data: StudyCardsGenerateAccepted | None = None
    success: bool = True
    message: str | None = None
    error: str | None = None
