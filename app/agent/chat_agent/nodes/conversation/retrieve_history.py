from logging import Logger

from app.agent.chat_agent.state import AgentState
from app.system.conversation.service import ConversationService


class RetrieveConversationHistoryNode:
    def __init__(
        self,
        conversation_service: ConversationService,
        logger: Logger,
    ):
        self.conversation_service = conversation_service
        self.logger = logger

    async def __call__(self, state: AgentState) -> AgentState:
        if not state["retrieve_conversation_history"]:
            self.logger.info(
                "Retrieve history node skipped id=%s user_id=%s",
                state["conversation_id"],
                state["user_id"],
            )
            return {}

        if len(state["conversation_history"]) > 0:
            self.logger.info(
                "Retrieve history node skipped id=%s user_id=%s reason=history_exists",
                state["conversation_id"],
                state["user_id"],
            )
            return {}

        self.logger.info(
            "Retrieve history node started id=%s user_id=%s",
            state["conversation_id"],
            state["user_id"],
        )
        results = await self.conversation_service.get(
            user_id=state["user_id"],
            conversation_id=state["conversation_id"],
        )
        if results is None:
            raise ValueError("Conversation not found")

        self.logger.info(
            "Retrieve history node completed id=%s user_id=%s count=%s",
            state["conversation_id"],
            state["user_id"],
            len(results.chats),
        )
        return {
            "conversation_history": results.chats,
            "conversation_summary": results.summary or "",
            "title": results.title or "",
        }
