from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

SearchMode = Literal["hybrid", "vector", "bm25"]

TOP_K = 10

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

class ConversationResponse(BaseModel):
    id: str
    user_id: str
    query: str
    conversation: str
    created_at: datetime
