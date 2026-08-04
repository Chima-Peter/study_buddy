from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from app.core.elasticsearch_schema import FusedResult
from app.memory.schema import Memory
from app.system.chat.schema import ChatResponse

import operator

class AgentState(TypedDict):
    query: str
    rewritten_query: str
    conversation_id: str
    user_id: str
    document_ids: list[str] | None
    document_sections: dict[str, list[str]]
    chapter_keys: list[str] | None
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

    student_name: str | None
    student_gender: str | None

    response: str
