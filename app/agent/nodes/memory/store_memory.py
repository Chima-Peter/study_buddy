from logging import Logger

from app.agent.schema import SUMMARY_EVERY
from app.agent.state import AgentState
from app.memory.service import MemoryService


class StoreMemoryNode:
    """Extract and store memories from recent user messages every SUMMARY_EVERY chats."""

    def __init__(self, memory_service: MemoryService, logger: Logger):
        self.memory_service = memory_service
        self.logger = logger

    async def __call__(self, state: AgentState) -> AgentState:
        if not state["conversation_history"]:
            self.logger.info(
                "Store memory node skipped id=%s user_id=%s reason=no_conversation_history",
                state["conversation_id"],
                state["user_id"],
            )
            return {}

        context = "\n".join(
            f"User: {chat.query}\nAssistant: {chat.response}"
            for chat in state["conversation_history"][-SUMMARY_EVERY:]
        )
        self.logger.info(
            "Store memory node started id=%s user_id=%s",
            state["conversation_id"],
            state["user_id"],
        )
        try:
            await self.memory_service.store(
                user_id=state["user_id"],
                context=context,
            )
        except Exception:
            self.logger.exception(
                "Store memory node failed id=%s user_id=%s",
                state["conversation_id"],
                state["user_id"],
            )
            return {}

        self.logger.info(
            "Store memory node completed id=%s user_id=%s",
            state["conversation_id"],
            state["user_id"],
        )
        return {}
