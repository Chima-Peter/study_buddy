from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 50


class CreateNotificationRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)


class NotificationResponse(BaseModel):
    id: str
    title: str
    content: str
    created_at: datetime
    read_at: Optional[datetime] = None


class NotificationListResponseData(BaseModel):
    items: list[NotificationResponse]
    next_cursor: Optional[str] = None
    has_more: bool = False
    limit: int


class NotificationApiResponse(BaseModel):
    data: Optional[NotificationResponse] = None
    success: bool = True
    message: Optional[str] = None
    error: Optional[str] = None


class NotificationListApiResponse(BaseModel):
    data: Optional[NotificationListResponseData] = None
    success: bool = True
    message: Optional[str] = None
    error: Optional[str] = None

class EventPayload(BaseModel):
    type: str
    data: dict