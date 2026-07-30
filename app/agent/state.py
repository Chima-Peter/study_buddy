from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from app.core.elasticsearch import FusedResult
from app.system.schemas.chat import ChatResponse

import operator

class AgentState(TypedDict):
    query: str
    rewritten_query: str
    conversation_id: str
    user_id: str
    first_message: bool
    title: str | None
    conversation_history: Annotated[list[ChatResponse], operator.add]
    conversation_summary: str | None
    rag_documents: list[FusedResult]
    messages: Annotated[list[AnyMessage], operator.add]

    retrieve_rag: bool
    retrieve_conversation_history: bool

    response: str