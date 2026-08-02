from logging import Logger

from app.agent.state import AgentState


class CleanupNode:
    """Clears transient state before checkpointing."""

    def __init__(self, logger: Logger):
        self.logger = logger

    async def __call__(self, state: AgentState) -> AgentState:
        self.logger.info(
            "Cleanup node started id=%s user_id=%s",
            state["conversation_id"],
            state["user_id"],
        )
        return {
            "query": "",
            "rewritten_query": "",
            "first_message": False,
            "rag_documents": [],
            "retrieve_rag": False,
            "retrieve_conversation_history": False,
            "retrieve_memory": False,
            "memory_query": None,
            "memories": [],
            "response": "",
            "messages": [],
        }
