from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from app.system.chat.schema import ChatResponse

STATUS_LITERAL = Literal["active", "archived"]

DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 50


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
    title: str = Field(default=None, min_length=1, max_length=255)
    # status: Optional[STATUS_LITERAL] = None

class ConversationListResponseData(BaseModel):
    items: list[ConversationResponse]
    next_cursor: Optional[str] = None
    has_more: bool = False
    limit: int


class ConversationListApiResponse(BaseModel):
    data: ConversationListResponseData | None = None
    success: bool = True
    message: str | None = None
    error: str | None = None


class ConversationHistoryApiResponse(BaseModel):
    data: ConversationHistoryResponse | None = None
    success: bool = True
    message: str | None = None
    error: str | None = None


class ConversationApiResponse(BaseModel):
    data: ConversationResponse | None = None
    success: bool = True
    message: str | None = None
    error: str | None = None
