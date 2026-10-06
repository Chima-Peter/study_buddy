from langgraph.graph import MessagesState

from app.agent.chat_agent.schema import MemoryRetrieval
from app.core.elasticsearch_schema import FusedResult
from app.memory.schema import Memory

class AgentState(MessagesState):
    query: str
    rewritten_query: str
    cache_query: str | None
    tavily_query: str | None
    conversation_id: str
    user_id: str
    document_id: str | None
    document_sections: dict[str, list[str]]
    chapter_keys: list[str] | None
    title: str | None
    conversation_summary: str | None
    rag_documents: list[FusedResult]
    tavily_results: list[dict]
    semantic_cache_hit: bool
    query_embedding: list[float] | None

    retrieve_rag: bool
    retrieve_conversation_history: bool
    retrieve_memory: bool
    is_academic_discussion: bool
    answer_from_history: bool

    memory_queries: list[MemoryRetrieval]
    memories: list[Memory]

    student_name: str | None
    student_gender: str | None

    response: str

    turn_type: str | None
    fork_chat_id: str | None
