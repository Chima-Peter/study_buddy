from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from app.core.elasticsearch_schema import FusedResult
from app.memory.schema import Memory
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
    retrieve_memory: bool

    memory_query: str | None
    memories: list[Memory]

    # Persist across turns; fetched from postgres when missing.
    student_name: str | None
    student_gender: str | None

    response: str
