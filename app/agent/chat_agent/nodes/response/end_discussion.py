from logging import Logger
from app.agent.chat_agent.state import AgentState
from langgraph.config import get_stream_writer


class EndDiscussionNode:
    def __init__(self, logger: Logger):
        self.logger = logger

    async def __call__(self, state: AgentState) -> AgentState:
        self.logger.info(
            "End discussion node started id=%s user_id=%s",
            state["conversation_id"],
            state["user_id"],
        )

        response = (
            "I'm sorry, I can't help with that. This is a study buddy, "
            "not a general purpose chatbot. Please ask me something related "
            "to your studies!"
        )
        writer = get_stream_writer()
        writer(
            {
                "type": "chat.response",
                "response": response,
            }
        )
        return {
            "response": response,
            "rag_documents": [],
        }
