from pydantic import BaseModel


class QuizGenerateRequest(BaseModel):
    """RabbitMQ payload for async quiz / study-card generation."""

    document_id: str
    user_id: str


class QuizGenerateAccepted(BaseModel):
    document_id: str


class QuizResultResponse(BaseModel):
    id: str
    document_id: str
    result: dict | None
    created_at: str
    updated_at: str


class QuizGenerateApiResponse(BaseModel):
    data: QuizGenerateAccepted | None = None
    success: bool = True
    message: str | None = None
    error: str | None = None


