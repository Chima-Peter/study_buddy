from langgraph.graph import MessagesState

from app.core.elasticsearch_schema import FusedResult
from app.memory.schema import Memory

class AgentState(MessagesState):
    query: str
    rewritten_query: str
    conversation_id: str
    user_id: str
    document_ids: list[str] | None
    document_sections: dict[str, list[str]]
    chapter_keys: list[str] | None
    title: str | None
    conversation_summary: str | None
    rag_documents: list[FusedResult]

    retrieve_rag: bool
    retrieve_conversation_history: bool
    retrieve_memory: bool
    is_academic_discussion: bool

    memory_query: str | None
    memories: list[Memory]

    student_name: str | None
    student_gender: str | None

    response: str

    retry_count: int = 1
