from datetime import datetime

from pydantic import BaseModel

TOP_K = 10


class ChatResponse(BaseModel):
    id: str
    conversation_id: str
    query: str
    response: str
    query_message_id: str | None = None
    response_message_id: str | None = None
    created_at: datetime
