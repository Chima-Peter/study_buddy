from pydantic import BaseModel, Field

from app.system.schemas.chat import ChatResponse


class CreateConversationRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)


class UpdateConversationTitleRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class ConversationResponse(BaseModel):
    id: str
    title: str | None


class ConversationDetailResponse(ConversationResponse):
    chats: list[ChatResponse]
