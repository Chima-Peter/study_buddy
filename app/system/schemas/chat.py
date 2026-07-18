from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

SearchMode = Literal["hybrid", "vector", "bm25"]
WebSocketMessageType = Literal["ping", "query", "subscribe", "unsubscribe"]

TOP_K = 5


class WebSocketMessage(BaseModel):
    type: WebSocketMessageType
    data: dict[str, Any] = Field(default_factory=dict)


def validate_ws_message(data: str) -> tuple[bool, WebSocketMessage | str]:
    """Validate incoming WebSocket message. Returns (is_valid, parsed_message_or_error)."""
    if data == "ping":
        return True, WebSocketMessage(type="ping")
    try:
        msg = WebSocketMessage.model_validate_json(data)
        return True, msg
    except ValidationError as e:
        return False, e.errors()[0].get("msg", "Invalid message")


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, description="User question to retrieve against")
    # mode: SearchMode = Field(
    #     default="hybrid",
    #     description="Search mode: hybrid (RRF), vector (kNN), or bm25",
    # )


class SourceChunk(BaseModel):
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    rrf_score: Optional[float] = Field(
        default=None,
        description="RRF fusion score (only present for hybrid mode)",
    )


class QueryResponseData(BaseModel):
    answer: str
    sources: list[SourceChunk]


class QueryApiResponse(BaseModel):
    data: Optional[QueryResponseData] = None
    success: bool = True
    message: Optional[str] = None
    error: Optional[str] = None
