from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from app.system.chat.schema import ChatResponse

STATUS_LITERAL = Literal["active", "archived"]


class CreateConversationRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)


class UpdateConversationTitleRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class ConversationResponse(BaseModel):
    id: str
    title: str | None
    status: STATUS_LITERAL = "active"


class ConversationDetailResponse(ConversationResponse):
    summary: str | None
    chats: list[ChatResponse]


class ConversationHistoryResponse(ConversationResponse):
    chats: list[ChatResponse]


class ConversationPatchRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    status: Optional[STATUS_LITERAL] = None

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "ConversationPatchRequest":
        if self.title is None and self.status is None:
            raise ValueError("At least one of title or status must be provided")
        return self
