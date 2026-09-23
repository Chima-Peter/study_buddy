from logging import Logger

from langchain_core.messages import AIMessage
from langgraph.config import get_stream_writer

from app.agent.chat_agent.schema import NON_ACADEMIC_FALLBACK
from app.agent.chat_agent.state import AgentState


class EndDiscussionNode:
    def __init__(self, logger: Logger):
        self.logger = logger

    async def __call__(self, state: AgentState) -> AgentState:
        self.logger.info(
            "End discussion node started id=%s user_id=%s",
            state["conversation_id"],
            state["user_id"],
        )

        if state.get("retry_count", 1) > 3:
            self.logger.warning(
                "End discussion node failed id=%s user_id=%s retry_count=%s",
                state["conversation_id"],
                state["user_id"],
                state.get("retry_count"),
            )
            return {}

        response = (state.get("response") or "").strip() or NON_ACADEMIC_FALLBACK
        writer = get_stream_writer()
        writer(
            {
                "type": "chat.response",
                "response": response,
            }
        )

        return {
            "response": response,
            "messages": [AIMessage(content=response)],
            "rag_documents": [],
            "retry_count": state.get("retry_count") + 1,
        }
